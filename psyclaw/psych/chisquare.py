"""卡方检验 — 拟合优度 / 独立性检验 / Cramér's V / Fisher 精确检验（Monte Carlo），stdlib only。

心理学研究中分类数据（频率/比例/列联表）的标准分析工具。

提供：
  - chi2_goodness_of_fit(observed, expected)  → χ²/df/p/w 效应量
  - chi2_independence(table)                  → χ²/df/p/phi/cramers_v + 期望频率表
  - fisher_exact_2x2(table)                   → OR/p（双尾）
  - format_apa_chi2(result)                   → APA-7 段落
  - write_chi2_report(result)                 → MD + JSON sidecar
  - analyze_chi2(csv_path, ...)               → CSV 主入口
  - CLI: psyclaw chi2 <data.csv> --test gof|independence ...
"""

from __future__ import annotations

import csv
import json
import math
import pathlib
import random
from typing import Any

from scipy import stats


# ---------------------------------------------------------------------------
# 分布工具（scipy）
# ---------------------------------------------------------------------------

def _chi2_sf(x: float, df: float) -> float:
    """χ² 分布上尾 P(X > x)，df 自由度。"""
    if x <= 0 or df <= 0:
        return 1.0 if x <= 0 else 0.0
    return float(stats.chi2.sf(x, df))


# ---------------------------------------------------------------------------
# 拟合优度检验（Goodness of Fit）
# ---------------------------------------------------------------------------

def chi2_goodness_of_fit(
    observed: list[float],
    expected: list[float] | None = None,
    alpha: float = 0.05,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """χ² 拟合优度检验。

    observed: 观测频率列表
    expected: 期望频率列表（None → 均匀分布）
    效应量 w = √(χ²/N)（Cohen 1988）
    """
    k = len(observed)
    if k < 2:
        raise ValueError(f"至少需要 2 个类别（当前 {k}）")
    N = sum(observed)
    if N <= 0:
        raise ValueError("观测频率之和必须 > 0")

    if expected is None:
        expected = [N / k] * k
    elif len(expected) != k:
        raise ValueError(f"observed 和 expected 长度不一致（{k} vs {len(expected)}）")

    exp_sum = sum(expected)
    if abs(exp_sum - N) > 1e-6:
        # 允许期望以比例形式传入，自动缩放
        scale = N / exp_sum
        expected = [e * scale for e in expected]

    # 小期望频率警告（< 5 的单元格 > 20%）
    small_expected = sum(1 for e in expected if e < 5)
    warn_small = small_expected / k > 0.20

    chi2 = sum((o - e) ** 2 / e for o, e in zip(observed, expected) if e > 0)
    df = k - 1
    p = _chi2_sf(chi2, df)
    w = math.sqrt(chi2 / N) if N > 0 else 0.0

    cells = []
    for i in range(k):
        cells.append({
            "label": labels[i] if labels else str(i),
            "observed": observed[i],
            "expected": round(expected[i], 4),
            "residual": round(observed[i] - expected[i], 4),
        })

    return {
        "test": "chi2_gof",
        "chi2": round(chi2, 4),
        "df": df,
        "p": round(p, 6),
        "N": N,
        "w": round(w, 4),
        "alpha": alpha,
        "significant": p < alpha,
        "warn_small_expected": warn_small,
        "cells": cells,
    }


# ---------------------------------------------------------------------------
# 独立性检验（Contingency Table）
# ---------------------------------------------------------------------------

def chi2_independence(
    table: list[list[float]],
    row_labels: list[str] | None = None,
    col_labels: list[str] | None = None,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """χ² 独立性检验（列联表）。

    table: R×C 二维观测频率矩阵
    效应量：phi（2×2）/ Cramér's V（一般）
    """
    R = len(table)
    if R < 2:
        raise ValueError(f"至少需要 2 行（当前 {R}）")
    C = len(table[0])
    if C < 2:
        raise ValueError(f"至少需要 2 列（当前 {C}）")
    if any(len(row) != C for row in table):
        raise ValueError("列联表各行列数不一致")

    row_sums = [sum(table[r]) for r in range(R)]
    col_sums = [sum(table[r][c] for r in range(R)) for c in range(C)]
    N = sum(row_sums)
    if N <= 0:
        raise ValueError("列联表总频率之和必须 > 0")

    # 期望频率
    expected = [[row_sums[r] * col_sums[c] / N for c in range(C)] for r in range(R)]

    # 小期望频率检查
    small_count = sum(1 for r in range(R) for c in range(C) if expected[r][c] < 5)
    total_cells = R * C
    warn_small = small_count / total_cells > 0.20

    chi2 = sum(
        (table[r][c] - expected[r][c]) ** 2 / expected[r][c]
        for r in range(R) for c in range(C)
        if expected[r][c] > 0
    )
    df = (R - 1) * (C - 1)
    p = _chi2_sf(chi2, df)

    phi = math.sqrt(chi2 / N)
    # Cramér's V = phi / √(min(R,C)-1)
    cramers_v = phi / math.sqrt(min(R, C) - 1) if min(R, C) > 1 else phi

    # 调整后 Cramér's V（Bergsma 2013 偏倚校正）
    phi2_corr = max(phi ** 2 - (R - 1) * (C - 1) / (N - 1), 0.0)
    k_corr = min(R, C) - (min(R, C) - 1) ** 2 / (N - 1)
    cramers_v_adj = math.sqrt(phi2_corr / (k_corr - 1)) if k_corr > 1 else 0.0

    return {
        "test": "chi2_independence",
        "chi2": round(chi2, 4),
        "df": df,
        "p": round(p, 6),
        "N": N,
        "phi": round(phi, 4),
        "cramers_v": round(cramers_v, 4),
        "cramers_v_adj": round(cramers_v_adj, 4),
        "R": R,
        "C": C,
        "alpha": alpha,
        "significant": p < alpha,
        "warn_small_expected": warn_small,
        "expected": [[round(expected[r][c], 4) for c in range(C)] for r in range(R)],
        "row_labels": row_labels or [f"R{r+1}" for r in range(R)],
        "col_labels": col_labels or [f"C{c+1}" for c in range(C)],
        "row_sums": row_sums,
        "col_sums": col_sums,
    }


# ---------------------------------------------------------------------------
# Fisher 精确检验（2×2 表，双尾）
# ---------------------------------------------------------------------------

def fisher_exact_2x2(
    table: list[list[float]],
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Fisher 精确检验（仅适用于 2×2 列联表）。

    使用超几何分布精确计算 p 值（双尾，条件于边缘合计）。
    """
    if len(table) != 2 or any(len(r) != 2 for r in table):
        raise ValueError("Fisher 精确检验仅适用于 2×2 列联表")
    a, b = int(table[0][0]), int(table[0][1])
    c, d = int(table[1][0]), int(table[1][1])
    N = a + b + c + d
    if N <= 0:
        raise ValueError("列联表总频率之和必须 > 0")

    # 比值比（Odds Ratio）
    if b * c == 0:
        OR = float("inf") if a * d > 0 else float("nan")
    else:
        OR = (a * d) / (b * c)

    # 双尾精确 p（超几何分布，条件于边缘合计）—— scipy
    _, p_value = stats.fisher_exact([[a, b], [c, d]], alternative="two-sided")
    p_value = float(p_value)

    return {
        "test": "fisher_exact",
        "OR": round(OR, 4) if math.isfinite(OR) else str(OR),
        "p": round(p_value, 6),
        "a": a, "b": b, "c": c, "d": d,
        "N": N,
        "alpha": alpha,
        "significant": p_value < alpha,
    }


# ---------------------------------------------------------------------------
# 效应量解读
# ---------------------------------------------------------------------------

def _interpret_cramers_v(v: float, df_min: int) -> str:
    """Cohen (1988) 基于 df_min = min(R,C)-1 的 Cramér's V 语言标签。"""
    thresholds = {1: (0.10, 0.30, 0.50), 2: (0.07, 0.21, 0.35), 3: (0.06, 0.17, 0.29)}
    sm, md, lg = thresholds.get(df_min, (0.05, 0.15, 0.25))
    if v >= lg:
        return "大效应"
    if v >= md:
        return "中效应"
    if v >= sm:
        return "小效应"
    return "微效应"


def _interpret_w(w: float) -> str:
    if w >= 0.50:
        return "大效应"
    if w >= 0.30:
        return "中效应"
    if w >= 0.10:
        return "小效应"
    return "微效应"


# ---------------------------------------------------------------------------
# APA-7 格式化
# ---------------------------------------------------------------------------

def _fmt_p(p: float | None) -> str:
    if p is None:
        return "—"
    if p < 0.001:
        return "< .001"
    return f"= {p:.3f}".lstrip("0")


def format_apa_chi2(result: dict[str, Any]) -> str:
    """生成 APA-7 卡方检验段落（+ 期望频率警告）。"""
    test = result["test"]
    chi2 = result.get("chi2")
    df = result.get("df")
    p = result.get("p")
    N = result["N"]
    sig_str = "达到统计显著性" if result.get("significant") else "未达到统计显著性"
    p_str = _fmt_p(p)

    lines = []
    if test == "chi2_gof":
        w = result.get("w", 0.0)
        interp = _interpret_w(w)
        lines.append(
            f"χ² 拟合优度检验结果显示，*χ*²({df}) = {chi2:.2f}，"
            f"*p* {p_str}，*w* = {w:.3f}（{interp}，N = {N}），{sig_str}。"
        )
        # 单元格表
        lines += ["", "| 类别 | 观测 | 期望 | 残差 |", "|------|------|------|------|"]
        for cell in result.get("cells", []):
            lines.append(
                f"| {cell['label']} | {cell['observed']} | {cell['expected']} | {cell['residual']} |"
            )

    elif test == "chi2_independence":
        v = result.get("cramers_v", 0.0)
        df_min = min(result["R"], result["C"]) - 1
        interp = _interpret_cramers_v(v, df_min)
        phi_str = f"*φ* = {result['phi']:.3f}，" if result["R"] == 2 and result["C"] == 2 else ""
        lines.append(
            f"χ² 独立性检验结果显示，*χ*²({df}, N = {N}) = {chi2:.2f}，"
            f"*p* {p_str}，{phi_str}*V* = {v:.3f}（{interp}），{sig_str}。"
        )
        # 期望频率表
        rows_lbl = result["row_labels"]
        cols_lbl = result["col_labels"]
        lines += ["", f"**期望频率表**", "",
                  "| — | " + " | ".join(cols_lbl) + " |",
                  "|---|" + "---|" * len(cols_lbl)]
        for r, row_lbl in enumerate(rows_lbl):
            vals = " | ".join(str(result["expected"][r][c]) for c in range(result["C"]))
            lines.append(f"| {row_lbl} | {vals} |")

    elif test == "fisher_exact":
        OR = result.get("OR")
        OR_str = f"{OR:.3f}" if isinstance(OR, float) else str(OR)
        lines.append(
            f"Fisher 精确检验结果显示，OR = {OR_str}，"
            f"*p* {p_str}（双尾，N = {N}），{sig_str}。"
        )

    if result.get("warn_small_expected"):
        lines += ["", "*注：超过 20% 的单元格期望频率 < 5，建议考虑 Fisher 精确检验或合并类别。*"]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MD + JSON sidecar
# ---------------------------------------------------------------------------

def write_chi2_report(
    result: dict[str, Any],
    out_dir: str | pathlib.Path = "notes",
    filename: str = "chi2_report",
) -> tuple[pathlib.Path, pathlib.Path]:
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    test_labels = {"chi2_gof": "拟合优度", "chi2_independence": "独立性", "fisher_exact": "Fisher精确"}
    label = test_labels.get(result.get("test", ""), "卡方检验")
    lines = [f"# 卡方检验报告：{label}", "", format_apa_chi2(result)]
    md_path = out / f"{filename}.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    json_path = out / f"{filename}.json"
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return md_path, json_path


# ---------------------------------------------------------------------------
# CSV 主入口
# ---------------------------------------------------------------------------

def analyze_chi2(
    csv_path: str,
    test: str,
    row_col: str | None = None,
    col_col: str | None = None,
    obs_col: str | None = None,
    exp_col: str | None = None,
    label_col: str | None = None,
    alpha: float = 0.05,
    out_dir: str | pathlib.Path = "notes",
    write_files: bool = True,
) -> dict[str, Any]:
    """从 CSV 执行卡方检验。

    test: 'gof' | 'independence' | 'fisher'
    """
    rows: list[dict[str, str]] = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows.append(dict(row))

    test = test.lower()

    if test == "gof":
        # CSV 格式：label_col（可选）+ obs_col + exp_col（可选）
        if obs_col is None:
            raise ValueError("拟合优度检验需要 --obs 参数（观测频率列名）")
        observed, expected, labels = [], [], []
        for row in rows:
            try:
                observed.append(float(row[obs_col]))
                if exp_col and row.get(exp_col, "").strip():
                    expected.append(float(row[exp_col]))
                if label_col:
                    labels.append(row.get(label_col, "").strip())
            except (ValueError, KeyError):
                continue
        exp_arg = expected if expected else None
        lbl_arg = labels if labels else None
        result = chi2_goodness_of_fit(observed, expected=exp_arg, alpha=alpha, labels=lbl_arg)

    elif test in ("independence", "fisher"):
        # CSV 格式：row_col + col_col（原始数据，每行一个观测）
        if row_col is None or col_col is None:
            raise ValueError(f"{test} 检验需要 --row-col 和 --col-col 参数")
        # 构建列联表
        row_vals, col_vals = set(), set()
        for row in rows:
            r_v = row.get(row_col, "").strip()
            c_v = row.get(col_col, "").strip()
            if r_v and c_v:
                row_vals.add(r_v)
                col_vals.add(c_v)
        row_order = sorted(row_vals)
        col_order = sorted(col_vals)
        table = [[0.0] * len(col_order) for _ in range(len(row_order))]
        r_idx = {v: i for i, v in enumerate(row_order)}
        c_idx = {v: i for i, v in enumerate(col_order)}
        for row in rows:
            r_v = row.get(row_col, "").strip()
            c_v = row.get(col_col, "").strip()
            if r_v in r_idx and c_v in c_idx:
                table[r_idx[r_v]][c_idx[c_v]] += 1
        if test == "fisher":
            result = fisher_exact_2x2(table, alpha=alpha)
        else:
            result = chi2_independence(table, row_labels=row_order,
                                       col_labels=col_order, alpha=alpha)
    else:
        raise ValueError(f"未知检验类型 '{test}'，可选：gof | independence | fisher")

    result["input_file"] = csv_path

    if write_files:
        fname = f"chi2_{test}_report"
        md_path, json_path = write_chi2_report(result, out_dir=out_dir, filename=fname)
        result["report_md"] = str(md_path)
        result["report_json"] = str(json_path)

    return result


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def chi2_cli(args: list[str]) -> int:
    """psyclaw chi2 <data.csv> --test gof|independence|fisher [options]"""
    import argparse

    parser = argparse.ArgumentParser(
        prog="psyclaw chi2",
        description="卡方检验：拟合优度 / 独立性 / Fisher 精确检验",
    )
    parser.add_argument("csv_file", help="输入数据 CSV 路径")
    parser.add_argument(
        "--test",
        required=True,
        choices=["gof", "independence", "fisher"],
        help="检验类型：gof（拟合优度）| independence（独立性）| fisher（Fisher精确）",
    )
    parser.add_argument("--obs", dest="obs_col", default=None,
                        help="观测频率列名（gof 必需）")
    parser.add_argument("--exp", dest="exp_col", default=None,
                        help="期望频率列名（gof 可选，默认均匀分布）")
    parser.add_argument("--label", dest="label_col", default=None,
                        help="类别标签列名（gof 可选）")
    parser.add_argument("--row-col", dest="row_col", default=None,
                        help="行因子列名（independence/fisher 必需）")
    parser.add_argument("--col-col", dest="col_col", default=None,
                        help="列因子列名（independence/fisher 必需）")
    parser.add_argument("--alpha", type=float, default=0.05,
                        help="显著性水平（默认 .05）")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    parser.add_argument("--out", default="notes", help="报告输出目录（默认 notes/）")
    opts = parser.parse_args(args)

    try:
        result = analyze_chi2(
            csv_path=opts.csv_file,
            test=opts.test,
            row_col=opts.row_col,
            col_col=opts.col_col,
            obs_col=opts.obs_col,
            exp_col=opts.exp_col,
            label_col=opts.label_col,
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
    print(format_apa_chi2(result))
    if "report_md" in result:
        print(f"\n报告已写入 {result['report_md']}")
    return 0
