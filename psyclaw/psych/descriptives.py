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
    """Fisher's g1（偏度），使用 n 矩（样本调整）。"""
    n = len(xs)
    if n < 3:
        return float("nan")
    m = _mean(xs)
    m2 = sum((v - m) ** 2 for v in xs) / n
    m3 = sum((v - m) ** 3 for v in xs) / n
    if m2 == 0:
        return float("nan")
    g1 = m3 / m2 ** 1.5
    # 样本偏度调整（G1）
    return g1 * math.sqrt(n * (n - 1)) / (n - 2)


def _kurtosis(xs: list[float]) -> float:
    """超峰度（excess kurtosis）G2，与 SPSS/Excel KURT() 一致。

    公式：G2 = (n-1)/((n-2)(n-3)) * [(n+1)*g2 + 6]，g2 = m4/m2^2 - 3
    正态分布期望值为 0；比正态更尖峰 > 0，更平坦 < 0。
    """
    n = len(xs)
    if n < 4:
        return float("nan")
    m = _mean(xs)
    m2 = sum((v - m) ** 2 for v in xs) / n
    m4 = sum((v - m) ** 4 for v in xs) / n
    if m2 == 0:
        return float("nan")
    g2 = m4 / m2 ** 2 - 3.0
    return (n - 1) * ((n + 1) * g2 + 6) / ((n - 2) * (n - 3))


def _t_ppf(p: float, df: float) -> float:
    """t 分布上α分位数（简化二分搜索）。"""
    if df <= 0:
        return float("nan")
    lo, hi = 0.0, 1000.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if _t_sf2(mid, df) < p:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2.0


def _betai(a: float, b: float, x: float) -> float:
    """正则化不完全 Beta 函数（Numerical Recipes 连分式 + 对称）。"""
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
    # Lentz continued fraction
    c = 1.0
    d = 1.0 - (a + b) * x / (a + 1)
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, 200):
        m2 = 2 * m
        # even
        num = m * (b - m) * x / ((a + m2 - 1) * (a + m2))
        d = 1.0 + num * d
        c = 1.0 + num / c
        if abs(d) < fpmin:
            d = fpmin
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        # odd
        num = -(a + m) * (a + b + m) * x / ((a + m2) * (a + m2 + 1))
        d = 1.0 + num * d
        c = 1.0 + num / c
        if abs(d) < fpmin:
            d = fpmin
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    return front * h


def _t_sf2(t: float, df: float) -> float:
    """学生 t 双尾 p 值。"""
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
    """标准正态分位数（Acklam 近似）。"""
    if not 0 < p < 1:
        return float("nan")
    a = [-3.969683028665376e+01, 2.209460984245205e+02,
         -2.759285104469687e+02, 1.383577518672690e+02,
         -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02,
         -1.556989798598866e+02, 6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01,
         -2.400758277161838e+00, -2.549732539343734e+00,
         4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01,
         2.445134137142996e+00, 3.754408661907416e+00]
    p_low, p_high = 0.02425, 1 - 0.02425
    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
               (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    else:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
                ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)


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
