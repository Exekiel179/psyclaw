"""单因素 ANOVA — F 检验 + eta²/omega² + 成对事后检验（stdlib only）。

心理学研究中比较 3+ 组均值时必须先进行 ANOVA，显著后再做事后检验
（避免 α 膨胀）。

提供：
  - one_way_anova(groups)          → F/p/eta²/omega²
  - post_hoc_pairwise(groups)      → Holm 校正成对 t 检验 + Cohen's d
  - format_apa_anova(result)       → APA-7 摘要段落 + Markdown 均值表
  - write_anova_report(result)     → MD + JSON sidecar
  - analyze_anova(csv_path, ...)   → CSV 主入口
  - CLI: psyclaw anova <data.csv> --dv <col> --group <col>
         [--post-hoc] [--alpha .05] [--json] [--out dir]
"""

from __future__ import annotations

import csv
import json
import math
import pathlib
from typing import Any


# ---------------------------------------------------------------------------
# 分布工具（来自 descriptives.py 同款 _betai / _t_sf2）
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


def _t_sf2(t: float, df: float) -> float:
    if df <= 0:
        return float("nan")
    x = df / (df + t * t)
    return _betai(df / 2.0, 0.5, x)


def _f_sf(f: float, df1: float, df2: float) -> float:
    if f <= 0 or df1 <= 0 or df2 <= 0:
        return float("nan")
    x = df2 / (df2 + df1 * f)
    return _betai(df2 / 2.0, df1 / 2.0, x)


# ---------------------------------------------------------------------------
# 单因素 ANOVA 核心
# ---------------------------------------------------------------------------

def one_way_anova(
    groups: dict[str, list[float]],
    alpha: float = 0.05,
) -> dict[str, Any]:
    """单因素 ANOVA。

    groups: {组名: [观测值, ...]}
    返回 {F, df_between, df_within, p, eta2, omega2, grand_mean, group_stats}
    """
    k = len(groups)
    if k < 2:
        raise ValueError(f"至少需要 2 组（当前 {k} 组）")

    group_names = list(groups.keys())
    group_data = [groups[name] for name in group_names]

    ns = [len(g) for g in group_data]
    if any(n < 2 for n in ns):
        raise ValueError("每组至少需要 2 个观测值")

    N = sum(ns)
    means = [sum(g) / len(g) for g in group_data]
    grand_mean = sum(sum(g) for g in group_data) / N

    # SS_between / SS_within
    SS_b = sum(ns[i] * (means[i] - grand_mean) ** 2 for i in range(k))
    SS_w = sum(sum((v - means[i]) ** 2 for v in group_data[i]) for i in range(k))
    SS_t = SS_b + SS_w

    df_b = k - 1
    df_w = N - k

    if SS_w == 0:
        if SS_b == 0:
            # 完全简并：所有值相同 → F 未定义，返回无效果结果
            group_stats = [{"name": group_names[i], "n": ns[i],
                            "mean": round(means[i], 4), "sd": 0.0}
                           for i in range(k)]
            return {"F": 0.0, "df_between": df_b, "df_within": df_w, "p": 1.0,
                    "eta2": 0.0, "omega2": 0.0, "MS_between": 0.0, "MS_within": 0.0,
                    "SS_between": 0.0, "SS_within": 0.0, "SS_total": 0.0,
                    "N": N, "k": k, "grand_mean": round(grand_mean, 4),
                    "alpha": alpha, "group_stats": group_stats}
        return _perfect_separation(group_names, group_data, ns, means, grand_mean,
                                   SS_b, SS_w, SS_t, df_b, df_w, alpha)

    MS_b = SS_b / df_b
    MS_w = SS_w / df_w
    F = MS_b / MS_w
    p = _f_sf(F, df_b, df_w)

    # eta² = SS_b / SS_t
    eta2 = SS_b / SS_t if SS_t > 0 else 0.0

    # omega² = (SS_b - df_b * MS_w) / (SS_t + MS_w)（校正偏差的效应量）
    omega2 = max((SS_b - df_b * MS_w) / (SS_t + MS_w), 0.0) if SS_t + MS_w > 0 else 0.0

    group_stats = [
        {
            "name": group_names[i],
            "n": ns[i],
            "mean": round(means[i], 4),
            "sd": round(math.sqrt(sum((v - means[i]) ** 2 for v in group_data[i]) / (ns[i] - 1)), 4),
        }
        for i in range(k)
    ]

    return {
        "F": round(F, 4),
        "df_between": df_b,
        "df_within": df_w,
        "p": round(p, 6) if math.isfinite(p) else None,
        "eta2": round(eta2, 4),
        "omega2": round(omega2, 4),
        "MS_between": round(MS_b, 4),
        "MS_within": round(MS_w, 4),
        "SS_between": round(SS_b, 4),
        "SS_within": round(SS_w, 4),
        "SS_total": round(SS_t, 4),
        "N": N,
        "k": k,
        "grand_mean": round(grand_mean, 4),
        "alpha": alpha,
        "group_stats": group_stats,
    }


def _perfect_separation(names, data, ns, means, grand_mean, SS_b, SS_w, SS_t,
                         df_b, df_w, alpha) -> dict[str, Any]:
    """SS_within=0 时（各组内方差为 0）返回无穷大 F。"""
    k = len(names)
    N = sum(ns)
    group_stats = [
        {"name": names[i], "n": ns[i], "mean": round(means[i], 4), "sd": 0.0}
        for i in range(k)
    ]
    return {
        "F": float("inf"),
        "df_between": df_b,
        "df_within": df_w,
        "p": 0.0,
        "eta2": round(SS_b / SS_t, 4) if SS_t > 0 else 1.0,
        "omega2": 1.0,
        "MS_between": round(SS_b / df_b, 4) if df_b > 0 else float("inf"),
        "MS_within": 0.0,
        "SS_between": round(SS_b, 4),
        "SS_within": 0.0,
        "SS_total": round(SS_t, 4),
        "N": N,
        "k": k,
        "grand_mean": round(grand_mean, 4),
        "alpha": alpha,
        "group_stats": group_stats,
    }


# ---------------------------------------------------------------------------
# 事后成对 t 检验（Holm 校正 + Cohen's d）
# ---------------------------------------------------------------------------

def post_hoc_pairwise(
    groups: dict[str, list[float]],
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Welch t 成对检验 + Holm-Bonferroni 校正 + Cohen's d。

    返回 {comparisons, n_significant, method}
    """
    names = list(groups.keys())
    k = len(names)
    pairs = []
    for i in range(k):
        for j in range(i + 1, k):
            g1, g2 = groups[names[i]], groups[names[j]]
            n1, n2 = len(g1), len(g2)
            m1 = sum(g1) / n1
            m2 = sum(g2) / n2
            var1 = sum((v - m1) ** 2 for v in g1) / (n1 - 1) if n1 > 1 else 0.0
            var2 = sum((v - m2) ** 2 for v in g2) / (n2 - 1) if n2 > 1 else 0.0
            se = math.sqrt(var1 / n1 + var2 / n2)
            if se == 0:
                t, df, p = float("nan"), n1 + n2 - 2, float("nan")
            else:
                t = (m1 - m2) / se
                # Welch–Satterthwaite df
                num = (var1 / n1 + var2 / n2) ** 2
                den = (var1 / n1) ** 2 / (n1 - 1) + (var2 / n2) ** 2 / (n2 - 1)
                df = num / den if den > 0 else n1 + n2 - 2
                p = _t_sf2(abs(t), df)
            # Cohen's d（合并 SD）
            sp2 = ((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2) if n1 + n2 > 2 else 0.0
            sp = math.sqrt(sp2)
            d = (m1 - m2) / sp if sp > 0 else float("nan")
            pairs.append({
                "group1": names[i],
                "group2": names[j],
                "m1": round(m1, 4),
                "m2": round(m2, 4),
                "diff": round(m1 - m2, 4),
                "t": round(t, 4) if math.isfinite(t) else None,
                "df": round(df, 1),
                "p_orig": round(p, 6) if math.isfinite(p) else None,
                "d": round(d, 4) if math.isfinite(d) else None,
            })

    # Holm 校正
    from psyclaw.psych.multiple_testing import holm as _holm
    pvals = [pair["p_orig"] if pair["p_orig"] is not None else 1.0 for pair in pairs]
    labels = [f"{pair['group1']} vs {pair['group2']}" for pair in pairs]
    corr = _holm(pvals, alpha=alpha, labels=labels)

    for i, pair in enumerate(pairs):
        pair["p_adj"] = corr["tests"][i]["p_adj"]
        pair["reject_h0"] = corr["tests"][i]["reject_h0"]

    return {
        "comparisons": pairs,
        "method": "holm",
        "n_significant": sum(p["reject_h0"] for p in pairs),
        "alpha": alpha,
    }


# ---------------------------------------------------------------------------
# APA-7 格式化
# ---------------------------------------------------------------------------

def _fmt_p(p: float | None) -> str:
    if p is None or not math.isfinite(p):
        return "—"
    if p < 0.001:
        return "< .001"
    return f"= {p:.3f}".lstrip("0")


def format_apa_anova(result: dict[str, Any]) -> str:
    """生成 APA-7 ANOVA 摘要段落 + Markdown 描述统计表。"""
    k = result["k"]
    N = result["N"]
    F = result.get("F")
    df1 = result["df_between"]
    df2 = result["df_within"]
    p = result.get("p")
    eta2 = result.get("eta2", 0.0)
    omega2 = result.get("omega2", 0.0)

    F_str = f"> 1000" if isinstance(F, float) and F > 1000 else f"{F:.2f}" if F is not None else "—"
    p_str = _fmt_p(p)

    # 效应量语言标签
    from psyclaw.psych.effect_size import interpret_eta2
    interp = interpret_eta2(eta2)

    para = (
        f"单因素方差分析结果显示，*F*({df1}, {df2}) = {F_str}，"
        f"*p* {p_str}，*η*² = {eta2:.3f}（{interp}），"
        f"*ω*² = {omega2:.3f}（N = {N}）。"
    )

    # 均值表
    lines = [
        para, "",
        "| 组别 | *n* | *M* | *SD* |",
        "|------|-----|-----|------|",
    ]
    for g in result["group_stats"]:
        lines.append(f"| {g['name']} | {g['n']} | {g['mean']:.2f} | {g['sd']:.2f} |")
    lines += ["", "*注：M = 均值；SD = 标准差。*"]
    return "\n".join(lines)


def format_apa_post_hoc(ph_result: dict[str, Any]) -> str:
    """格式化事后检验结果为 Markdown 表格。"""
    lines = [
        "**成对事后检验（Holm 校正 Welch t）**", "",
        "| 对比 | *M* 差 | *t* | *df* | 原始 *p* | 校正 *p* | *d* | 显著 |",
        "|------|--------|-----|------|---------|---------|-----|------|",
    ]
    for c in ph_result["comparisons"]:
        t_str = f"{c['t']:.2f}" if c["t"] is not None else "—"
        sig = "✓" if c["reject_h0"] else ""
        d_str = f"{c['d']:.2f}" if c["d"] is not None else "—"
        lines.append(
            f"| {c['group1']} vs {c['group2']} | {c['diff']:.2f} | "
            f"{t_str} | {c['df']:.0f} | {_fmt_p(c['p_orig'])} | "
            f"{_fmt_p(c['p_adj'])} | {d_str} | {sig} |"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MD + JSON sidecar
# ---------------------------------------------------------------------------

def write_anova_report(
    result: dict[str, Any],
    ph_result: dict[str, Any] | None = None,
    out_dir: str | pathlib.Path = "notes",
) -> tuple[pathlib.Path, pathlib.Path]:
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    lines = [
        "# 单因素 ANOVA 报告",
        "",
        format_apa_anova(result),
    ]
    if ph_result:
        lines += ["", "## 事后检验", "", format_apa_post_hoc(ph_result)]

    md_path = out / "anova_report.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    payload: dict[str, Any] = {"anova": result}
    if ph_result:
        payload["post_hoc"] = ph_result
    json_path = out / "anova_report.json"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return md_path, json_path


# ---------------------------------------------------------------------------
# CSV 主入口
# ---------------------------------------------------------------------------

def analyze_anova(
    csv_path: str,
    dv: str,
    group_col: str,
    alpha: float = 0.05,
    include_post_hoc: bool = False,
    out_dir: str | pathlib.Path = "notes",
    write_files: bool = True,
) -> dict[str, Any]:
    """从 CSV 执行单因素 ANOVA。"""
    rows: list[dict[str, str]] = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows.append(dict(row))

    if not rows:
        raise ValueError(f"CSV 文件无数据行：{csv_path}")

    # 读取并按分组列分组
    groups: dict[str, list[float]] = {}
    n_excluded = 0
    for row in rows:
        dv_raw = row.get(dv, "").strip()
        grp = row.get(group_col, "").strip()
        if not dv_raw or not grp:
            n_excluded += 1
            continue
        try:
            v = float(dv_raw)
            if not math.isfinite(v):
                n_excluded += 1
                continue
        except ValueError:
            n_excluded += 1
            continue
        groups.setdefault(grp, []).append(v)

    if len(groups) < 2:
        raise ValueError(
            f"分组列 '{group_col}' 需要至少 2 个不同水平（发现 {len(groups)}）"
        )

    anova_result = one_way_anova(groups, alpha=alpha)
    anova_result["dv"] = dv
    anova_result["group_col"] = group_col
    anova_result["n_excluded"] = n_excluded
    anova_result["input_file"] = csv_path

    ph_result = post_hoc_pairwise(groups, alpha=alpha) if include_post_hoc else None

    result: dict[str, Any] = {"anova": anova_result}
    if ph_result:
        result["post_hoc"] = ph_result

    if write_files:
        md_path, json_path = write_anova_report(anova_result, ph_result, out_dir=out_dir)
        result["report_md"] = str(md_path)
        result["report_json"] = str(json_path)

    return result


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def anova_cli(args: list[str]) -> int:
    """psyclaw anova <data.csv> --dv <col> --group <col> [options]"""
    import argparse

    parser = argparse.ArgumentParser(
        prog="psyclaw anova",
        description="单因素 ANOVA：F/eta²/omega² + 可选 Holm 校正成对事后检验",
    )
    parser.add_argument("csv_file", help="输入数据 CSV 路径")
    parser.add_argument("--dv", required=True, help="因变量列名")
    parser.add_argument("--group", required=True, help="分组列名")
    parser.add_argument("--post-hoc", action="store_true", dest="post_hoc",
                        help="附加 Holm 校正成对 t 事后检验")
    parser.add_argument("--alpha", type=float, default=0.05,
                        help="显著性水平（默认 .05）")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    parser.add_argument("--out", default="notes", help="报告输出目录（默认 notes/）")
    opts = parser.parse_args(args)

    try:
        result = analyze_anova(
            csv_path=opts.csv_file,
            dv=opts.dv,
            group_col=opts.group,
            alpha=opts.alpha,
            include_post_hoc=opts.post_hoc,
            out_dir=opts.out,
        )
    except (ValueError, FileNotFoundError) as exc:
        print(f"错误：{exc}")
        return 1

    if opts.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0

    print()
    print(format_apa_anova(result["anova"]))
    if opts.post_hoc and "post_hoc" in result:
        print()
        print(format_apa_post_hoc(result["post_hoc"]))
    if "report_md" in result:
        print(f"\n报告已写入 {result['report_md']}")
    return 0
