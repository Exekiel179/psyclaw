"""多重检验校正 — Bonferroni / Holm / Benjamini-Hochberg FDR（stdlib only）。

心理学研究常同时进行多个假设检验（多个相关、多个组间比较），需控制
家族错误率（FWER）或虚假发现率（FDR）。

提供：
  - bonferroni(pvals, alpha)       → FWER 控制（最保守）
  - holm(pvals, alpha)             → Holm step-down FWER 控制（比 Bonferroni 更有效）
  - benjamini_hochberg(pvals, alpha) → BH FDR 控制（推荐，广泛用于探索性研究）
  - interpret_correction(result)   → 决策摘要
  - format_apa_corrections(result) → APA-7 段落
  - analyze_corrections(csv_path)  → 从 CSV p 值列批量校正
  - CLI: psyclaw correct-p <p1,p2,...|csv> [--method bh|holm|bonferroni] [--alpha .05]

参考：
  Bonferroni, C. E. (1936). Teoria statistica delle classi e calcolo delle probabilità.
  Holm, S. (1979). A simple sequentially rejective multiple test procedure.
    *Scandinavian Journal of Statistics*, 6(2), 65–70.
  Benjamini, Y., & Hochberg, Y. (1995). Controlling the false discovery rate:
    A practical and powerful approach to multiple testing.
    *Journal of the Royal Statistical Society, Series B*, 57(1), 289–300.
"""

from __future__ import annotations

import csv
import json
import math
import pathlib
from typing import Any


# ---------------------------------------------------------------------------
# Bonferroni 校正
# ---------------------------------------------------------------------------

def bonferroni(
    pvals: list[float],
    alpha: float = 0.05,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Bonferroni 校正：阈值 = alpha / m。

    返回每个检验的调整 p 值（min(p*m, 1)）和显著性决策。
    """
    m = len(pvals)
    if m == 0:
        return _empty_result("bonferroni", alpha)

    adjusted = [min(p * m, 1.0) for p in pvals]
    reject = [ap < alpha for ap in adjusted]
    threshold = alpha / m

    lbs = labels or [f"检验{i + 1}" for i in range(m)]
    tests = [
        {
            "label": lbs[i],
            "p_orig": round(pvals[i], 6),
            "p_adj": round(adjusted[i], 6),
            "reject_h0": reject[i],
        }
        for i in range(m)
    ]
    return {
        "method": "bonferroni",
        "m": m,
        "alpha": alpha,
        "threshold": round(threshold, 8),
        "n_rejected": sum(reject),
        "tests": tests,
    }


# ---------------------------------------------------------------------------
# Holm step-down
# ---------------------------------------------------------------------------

def holm(
    pvals: list[float],
    alpha: float = 0.05,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Holm (1979) 逐步降低 FWER 校正。

    按 p 从小到大排序，第 k 步（1-indexed）阈值 = alpha / (m - k + 1)。
    一旦不显著，后续均不显著（单调性保持）。
    """
    m = len(pvals)
    if m == 0:
        return _empty_result("holm", alpha)

    lbs = labels or [f"检验{i + 1}" for i in range(m)]
    order = sorted(range(m), key=lambda i: pvals[i])

    reject_flags = [False] * m
    stopped = False
    for rank, idx in enumerate(order):
        if stopped:
            reject_flags[idx] = False
        else:
            threshold_k = alpha / (m - rank)
            if pvals[idx] <= threshold_k:
                reject_flags[idx] = True
            else:
                stopped = True
                reject_flags[idx] = False

    # 调整 p 值：p_adj_i = max_{k ≤ i} min(p_k * (m - k + 1), 1)（单调性保持）
    adj_p_by_order = [0.0] * m
    for rank, idx in enumerate(order):
        adj_p_by_order[rank] = min(pvals[idx] * (m - rank), 1.0)
    # 强制单调递增
    for rank in range(1, m):
        adj_p_by_order[rank] = max(adj_p_by_order[rank], adj_p_by_order[rank - 1])

    adjusted = [0.0] * m
    for rank, idx in enumerate(order):
        adjusted[idx] = adj_p_by_order[rank]

    tests = [
        {
            "label": lbs[i],
            "p_orig": round(pvals[i], 6),
            "p_adj": round(adjusted[i], 6),
            "reject_h0": reject_flags[i],
        }
        for i in range(m)
    ]
    return {
        "method": "holm",
        "m": m,
        "alpha": alpha,
        "n_rejected": sum(reject_flags),
        "tests": tests,
    }


# ---------------------------------------------------------------------------
# Benjamini-Hochberg FDR
# ---------------------------------------------------------------------------

def benjamini_hochberg(
    pvals: list[float],
    alpha: float = 0.05,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Benjamini & Hochberg (1995) FDR 校正。

    按 p 从小到大排序，第 k 步阈值 = (k/m) * alpha。
    找最大的 k 使得 p_(k) ≤ (k/m)*alpha，拒绝前 k 个。
    """
    m = len(pvals)
    if m == 0:
        return _empty_result("benjamini_hochberg", alpha)

    lbs = labels or [f"检验{i + 1}" for i in range(m)]
    order = sorted(range(m), key=lambda i: pvals[i])

    # 找最大 k（1-indexed）满足 p_(k) ≤ k*alpha/m
    last_reject = -1
    for rank, idx in enumerate(order):
        threshold_k = (rank + 1) * alpha / m
        if pvals[idx] <= threshold_k:
            last_reject = rank

    reject_flags = [False] * m
    for rank in range(last_reject + 1):
        reject_flags[order[rank]] = True

    # 调整 p 值（BH adjusted = min_{k'≥k} (m/k') * p_(k')，单调降级）
    adj_p_by_order = [0.0] * m
    for rank, idx in enumerate(order):
        adj_p_by_order[rank] = min((m / (rank + 1)) * pvals[idx], 1.0)
    # 强制单调递减（从大到小累积最小值）
    for rank in range(m - 2, -1, -1):
        adj_p_by_order[rank] = min(adj_p_by_order[rank], adj_p_by_order[rank + 1])

    adjusted = [0.0] * m
    for rank, idx in enumerate(order):
        adjusted[idx] = adj_p_by_order[rank]

    tests = [
        {
            "label": lbs[i],
            "p_orig": round(pvals[i], 6),
            "p_adj": round(adjusted[i], 6),
            "reject_h0": reject_flags[i],
        }
        for i in range(m)
    ]
    return {
        "method": "benjamini_hochberg",
        "m": m,
        "alpha": alpha,
        "n_rejected": sum(reject_flags),
        "tests": tests,
    }


def _empty_result(method: str, alpha: float) -> dict[str, Any]:
    return {"method": method, "m": 0, "alpha": alpha, "n_rejected": 0, "tests": []}


# ---------------------------------------------------------------------------
# APA-7 格式化
# ---------------------------------------------------------------------------

_METHOD_LABELS = {
    "bonferroni": "Bonferroni",
    "holm": "Holm",
    "benjamini_hochberg": "Benjamini-Hochberg（BH）",
}


def format_apa_corrections(result: dict[str, Any]) -> str:
    """生成 APA-7 格式多重检验校正报告段落 + Markdown 表格。"""
    method = result.get("method", "unknown")
    m = result["m"]
    alpha = result["alpha"]
    n_rej = result["n_rejected"]
    label = _METHOD_LABELS.get(method, method)

    # 段落
    if method == "bonferroni":
        method_desc = f"采用 Bonferroni 校正（阈值 α′ = {alpha}/{m} = {alpha/m:.5f}）"
    elif method == "holm":
        method_desc = "采用 Holm (1979) 逐步降低法控制家族错误率（FWER）"
    elif method == "benjamini_hochberg":
        method_desc = "采用 Benjamini & Hochberg (1995) FDR 校正"
    else:
        method_desc = f"采用 {label} 多重检验校正"

    para = (
        f"共进行 {m} 项检验，{method_desc}，α = {alpha}。"
        f"校正后 {n_rej} 项检验达显著水平。"
    )
    if method in ("holm", "bonferroni"):
        para += "（控制家族错误率 FWER；Holm, 1979; Bonferroni, 1936）"
    elif method == "benjamini_hochberg":
        para += "（控制虚假发现率 FDR；Benjamini & Hochberg, 1995）"

    # Markdown 表格
    lines = [
        para, "",
        "| 检验 | 原始 *p* | 校正 *p* | 显著 |",
        "|------|---------|---------|------|",
    ]
    for t in result["tests"]:
        sig = "✓" if t["reject_h0"] else ""
        p_orig = f"{t['p_orig']:.4f}" if t["p_orig"] >= 0.0001 else "< .0001"
        p_adj = f"{t['p_adj']:.4f}" if t["p_adj"] >= 0.0001 else "< .0001"
        lines.append(f"| {t['label']} | {p_orig} | {p_adj} | {sig} |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MD + JSON sidecar
# ---------------------------------------------------------------------------

def write_corrections_report(
    result: dict[str, Any],
    out_dir: str | pathlib.Path = "notes",
) -> tuple[pathlib.Path, pathlib.Path]:
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    method = result.get("method", "correction")
    lines = [
        "# 多重检验校正报告",
        "",
        format_apa_corrections(result),
    ]
    md_path = out / f"corrections_{method}.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    json_path = out / f"corrections_{method}.json"
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return md_path, json_path


# ---------------------------------------------------------------------------
# CSV 主入口
# ---------------------------------------------------------------------------

def analyze_corrections(
    csv_path: str,
    p_col: str = "p",
    label_col: str | None = None,
    method: str = "benjamini_hochberg",
    alpha: float = 0.05,
    out_dir: str | pathlib.Path = "notes",
    write_files: bool = True,
) -> dict[str, Any]:
    """从 CSV 读取 p 值列，执行多重检验校正。

    csv_path: CSV 路径
    p_col: p 值列名（默认 "p"）
    label_col: 检验标签列名（可选）
    method: 'bonferroni' | 'holm' | 'benjamini_hochberg'
    """
    rows: list[dict[str, str]] = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows.append(dict(row))

    pvals = []
    labels = []
    for i, row in enumerate(rows):
        raw = row.get(p_col, "").strip()
        try:
            p = float(raw)
            if 0.0 <= p <= 1.0:
                pvals.append(p)
                lbl = row.get(label_col, "").strip() if label_col else f"检验{i + 1}"
                labels.append(lbl or f"检验{i + 1}")
        except ValueError:
            pass

    if not pvals:
        raise ValueError(f"CSV 列 '{p_col}' 中未找到有效 p 值（0-1 范围内的数值）")

    fn_map = {
        "bonferroni": bonferroni,
        "holm": holm,
        "benjamini_hochberg": benjamini_hochberg,
        "bh": benjamini_hochberg,
        "fdr": benjamini_hochberg,
    }
    if method not in fn_map:
        raise ValueError(f"未知校正方法 '{method}'，可选：bonferroni / holm / benjamini_hochberg")

    result = fn_map[method](pvals, alpha=alpha, labels=labels)
    result["input_file"] = csv_path

    if write_files:
        md_path, json_path = write_corrections_report(result, out_dir=out_dir)
        result["report_md"] = str(md_path)
        result["report_json"] = str(json_path)

    return result


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def corrections_cli(args: list[str]) -> int:
    """psyclaw correct-p <p1,p2,...|--csv file> [--method bh|holm|bonferroni] [--alpha .05]"""
    import argparse

    parser = argparse.ArgumentParser(
        prog="psyclaw correct-p",
        description="多重检验校正：Bonferroni / Holm / BH FDR",
    )
    # 两种输入方式：直接列出 p 值，或从 CSV 读取
    parser.add_argument("pvalues", nargs="?", default=None,
                        help="逗号分隔的 p 值（如 0.01,0.03,0.2）。与 --csv 二选一")
    parser.add_argument("--csv", default=None, help="从 CSV 文件读取 p 值")
    parser.add_argument("--p-col", default="p", dest="p_col",
                        help="CSV 中 p 值所在列名（默认 'p'）")
    parser.add_argument("--label-col", default=None, dest="label_col",
                        help="CSV 中标签列名（可选）")
    parser.add_argument("--method",
                        choices=["bonferroni", "holm", "benjamini_hochberg", "bh", "fdr"],
                        default="benjamini_hochberg",
                        help="校正方法（默认 benjamini_hochberg）")
    parser.add_argument("--alpha", type=float, default=0.05, help="显著性水平（默认 .05）")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    parser.add_argument("--out", default="notes", help="报告输出目录（默认 notes/）")
    opts = parser.parse_args(args)

    fn_map = {
        "bonferroni": bonferroni,
        "holm": holm,
        "benjamini_hochberg": benjamini_hochberg,
        "bh": benjamini_hochberg,
        "fdr": benjamini_hochberg,
    }

    if opts.csv:
        try:
            result = analyze_corrections(
                csv_path=opts.csv,
                p_col=opts.p_col,
                label_col=opts.label_col,
                method=opts.method,
                alpha=opts.alpha,
                out_dir=opts.out,
            )
        except (ValueError, FileNotFoundError) as exc:
            print(f"错误：{exc}")
            return 1
    elif opts.pvalues:
        try:
            pvals = [float(s.strip()) for s in opts.pvalues.split(",")]
        except ValueError:
            print("错误：p 值格式不正确，请用逗号分隔的数值（如 0.01,0.03,0.2）")
            return 1
        result = fn_map[opts.method](pvals, alpha=opts.alpha)
        if not opts.json and not opts.csv:
            # 非 CSV 模式不写文件（无输出目录意义）
            pass
    else:
        parser.print_help()
        return 1

    if opts.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print()
    print(format_apa_corrections(result))
    if "report_md" in result:
        print(f"\n报告已写入 {result['report_md']}")
    return 0
