"""描述统计报告 — APA-7 三线表、相关矩阵、Fisher-z CI。

每篇心理学论文都需要：各变量 N/M/SD/Median/Sk/Kurt/CI + Pearson r 矩阵（*p<.05 标注）。

CLI: psyclaw describe <data.csv> [--cols c1,c2,...] [--corr] [--alpha .05]
     [--json] [--out dir]
"""

from __future__ import annotations

import csv
import json
import math
import pathlib
from typing import Any

from scipy import special, stats


# ---------------------------------------------------------------------------
# 数值工具
# ---------------------------------------------------------------------------

def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def _var(xs: list[float], ddof: int = 1) -> float:
    m = _mean(xs)
    return sum((v - m) ** 2 for v in xs) / (len(xs) - ddof)


def _sd(xs: list[float]) -> float:
    return math.sqrt(_var(xs))


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


def _skewness(xs: list[float]) -> float:
    """Fisher-Pearson 样本偏度 G1（bias-corrected）—— scipy.stats.skew。"""
    if len(xs) < 3:
        return float("nan")
    return float(stats.skew(xs, bias=False))


def _kurtosis(xs: list[float]) -> float:
    """样本超峰度 G2（Fisher，bias-corrected，与 SPSS/Excel KURT() 一致）—— scipy.stats.kurtosis。"""
    if len(xs) < 4:
        return float("nan")
    return float(stats.kurtosis(xs, fisher=True, bias=False))


def _t_ppf(p: float, df: float) -> float:
    """双尾 p = p 对应的 t（即 t.ppf(1 - p/2)）。"""
    if df <= 0:
        return float("nan")
    return float(stats.t.ppf(1 - p / 2.0, df))


def _betai(a: float, b: float, x: float) -> float:
    """正则化不完全 Beta 函数 I_x(a,b) —— scipy.special.betainc。"""
    if x < 0 or x > 1:
        return float("nan")
    return float(special.betainc(a, b, x))


def _t_sf2(t: float, df: float) -> float:
    """学生 t 双尾 p 值（经 _betai → scipy）。"""
    if df <= 0:
        return float("nan")
    x = df / (df + t * t)
    return _betai(df / 2.0, 0.5, x)


# ---------------------------------------------------------------------------
# 单变量描述统计
# ---------------------------------------------------------------------------

def compute_descriptives(
    rows: list[dict[str, str]],
    cols: list[str],
    alpha: float = 0.05,
) -> dict[str, dict[str, Any]]:
    """计算每列的描述统计量。

    返回 {col: {n, missing, missing_pct, mean, sd, se, ci_lower, ci_upper,
                median, min, max, skewness, kurtosis}}
    """
    n_rows = len(rows)
    result: dict[str, dict[str, Any]] = {}
    for col in cols:
        vals: list[float] = []
        missing = 0
        for row in rows:
            raw = row.get(col, "").strip()
            if not raw:
                missing += 1
                continue
            try:
                vals.append(float(raw))
            except ValueError:
                missing += 1
        n = len(vals)
        if n == 0:
            result[col] = {
                "n": 0, "missing": missing,
                "missing_pct": 100.0 if n_rows else 0.0,
                "mean": None, "sd": None, "se": None,
                "ci_lower": None, "ci_upper": None,
                "median": None, "min": None, "max": None,
                "skewness": None, "kurtosis": None,
            }
            continue
        m = _mean(vals)
        sd = _sd(vals) if n >= 2 else 0.0
        se = sd / math.sqrt(n) if n >= 1 else 0.0
        # t*(alpha/2, df=n-1) CI for mean
        if n >= 2:
            t_crit = _t_ppf(alpha, n - 1)
            ci_lo = m - t_crit * se
            ci_hi = m + t_crit * se
        else:
            ci_lo = ci_hi = m
        result[col] = {
            "n": n,
            "missing": missing,
            "missing_pct": round(missing / n_rows * 100, 1) if n_rows else 0.0,
            "mean": round(m, 4),
            "sd": round(sd, 4),
            "se": round(se, 4),
            "ci_lower": round(ci_lo, 4),
            "ci_upper": round(ci_hi, 4),
            "median": round(_median(vals), 4),
            "min": round(min(vals), 4),
            "max": round(max(vals), 4),
            "skewness": round(_skewness(vals), 4) if n >= 3 else None,
            "kurtosis": round(_kurtosis(vals), 4) if n >= 4 else None,
        }
    return result


# ---------------------------------------------------------------------------
# 相关矩阵（Pearson r + p + Fisher-z 95% CI）
# ---------------------------------------------------------------------------

def compute_correlation_matrix(
    rows: list[dict[str, str]],
    cols: list[str],
    alpha: float = 0.05,
) -> dict[str, Any]:
    """计算 Pearson r 矩阵 + 双尾 p + Fisher-z CI。

    返回 {r, p, ci_lower, ci_upper, n} 各为 {col→{col→value}} 嵌套字典。
    """
    # 提取数值
    data: dict[str, list[float]] = {}
    for col in cols:
        vals = []
        for row in rows:
            raw = row.get(col, "").strip()
            try:
                vals.append(float(raw))
            except (ValueError, AttributeError):
                vals.append(float("nan"))
        data[col] = vals

    r_mat: dict[str, dict[str, Any]] = {c: {} for c in cols}
    p_mat: dict[str, dict[str, Any]] = {c: {} for c in cols}
    ci_lo: dict[str, dict[str, Any]] = {c: {} for c in cols}
    ci_hi: dict[str, dict[str, Any]] = {c: {} for c in cols}
    n_mat: dict[str, dict[str, Any]] = {c: {} for c in cols}

    z_crit = _norm_ppf(1.0 - alpha / 2.0)

    for i, c1 in enumerate(cols):
        for j, c2 in enumerate(cols):
            if i == j:
                r_mat[c1][c2] = 1.0
                p_mat[c1][c2] = 0.0
                ci_lo[c1][c2] = 1.0
                ci_hi[c1][c2] = 1.0
                n_mat[c1][c2] = sum(1 for v in data[c1] if math.isfinite(v))
                continue
            # 仅取两列都非 nan 的行
            pairs = [(data[c1][k], data[c2][k])
                     for k in range(len(rows))
                     if math.isfinite(data[c1][k]) and math.isfinite(data[c2][k])]
            n_pair = len(pairs)
            if n_pair < 4:
                r_mat[c1][c2] = None
                p_mat[c1][c2] = None
                ci_lo[c1][c2] = None
                ci_hi[c1][c2] = None
                n_mat[c1][c2] = n_pair
                continue
            xs = [p[0] for p in pairs]
            ys = [p[1] for p in pairs]
            mx, my = _mean(xs), _mean(ys)
            sx = math.sqrt(sum((v - mx) ** 2 for v in xs))
            sy = math.sqrt(sum((v - my) ** 2 for v in ys))
            if sx == 0 or sy == 0:
                r_mat[c1][c2] = None
                p_mat[c1][c2] = None
                ci_lo[c1][c2] = None
                ci_hi[c1][c2] = None
                n_mat[c1][c2] = n_pair
                continue
            cov = sum((xs[k] - mx) * (ys[k] - my) for k in range(n_pair))
            r = cov / (sx * sy)
            r = max(-0.9999999, min(0.9999999, r))
            # p value
            t_stat = r * math.sqrt(n_pair - 2) / math.sqrt(1 - r * r)
            p = _t_sf2(abs(t_stat), n_pair - 2)
            # Fisher-z CI
            z = math.atanh(r)
            se_z = 1.0 / math.sqrt(n_pair - 3)
            ci_l = math.tanh(z - z_crit * se_z)
            ci_h = math.tanh(z + z_crit * se_z)
            r_mat[c1][c2] = round(r, 4)
            p_mat[c1][c2] = round(p, 4)
            ci_lo[c1][c2] = round(ci_l, 4)
            ci_hi[c1][c2] = round(ci_h, 4)
            n_mat[c1][c2] = n_pair

    return {"r": r_mat, "p": p_mat, "ci_lower": ci_lo,
            "ci_upper": ci_hi, "n": n_mat, "cols": cols, "alpha": alpha}


def _norm_ppf(p: float) -> float:
    """标准正态分位数 —— scipy.special.ndtri。"""
    if not 0 < p < 1:
        return float("nan")
    return float(special.ndtri(p))


# ---------------------------------------------------------------------------
# APA-7 格式化
# ---------------------------------------------------------------------------

def format_apa_descriptives_table(
    stats: dict[str, dict[str, Any]],
    title: str = "描述统计",
) -> str:
    """生成 APA-7 Markdown 三线表（变量 × M/SD/N/Sk/Kurt）。"""
    cols = list(stats.keys())
    if not cols:
        return "（无变量可报告）"

    header = "| 变量 | *N* | *M* | *SD* | Mdn | Sk | Kurt | 95% CI |"
    sep = "|------|-----|-----|------|-----|----|----|--------|"
    rows = []
    for col in cols:
        s = stats[col]
        if s["n"] == 0:
            rows.append(f"| {col} | 0 | — | — | — | — | — | — |")
            continue
        m_str = f"{s['mean']:.2f}" if s["mean"] is not None else "—"
        sd_str = f"{s['sd']:.2f}" if s["sd"] is not None else "—"
        mdn_str = f"{s['median']:.2f}" if s["median"] is not None else "—"
        sk_str = f"{s['skewness']:.2f}" if s["skewness"] is not None else "—"
        kurt_str = f"{s['kurtosis']:.2f}" if s["kurtosis"] is not None else "—"
        ci_str = (f"[{s['ci_lower']:.2f}, {s['ci_upper']:.2f}]"
                  if s["ci_lower"] is not None else "—")
        rows.append(f"| {col} | {s['n']} | {m_str} | {sd_str} | {mdn_str} | {sk_str} | {kurt_str} | {ci_str} |")

    lines = [f"*{title}*", "", header, sep] + rows + [
        "",
        f"*注：95% CI 为均值置信区间；Sk = 偏度；Kurt = 超峰度。*"
    ]
    return "\n".join(lines)


def format_apa_correlation_table(
    corr: dict[str, Any],
    alpha: float = 0.05,
) -> str:
    """生成 APA-7 Markdown 相关矩阵下三角表，标注 * p < .05, ** p < .01, *** p < .001。"""
    cols = corr.get("cols", [])
    if not cols:
        return "（无相关矩阵）"

    r_mat = corr["r"]
    p_mat = corr["p"]

    def star(p_val: float | None) -> str:
        if p_val is None:
            return ""
        if p_val < 0.001:
            return "***"
        if p_val < 0.01:
            return "**"
        if p_val < 0.05:
            return "*"
        return ""

    n_cols = len(cols)
    # header: 变量 + 1..n-1 (下三角不含最后列)
    header_cells = ["变量"] + [str(i + 1) for i in range(n_cols)]
    header = "| " + " | ".join(header_cells) + " |"
    sep = "|" + "|".join(["---"] * (n_cols + 1)) + "|"

    rows = []
    for i, c1 in enumerate(cols):
        cells = [f"{i + 1}. {c1}"]
        for j, c2 in enumerate(cols):
            if j < i:
                r_val = r_mat[c1][c2]
                p_val = p_mat[c1][c2]
                if r_val is None:
                    cells.append("—")
                else:
                    cells.append(f"{r_val:.2f}{star(p_val)}")
            elif j == i:
                cells.append("—")
            else:
                cells.append("")
        rows.append("| " + " | ".join(cells) + " |")

    lines = [
        "*变量间 Pearson 相关矩阵*", "",
        header, sep,
    ] + rows + [
        "",
        "*注：\\* p < .05, \\*\\* p < .01, \\*\\*\\* p < .001。CI 采用 Fisher z 变换。*"
    ]
    return "\n".join(lines)


def format_apa_paragraph(
    stats: dict[str, dict[str, Any]],
) -> str:
    """生成描述统计 APA 文字段落（简要总结主要变量的 M 和 SD）。"""
    parts = []
    for col, s in stats.items():
        if s["n"] == 0:
            continue
        m = s["mean"]
        sd = s["sd"]
        n = s["n"]
        parts.append(f"{col}（*M* = {m:.2f}, *SD* = {sd:.2f}, *N* = {n}）")
    if not parts:
        return "无有效数据。"
    return "描述统计结果如下：" + "；".join(parts) + "。"


# ---------------------------------------------------------------------------
# MD + JSON sidecar
# ---------------------------------------------------------------------------

def write_descriptives_report(
    stats: dict[str, dict[str, Any]],
    corr: dict[str, Any] | None = None,
    out_dir: str | pathlib.Path = "notes",
    alpha: float = 0.05,
) -> tuple[pathlib.Path, pathlib.Path]:
    """写 descriptives_report.md + descriptives_report.json。"""
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    lines = [
        "# 描述统计报告",
        "",
        format_apa_descriptives_table(stats),
        "",
        "## APA-7 文字摘要",
        "",
        format_apa_paragraph(stats),
    ]
    if corr:
        lines += ["", "## 相关矩阵", "", format_apa_correlation_table(corr, alpha=alpha)]

    md_path = out / "descriptives_report.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    payload: dict[str, Any] = {"descriptives": stats}
    if corr:
        payload["correlations"] = corr
    json_path = out / "descriptives_report.json"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return md_path, json_path


# ---------------------------------------------------------------------------
# CSV 主入口
# ---------------------------------------------------------------------------

def analyze_descriptives(
    csv_path: str,
    cols: list[str] | None = None,
    include_corr: bool = False,
    alpha: float = 0.05,
    out_dir: str | pathlib.Path = "notes",
    write_files: bool = True,
) -> dict[str, Any]:
    """从 CSV 计算描述统计（+ 可选相关矩阵）。"""
    rows: list[dict[str, str]] = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))

    if not rows:
        raise ValueError(f"CSV 文件无数据行：{csv_path}")

    all_cols = list(rows[0].keys()) if rows else []
    if cols is None or len(cols) == 0:
        # 自动选数值列
        numeric_cols = []
        for c in all_cols:
            for row in rows[:20]:
                val = row.get(c, "").strip()
                if val:
                    try:
                        float(val)
                        numeric_cols.append(c)
                        break
                    except ValueError:
                        break
        cols = numeric_cols if numeric_cols else all_cols

    stats = compute_descriptives(rows, cols, alpha=alpha)
    corr = compute_correlation_matrix(rows, cols, alpha=alpha) if include_corr else None

    result: dict[str, Any] = {"descriptives": stats, "cols": cols, "n_rows": len(rows)}
    if corr:
        result["correlations"] = corr

    if write_files:
        md_path, json_path = write_descriptives_report(stats, corr, out_dir=out_dir, alpha=alpha)
        result["report_md"] = str(md_path)
        result["report_json"] = str(json_path)

    return result


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def descriptives_cli(args: list[str]) -> int:
    """psyclaw describe <data.csv> [--cols c1,c2] [--corr] [options]"""
    import argparse

    parser = argparse.ArgumentParser(
        prog="psyclaw describe",
        description="APA-7 描述统计表 + 可选 Pearson 相关矩阵",
    )
    parser.add_argument("csv_file", help="输入数据 CSV 路径")
    parser.add_argument("--cols", default=None,
                        help="逗号分隔的列名（默认自动选数值列）")
    parser.add_argument("--corr", action="store_true", help="附加 Pearson 相关矩阵")
    parser.add_argument("--alpha", type=float, default=0.05,
                        help="显著性水平（默认 .05，影响 CI 和相关 * 标注）")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    parser.add_argument("--out", default="notes", help="报告输出目录（默认 notes/）")
    opts = parser.parse_args(args)

    col_list = [c.strip() for c in opts.cols.split(",")] if opts.cols else None

    try:
        result = analyze_descriptives(
            csv_path=opts.csv_file,
            cols=col_list,
            include_corr=opts.corr,
            alpha=opts.alpha,
            out_dir=opts.out,
        )
    except (ValueError, FileNotFoundError) as exc:
        print(f"错误：{exc}")
        return 1

    if opts.json:
        print(json.dumps(
            {"descriptives": result["descriptives"],
             "correlations": result.get("correlations")},
            ensure_ascii=False, indent=2, default=str,
        ))
        return 0

    # 人类可读输出
    print()
    print(format_apa_descriptives_table(result["descriptives"]))
    if opts.corr and "correlations" in result:
        print()
        print(format_apa_correlation_table(result["correlations"], alpha=opts.alpha))
    print()
    print(format_apa_paragraph(result["descriptives"]))
    if "report_md" in result:
        print(f"\n报告已写入 {result['report_md']}")
    return 0
