"""双因素（析因）ANOVA — 主效应、交互效应、效应量（eta²/omega²），stdlib only。

心理学研究中比较两个独立因素（及其交互）时，双因素 ANOVA 是标准方法。
不等组距（非均衡设计）采用 Type-I SS（顺序）计算，与 R/SAS Type-I 一致。

提供：
  - two_way_anova(data, dv, fA, fB)   → 主效应A/B + 交互效应A×B + SS/MS/df/F/p/eta²
  - format_apa_anova2(result)          → APA-7 摘要段落 + Markdown ANOVA 表
  - write_anova2_report(result)        → MD + JSON sidecar
  - analyze_anova2(csv_path, ...)      → CSV 主入口
  - CLI: psyclaw anova2 <data.csv> --dv <col> --factorA <col> --factorB <col>
"""

from __future__ import annotations

import csv
import json
import math
import pathlib
from typing import Any


# ---------------------------------------------------------------------------
# 分布工具（与 anova.py 相同实现）
# ---------------------------------------------------------------------------

def _betai(a: float, b: float, x: float) -> float:
    if x < 0 or x > 1:
        return float("nan")
    if x == 0:
        return 0.0
    if x == 1:
        return 1.0
    if x > (a + 1) / (a + b + 2):
        return 1.0 - _betai(b, a, 1.0 - x)
    fpmin = 1e-300
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(math.log(x) * a + math.log(1 - x) * b - lbeta) / a
    c = 1.0
    d = 1.0 - (a + b) * x / (a + 1)
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, 200):
        m2 = 2 * m
        num = m * (b - m) * x / ((a + m2 - 1) * (a + m2))
        d = 1.0 + num * d
        c = 1.0 + num / c
        if abs(d) < fpmin: d = fpmin
        if abs(c) < fpmin: c = fpmin
        d = 1.0 / d
        h *= d * c
        num = -(a + m) * (a + b + m) * x / ((a + m2) * (a + m2 + 1))
        d = 1.0 + num * d
        c = 1.0 + num / c
        if abs(d) < fpmin: d = fpmin
        if abs(c) < fpmin: c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    return front * h


def _f_sf(f: float, df1: float, df2: float) -> float:
    if f <= 0 or df1 <= 0 or df2 <= 0:
        return float("nan")
    x = df2 / (df2 + df1 * f)
    return _betai(df2 / 2.0, df1 / 2.0, x)


# ---------------------------------------------------------------------------
# 双因素 ANOVA 核心（Type-I SS / 顺序平方和）
# ---------------------------------------------------------------------------

def two_way_anova(
    data: list[dict[str, Any]],
    dv: str,
    factorA: str,
    factorB: str,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """双因素析因 ANOVA。

    data: 行字典列表，每行含因变量与两个因子列
    dv: 因变量列名（数值）
    factorA / factorB: 因子列名（字符串水平）

    返回：{effectA, effectB, effectAB, error, total, cell_means, ...}
    每个 effect 含 {SS, df, MS, F, p, eta2, omega2}
    """
    # 读取有效行
    rows = []
    n_excluded = 0
    for row in data:
        try:
            v = float(row[dv])
            if not math.isfinite(v):
                n_excluded += 1
                continue
            a_lvl = str(row[factorA]).strip()
            b_lvl = str(row[factorB]).strip()
            if not a_lvl or not b_lvl:
                n_excluded += 1
                continue
            rows.append({"dv": v, "A": a_lvl, "B": b_lvl})
        except (KeyError, ValueError, TypeError):
            n_excluded += 1

    if not rows:
        raise ValueError("有效数据行为空，请检查列名与数值格式")

    a_levels = sorted(set(r["A"] for r in rows))
    b_levels = sorted(set(r["B"] for r in rows))
    a = len(a_levels)
    b = len(b_levels)
    if a < 2:
        raise ValueError(f"因子 A 需至少 2 个水平（当前 {a}）")
    if b < 2:
        raise ValueError(f"因子 B 需至少 2 个水平（当前 {b}）")

    N = len(rows)
    grand_mean = sum(r["dv"] for r in rows) / N

    # --- SS_total ---
    SS_t = sum((r["dv"] - grand_mean) ** 2 for r in rows)

    # --- SS_A（因子 A 主效应）---
    mean_A: dict[str, float] = {}
    n_A: dict[str, int] = {}
    for lvl in a_levels:
        vals = [r["dv"] for r in rows if r["A"] == lvl]
        n_A[lvl] = len(vals)
        mean_A[lvl] = sum(vals) / len(vals)
    SS_A = sum(n_A[lvl] * (mean_A[lvl] - grand_mean) ** 2 for lvl in a_levels)
    df_A = a - 1

    # --- SS_B（因子 B 主效应）---
    mean_B: dict[str, float] = {}
    n_B: dict[str, int] = {}
    for lvl in b_levels:
        vals = [r["dv"] for r in rows if r["B"] == lvl]
        n_B[lvl] = len(vals)
        mean_B[lvl] = sum(vals) / len(vals)
    SS_B = sum(n_B[lvl] * (mean_B[lvl] - grand_mean) ** 2 for lvl in b_levels)
    df_B = b - 1

    # --- SS_cells（各单元格效应）---
    cell_data: dict[tuple[str, str], list[float]] = {}
    for r in rows:
        key = (r["A"], r["B"])
        cell_data.setdefault(key, []).append(r["dv"])

    cell_means: dict[tuple[str, str], float] = {
        k: sum(vs) / len(vs) for k, vs in cell_data.items()
    }
    cell_ns: dict[tuple[str, str], int] = {k: len(vs) for k, vs in cell_data.items()}

    SS_cells = sum(
        cell_ns[k] * (cell_means[k] - grand_mean) ** 2
        for k in cell_data
    )

    # --- SS_AB（交互效应 = SS_cells - SS_A - SS_B）---
    SS_AB = SS_cells - SS_A - SS_B
    df_AB = df_A * df_B

    # --- SS_error（组内误差）---
    SS_e = sum(
        (v - cell_means[(r["A"], r["B"])]) ** 2
        for r in rows
        for v in [r["dv"]]
    )
    df_e = N - a * b

    if df_e <= 0:
        raise ValueError(
            f"误差 df = {df_e}：每个单元格至少需要 2 个观测（{a}×{b}={a*b} 单元格，N={N}）"
        )

    MS_e = SS_e / df_e

    def _effect(SS: float, df: int, label: str) -> dict[str, Any]:
        if df <= 0 or SS < 0:
            return {"SS": round(SS, 4), "df": df, "MS": None, "F": None,
                    "p": None, "eta2": None, "omega2": None}
        MS = SS / df
        if MS_e == 0:
            F = float("inf") if MS > 0 else 0.0
        else:
            F = MS / MS_e
        # F=0 → p=1 (no deviation from null); F=inf → p=0
        if F == 0.0:
            p = 1.0
        elif not math.isfinite(F):
            p = 0.0
        else:
            p = _f_sf(F, df, df_e)
        eta2 = SS / SS_t if SS_t > 0 else 0.0
        omega2 = max((SS - df * MS_e) / (SS_t + MS_e), 0.0) if SS_t + MS_e > 0 else 0.0
        return {
            "SS": round(SS, 4),
            "df": df,
            "MS": round(MS, 4),
            "F": round(F, 4) if math.isfinite(F) else None,
            "p": round(p, 6) if math.isfinite(p) else None,
            "eta2": round(eta2, 4),
            "omega2": round(omega2, 4),
        }

    # 单元格均值表（嵌套字典）
    cell_means_table: dict[str, dict[str, float]] = {}
    for a_lvl in a_levels:
        cell_means_table[a_lvl] = {}
        for b_lvl in b_levels:
            key = (a_lvl, b_lvl)
            if key in cell_means:
                cell_means_table[a_lvl][b_lvl] = round(cell_means[key], 4)
            else:
                cell_means_table[a_lvl][b_lvl] = None  # type: ignore[assignment]

    return {
        "effectA": _effect(SS_A, df_A, factorA),
        "effectB": _effect(SS_B, df_B, factorB),
        "effectAB": _effect(SS_AB, df_AB, f"{factorA}×{factorB}"),
        "error": {
            "SS": round(SS_e, 4),
            "df": df_e,
            "MS": round(MS_e, 4),
        },
        "total": {"SS": round(SS_t, 4), "df": N - 1},
        "N": N,
        "n_excluded": n_excluded,
        "a_levels": a_levels,
        "b_levels": b_levels,
        "cell_means": cell_means_table,
        "grand_mean": round(grand_mean, 4),
        "factorA": factorA,
        "factorB": factorB,
        "dv": dv,
        "alpha": alpha,
    }


# ---------------------------------------------------------------------------
# APA-7 格式化
# ---------------------------------------------------------------------------

def _fmt_p(p: float | None) -> str:
    if p is None or (isinstance(p, float) and not math.isfinite(p)):
        return "—"
    if p < 0.001:
        return "< .001"
    return f"= {p:.3f}".lstrip("0")


def _fmt_f(eff: dict[str, Any]) -> str:
    F = eff.get("F")
    if F is None:
        return "—"
    df1 = eff["df"]
    df2_key = "error"
    return f"*F*({df1}, df_e) = {F:.2f}"


def format_apa_anova2(result: dict[str, Any]) -> str:
    """生成 APA-7 双因素 ANOVA 摘要段落 + Markdown 方差分析表 + 单元格均值表。"""
    fA = result["factorA"]
    fB = result["factorB"]
    dv = result["dv"]
    N = result["N"]
    df_e = result["error"]["df"]

    lines = [f"双因素析因 ANOVA（因变量：{dv}，N = {N}）", ""]

    # ANOVA 汇总表
    lines += [
        "| 来源 | *SS* | *df* | *MS* | *F* | *p* | *η*² | *ω*² |",
        "|------|------|------|------|-----|-----|------|------|",
    ]
    for label, key in [(fA, "effectA"), (fB, "effectB"),
                       (f"{fA}×{fB}", "effectAB")]:
        eff = result[key]
        F_str = f"{eff['F']:.2f}" if eff.get("F") is not None else "—"
        p_str = _fmt_p(eff.get("p"))
        eta2_str = f"{eff['eta2']:.3f}" if eff.get("eta2") is not None else "—"
        omega2_str = f"{eff['omega2']:.3f}" if eff.get("omega2") is not None else "—"
        ms_val = eff.get("MS")
        ms_str = f"{ms_val:.2f}" if ms_val is not None else "—"
        lines.append(
            f"| {label} | {eff['SS']:.2f} | {eff['df']} | "
            f"{ms_str} | "
            f"{F_str} | {p_str} | {eta2_str} | {omega2_str} |"
        )
    err = result["error"]
    lines.append(f"| 误差 | {err['SS']:.2f} | {df_e} | {err['MS']:.2f} | — | — | — | — |")
    tot = result["total"]
    lines.append(f"| 合计 | {tot['SS']:.2f} | {tot['df']} | — | — | — | — | — |")

    # 各效应文字描述
    lines.append("")
    for label, key in [(fA, "effectA"), (fB, "effectB"),
                       (f"{fA} × {fB}", "effectAB")]:
        eff = result[key]
        F = eff.get("F")
        p = eff.get("p")
        eta2 = eff.get("eta2", 0.0)
        sig_str = "达到统计显著性" if (p is not None and p < result["alpha"]) else "未达到统计显著性"
        if F is not None:
            lines.append(
                f"{label} 主效应：*F*({eff['df']}, {df_e}) = {F:.2f}，"
                f"*p* {_fmt_p(p)}，*η*² = {eta2:.3f}，{sig_str}。"
            )

    # 单元格均值表
    a_levels = result["a_levels"]
    b_levels = result["b_levels"]
    lines += [
        "",
        f"**单元格均值（行={fA}，列={fB}）**", "",
        "| " + fA + " \\ " + fB + " | " + " | ".join(b_levels) + " |",
        "|" + "---|" * (len(b_levels) + 1),
    ]
    for a_lvl in a_levels:
        vals = [
            f"{result['cell_means'][a_lvl].get(b_lvl, '—')}"
            if result["cell_means"].get(a_lvl) else "—"
            for b_lvl in b_levels
        ]
        lines.append(f"| {a_lvl} | " + " | ".join(vals) + " |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MD + JSON sidecar
# ---------------------------------------------------------------------------

def write_anova2_report(
    result: dict[str, Any],
    out_dir: str | pathlib.Path = "notes",
) -> tuple[pathlib.Path, pathlib.Path]:
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    lines = ["# 双因素析因 ANOVA 报告", "", format_apa_anova2(result)]
    md_path = out / "anova2_report.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    json_path = out / "anova2_report.json"
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return md_path, json_path


# ---------------------------------------------------------------------------
# CSV 主入口
# ---------------------------------------------------------------------------

def analyze_anova2(
    csv_path: str,
    dv: str,
    factorA: str,
    factorB: str,
    alpha: float = 0.05,
    out_dir: str | pathlib.Path = "notes",
    write_files: bool = True,
) -> dict[str, Any]:
    """从 CSV 执行双因素析因 ANOVA。"""
    rows: list[dict[str, str]] = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows.append(dict(row))

    if not rows:
        raise ValueError(f"CSV 文件无数据行：{csv_path}")

    result = two_way_anova(rows, dv=dv, factorA=factorA, factorB=factorB, alpha=alpha)
    result["input_file"] = csv_path

    if write_files:
        md_path, json_path = write_anova2_report(result, out_dir=out_dir)
        result["report_md"] = str(md_path)
        result["report_json"] = str(json_path)

    return result


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def anova2_cli(args: list[str]) -> int:
    """psyclaw anova2 <data.csv> --dv <col> --factorA <col> --factorB <col> [options]"""
    import argparse

    parser = argparse.ArgumentParser(
        prog="psyclaw anova2",
        description="双因素析因 ANOVA：主效应 A/B + 交互效应 A×B + eta²/omega²",
    )
    parser.add_argument("csv_file", help="输入数据 CSV 路径")
    parser.add_argument("--dv", required=True, help="因变量列名")
    parser.add_argument("--factorA", required=True, help="因子 A 列名")
    parser.add_argument("--factorB", required=True, help="因子 B 列名")
    parser.add_argument("--alpha", type=float, default=0.05,
                        help="显著性水平（默认 .05）")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    parser.add_argument("--out", default="notes", help="报告输出目录（默认 notes/）")
    opts = parser.parse_args(args)

    try:
        result = analyze_anova2(
            csv_path=opts.csv_file,
            dv=opts.dv,
            factorA=opts.factorA,
            factorB=opts.factorB,
            alpha=opts.alpha,
            out_dir=opts.out,
        )
    except (ValueError, FileNotFoundError) as exc:
        print(f"错误：{exc}")
        return 1

    if opts.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0

    print()
    print(format_apa_anova2(result))
    if "report_md" in result:
        print(f"\n报告已写入 {result['report_md']}")
    return 0
