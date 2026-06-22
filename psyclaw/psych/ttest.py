"""t 检验套件 — 单样本 / 独立样本（Welch）/ 配对，APA-7 报告。

数值引擎复用 scipy.stats（t / 自由度 / p / 置信区间）+ numpy（描述统计）；
效应量用标准 Cohen's d / dz 公式。不再手写分布函数。对外提供与其他分析
命令一致的 CLI 接口、APA-7 段落/表格格式化和 MD+JSON sidecar。

提供：
  - ttest_one_sample(x, mu0)          → t/df/p/d/CI（单样本）
  - ttest_independent(x, y, welch)    → t/df/p/d/CI（独立样本）
  - ttest_paired(x, y)                → t/df/p/dz/CI（配对样本）
  - format_apa_ttest(result)          → APA-7 段落 + 描述统计
  - write_ttest_report(result)        → MD + JSON sidecar
  - analyze_ttest(csv_path, ...)      → CSV 主入口
  - CLI: psyclaw ttest <data.csv> --dv <col>
         [--one-sample --mu0 <val> | --group <col> | --paired --y <col>]
         [--student] [--alpha .05] [--json] [--out dir]
"""

from __future__ import annotations

import csv
import json
import math
import pathlib
from typing import Any

import numpy as np
from scipy import stats


# ---------------------------------------------------------------------------
# 描述统计（numpy）
# ---------------------------------------------------------------------------

def _desc(vals) -> tuple[float, float, int]:
    """返回 (mean, sd_ddof1, n)。"""
    arr = np.asarray(vals, dtype=float)
    n = int(arr.size)
    m = float(arr.mean()) if n else float("nan")
    s = float(arr.std(ddof=1)) if n > 1 else 0.0
    return m, s, n


# ---------------------------------------------------------------------------
# 单样本 t 检验
# ---------------------------------------------------------------------------

def ttest_one_sample(
    x: list[float],
    mu0: float = 0.0,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """单样本 t 检验（x 均值 vs mu0）。

    效应量：Cohen's d = (M - mu0) / SD
    """
    n = len(x)
    if n < 2:
        raise ValueError(f"单样本 t 检验需要至少 2 个观测（当前 {n}）")
    arr = np.asarray(x, dtype=float)
    m, s, _ = _desc(arr)
    se = s / math.sqrt(n)
    if se == 0:
        raise ValueError("样本标准差为 0，无法计算 t 统计量")

    res = stats.ttest_1samp(arr, mu0)
    t = float(res.statistic)
    df = int(n - 1)
    p = float(res.pvalue)

    d = (m - mu0) / s
    zc = float(stats.norm.ppf(1 - alpha / 2))
    se_d = math.sqrt((1 / n) + d ** 2 / (2 * n))
    d_lo, d_hi = d - zc * se_d, d + zc * se_d
    ci = res.confidence_interval(confidence_level=1 - alpha)
    m_lo, m_hi = float(ci.low), float(ci.high)

    return {
        "test": "one_sample",
        "t": round(t, 4),
        "df": df,
        "p": round(p, 6),
        "M": round(m, 4),
        "SD": round(s, 4),
        "SE": round(se, 4),
        "n": n,
        "mu0": mu0,
        "mean_ci": (round(m_lo, 4), round(m_hi, 4)),
        "d": round(d, 4),
        "d_ci": (round(d_lo, 4), round(d_hi, 4)),
        "alpha": alpha,
        "significant": p < alpha,
    }


# ---------------------------------------------------------------------------
# 独立样本 t 检验（Welch 或 Student）
# ---------------------------------------------------------------------------

def ttest_independent(
    x: list[float],
    y: list[float],
    welch: bool = True,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """独立样本 t 检验。

    welch=True（默认）：Welch 近似自由度（不等方差）
    welch=False：Student 等方差假设（合并 SD）
    效应量：Cohen's d（合并 SD）
    """
    n1, n2 = len(x), len(y)
    if n1 < 2 or n2 < 2:
        raise ValueError(f"每组至少需要 2 个观测（n1={n1}, n2={n2}）")
    ax, ay = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    m1, s1, _ = _desc(ax)
    m2, s2, _ = _desc(ay)

    # 标准误（同时用于零方差守卫）
    if welch:
        se = math.sqrt(s1 ** 2 / n1 + s2 ** 2 / n2)
        test_type = "welch"
    else:
        sp_pooled = math.sqrt(((n1 - 1) * s1 ** 2 + (n2 - 1) * s2 ** 2) / (n1 + n2 - 2))
        se = sp_pooled * math.sqrt(1 / n1 + 1 / n2)
        test_type = "student"
    if se == 0:
        raise ValueError("标准误为 0，无法计算 t 统计量")

    res = stats.ttest_ind(ax, ay, equal_var=not welch)
    t = float(res.statistic)
    df = float(res.df)
    p = float(res.pvalue)

    sp = math.sqrt(((n1 - 1) * s1 ** 2 + (n2 - 1) * s2 ** 2) / (n1 + n2 - 2)) if n1 + n2 > 2 else 0.0
    d = (m1 - m2) / sp if sp > 0 else float("nan")
    zc = float(stats.norm.ppf(1 - alpha / 2))
    se_d = math.sqrt((n1 + n2) / (n1 * n2) + d ** 2 / (2 * (n1 + n2))) if math.isfinite(d) else float("nan")
    d_lo = d - zc * se_d if math.isfinite(se_d) else float("nan")
    d_hi = d + zc * se_d if math.isfinite(se_d) else float("nan")

    diff = m1 - m2
    ci = res.confidence_interval(confidence_level=1 - alpha)
    diff_lo, diff_hi = float(ci.low), float(ci.high)

    return {
        "test": test_type,
        "t": round(t, 4),
        "df": round(df, 2),
        "p": round(p, 6),
        "M1": round(m1, 4), "SD1": round(s1, 4), "n1": n1,
        "M2": round(m2, 4), "SD2": round(s2, 4), "n2": n2,
        "diff": round(diff, 4),
        "diff_ci": (round(diff_lo, 4), round(diff_hi, 4)),
        "d": round(d, 4) if math.isfinite(d) else None,
        "d_ci": (round(d_lo, 4) if math.isfinite(d_lo) else None,
                 round(d_hi, 4) if math.isfinite(d_hi) else None),
        "alpha": alpha,
        "significant": p < alpha,
    }


# ---------------------------------------------------------------------------
# 配对 t 检验
# ---------------------------------------------------------------------------

def ttest_paired(
    x: list[float],
    y: list[float],
    alpha: float = 0.05,
) -> dict[str, Any]:
    """配对样本 t 检验（前测/后测）。

    效应量：Cohen's dz = M_diff / SD_diff
    """
    if len(x) != len(y):
        raise ValueError(f"配对 t 检验需要等长数据（len(x)={len(x)}, len(y)={len(y)}）")
    n = len(x)
    if n < 2:
        raise ValueError(f"配对 t 检验需要至少 2 对观测（当前 {n}）")
    ax, ay = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    diffs = ax - ay
    m_d = float(diffs.mean())
    s_d = float(diffs.std(ddof=1)) if n > 1 else 0.0
    se = s_d / math.sqrt(n)
    if se == 0:
        raise ValueError("差值标准差为 0，无法计算 t 统计量")

    res = stats.ttest_rel(ax, ay)
    t = float(res.statistic)
    df = int(n - 1)
    p = float(res.pvalue)

    dz = m_d / s_d
    zc = float(stats.norm.ppf(1 - alpha / 2))
    se_dz = math.sqrt(1 / n + dz ** 2 / (2 * n))
    dz_lo, dz_hi = dz - zc * se_dz, dz + zc * se_dz
    ci = res.confidence_interval(confidence_level=1 - alpha)
    m_d_lo, m_d_hi = float(ci.low), float(ci.high)

    m1, s1, _ = _desc(ax)
    m2, s2, _ = _desc(ay)

    return {
        "test": "paired",
        "t": round(t, 4),
        "df": df,
        "p": round(p, 6),
        "M1": round(m1, 4), "SD1": round(s1, 4),
        "M2": round(m2, 4), "SD2": round(s2, 4),
        "n": n,
        "M_diff": round(m_d, 4),
        "SD_diff": round(s_d, 4),
        "diff_ci": (round(m_d_lo, 4), round(m_d_hi, 4)),
        "dz": round(dz, 4),
        "dz_ci": (round(dz_lo, 4), round(dz_hi, 4)),
        "alpha": alpha,
        "significant": p < alpha,
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


def _interpret_d(d: float) -> str:
    ad = abs(d)
    if ad >= 0.8:
        return "大效应"
    if ad >= 0.5:
        return "中效应"
    if ad >= 0.2:
        return "小效应"
    return "微效应"


def format_apa_ttest(result: dict[str, Any]) -> str:
    """生成 APA-7 t 检验段落。"""
    test = result["test"]
    t = result["t"]
    df = result["df"]
    p = result.get("p")
    alpha = result.get("alpha", 0.05)
    sig_str = "达到统计显著性" if result.get("significant") else "未达到统计显著性"
    p_str = _fmt_p(p)
    lines = []

    if test == "one_sample":
        M, SD, n, mu0 = result["M"], result["SD"], result["n"], result["mu0"]
        d, d_ci = result["d"], result["d_ci"]
        ci_pct = int((1 - alpha) * 100)
        lines.append(
            f"单样本 *t* 检验结果显示，*t*({df}) = {t:.2f}，*p* {p_str}，"
            f"*M* = {M:.2f}，*SD* = {SD:.2f}（μ₀ = {mu0}）；"
            f"*d* = {d:.3f}（{_interpret_d(d)}），"
            f"{ci_pct}% CI [{d_ci[0]:.3f}, {d_ci[1]:.3f}]，"
            f"N = {n}，{sig_str}。"
        )

    elif test in ("welch", "student"):
        M1, SD1, n1 = result["M1"], result["SD1"], result["n1"]
        M2, SD2, n2 = result["M2"], result["SD2"], result["n2"]
        d, d_ci = result.get("d"), result.get("d_ci", (None, None))
        diff = result["diff"]
        diff_ci = result["diff_ci"]
        ci_pct = int((1 - alpha) * 100)
        t_type = "Welch 独立样本" if test == "welch" else "Student 独立样本"
        d_str = f"{d:.3f}" if d is not None else "—"
        d_ci_str = (
            f"[{d_ci[0]:.3f}, {d_ci[1]:.3f}]"
            if d_ci[0] is not None else "—"
        )
        lines.append(
            f"{t_type} *t* 检验结果显示，*t*({df:.1f}) = {t:.2f}，*p* {p_str}；"
            f"组 1：*M* = {M1:.2f}，*SD* = {SD1:.2f}，*n* = {n1}；"
            f"组 2：*M* = {M2:.2f}，*SD* = {SD2:.2f}，*n* = {n2}；"
            f"均值差 = {diff:.2f}，{ci_pct}% CI [{diff_ci[0]:.2f}, {diff_ci[1]:.2f}]；"
            f"*d* = {d_str}（{_interpret_d(d) if d is not None else '—'}），"
            f"{ci_pct}% CI {d_ci_str}，{sig_str}。"
        )
        # 描述统计表
        lines += [
            "",
            "| 组别 | *n* | *M* | *SD* |",
            "|------|-----|-----|------|",
            f"| 组 1 | {n1} | {M1:.2f} | {SD1:.2f} |",
            f"| 组 2 | {n2} | {M2:.2f} | {SD2:.2f} |",
        ]

    elif test == "paired":
        M1, SD1 = result["M1"], result["SD1"]
        M2, SD2 = result["M2"], result["SD2"]
        n, M_d, SD_d = result["n"], result["M_diff"], result["SD_diff"]
        dz, dz_ci = result["dz"], result["dz_ci"]
        diff_ci = result["diff_ci"]
        ci_pct = int((1 - alpha) * 100)
        lines.append(
            f"配对样本 *t* 检验结果显示，*t*({df}) = {t:.2f}，*p* {p_str}；"
            f"前测：*M* = {M1:.2f}，*SD* = {SD1:.2f}；"
            f"后测：*M* = {M2:.2f}，*SD* = {SD2:.2f}；"
            f"差值 *M* = {M_d:.2f}，*SD* = {SD_d:.2f}，"
            f"{ci_pct}% CI [{diff_ci[0]:.2f}, {diff_ci[1]:.2f}]；"
            f"*d*_z = {dz:.3f}（{_interpret_d(dz)}），"
            f"{ci_pct}% CI [{dz_ci[0]:.3f}, {dz_ci[1]:.3f}]，"
            f"*N* = {n}，{sig_str}。"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MD + JSON sidecar
# ---------------------------------------------------------------------------

def write_ttest_report(
    result: dict[str, Any],
    out_dir: str | pathlib.Path = "notes",
) -> tuple[pathlib.Path, pathlib.Path]:
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    test_labels = {
        "one_sample": "单样本", "welch": "Welch独立", "student": "Student独立",
        "paired": "配对",
    }
    label = test_labels.get(result.get("test", ""), "t检验")
    lines = [f"# t 检验报告：{label}", "", format_apa_ttest(result)]
    md_path = out / "ttest_report.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    json_path = out / "ttest_report.json"
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return md_path, json_path


# ---------------------------------------------------------------------------
# CSV 主入口
# ---------------------------------------------------------------------------

def _read_col(rows: list[dict], col: str) -> list[float]:
    vals = []
    for row in rows:
        raw = row.get(col, "").strip()
        try:
            v = float(raw)
            if math.isfinite(v):
                vals.append(v)
        except (ValueError, TypeError):
            continue
    return vals


def analyze_ttest(
    csv_path: str,
    dv: str,
    test: str = "independent",
    group_col: str | None = None,
    y_col: str | None = None,
    mu0: float = 0.0,
    welch: bool = True,
    alpha: float = 0.05,
    out_dir: str | pathlib.Path = "notes",
    write_files: bool = True,
) -> dict[str, Any]:
    """从 CSV 执行 t 检验。

    test: 'one_sample' | 'independent' | 'paired'
    """
    rows: list[dict[str, str]] = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows.append(dict(row))

    test = test.lower()

    if test == "one_sample":
        x = _read_col(rows, dv)
        if not x:
            raise ValueError(f"列 '{dv}' 无有效数值")
        result = ttest_one_sample(x, mu0=mu0, alpha=alpha)

    elif test == "independent":
        if group_col is None:
            raise ValueError("独立样本 t 检验需要 --group 参数")
        groups: dict[str, list[float]] = {}
        for row in rows:
            g = row.get(group_col, "").strip()
            raw = row.get(dv, "").strip()
            if not g or not raw:
                continue
            try:
                v = float(raw)
                if math.isfinite(v):
                    groups.setdefault(g, []).append(v)
            except ValueError:
                continue
        gnames = list(groups.keys())
        if len(gnames) != 2:
            raise ValueError(
                f"独立样本 t 检验需要恰好 2 组（发现 {len(gnames)}：{gnames}）"
            )
        result = ttest_independent(groups[gnames[0]], groups[gnames[1]],
                                   welch=welch, alpha=alpha)
        result["group1"] = gnames[0]
        result["group2"] = gnames[1]

    elif test == "paired":
        if y_col is None:
            raise ValueError("配对 t 检验需要 --y 参数（第二变量列名）")
        x = _read_col(rows, dv)
        y = _read_col(rows, y_col)
        n = min(len(x), len(y))
        result = ttest_paired(x[:n], y[:n], alpha=alpha)

    else:
        raise ValueError(
            f"未知检验类型 '{test}'，可选：one_sample | independent | paired"
        )

    result["dv"] = dv
    result["input_file"] = csv_path

    if write_files:
        md_path, json_path = write_ttest_report(result, out_dir=out_dir)
        result["report_md"] = str(md_path)
        result["report_json"] = str(json_path)

    return result


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def ttest_cli(args: list[str]) -> int:
    """psyclaw ttest <data.csv> --dv <col> [--test independent|paired|one-sample] [options]"""
    import argparse

    parser = argparse.ArgumentParser(
        prog="psyclaw ttest",
        description="t 检验：单样本 / 独立样本（Welch/Student）/ 配对样本",
    )
    parser.add_argument("csv_file", help="输入数据 CSV 路径")
    parser.add_argument("--dv", required=True, help="因变量列名（或第一变量）")
    parser.add_argument(
        "--test",
        choices=["independent", "paired", "one-sample", "one_sample"],
        default="independent",
        help="检验类型（默认 independent）",
    )
    parser.add_argument("--group", dest="group_col", default=None,
                        help="分组列名（independent 必需）")
    parser.add_argument("--y", dest="y_col", default=None,
                        help="第二变量列名（paired 必需）")
    parser.add_argument("--mu0", type=float, default=0.0,
                        help="单样本原假设均值（默认 0）")
    parser.add_argument("--student", action="store_true",
                        help="使用 Student t（等方差），默认 Welch t")
    parser.add_argument("--alpha", type=float, default=0.05,
                        help="显著性水平（默认 .05）")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    parser.add_argument("--out", default="notes", help="报告输出目录（默认 notes/）")
    opts = parser.parse_args(args)

    test_map = {"one-sample": "one_sample"}
    test_type = test_map.get(opts.test, opts.test)

    try:
        result = analyze_ttest(
            csv_path=opts.csv_file,
            dv=opts.dv,
            test=test_type,
            group_col=opts.group_col,
            y_col=opts.y_col,
            mu0=opts.mu0,
            welch=not opts.student,
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
    print(format_apa_ttest(result))
    if "report_md" in result:
        print(f"\n报告已写入 {result['report_md']}")
    return 0
