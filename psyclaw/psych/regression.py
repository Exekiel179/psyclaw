"""OLS 回归分析 — APA-7 系数表（stdlib only）。

提供：
  - 纯 stdlib OLS（Gauss-Jordan 求逆 + 正规方程）
  - B（非标准化系数）、β（标准化系数）、SE、t、p
  - R²、调整 R²、F 检验
  - APA-7 Markdown 三线系数表 + 文字摘要段落
  - CSV 主入口 + MD/JSON sidecar + CLI

CLI:
  psyclaw regress <data.csv> --dv <col> --iv col1,col2,...
          [--std] [--alpha .05] [--json] [--out dir]
"""

from __future__ import annotations

import csv
import json
import math
import pathlib
from typing import Any


# ---------------------------------------------------------------------------
# 矩阵工具（stdlib only）
# ---------------------------------------------------------------------------

def _mat_transpose(A: list[list[float]]) -> list[list[float]]:
    m, n = len(A), len(A[0])
    return [[A[i][j] for i in range(m)] for j in range(n)]


def _mat_mult(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
    """矩阵乘法 A(m×n) × B(n×p) → C(m×p)。"""
    m, n = len(A), len(A[0])
    p = len(B[0])
    C = [[0.0] * p for _ in range(m)]
    for i in range(m):
        for k in range(n):
            if A[i][k] == 0.0:
                continue
            for j in range(p):
                C[i][j] += A[i][k] * B[k][j]
    return C


def _mat_vec(A: list[list[float]], v: list[float]) -> list[float]:
    """矩阵 × 向量。"""
    return [sum(A[i][j] * v[j] for j in range(len(v))) for i in range(len(A))]


def _mat_invert(M: list[list[float]]) -> list[list[float]] | None:
    """Gauss-Jordan 消去求 n×n 矩阵逆，奇异返回 None。"""
    n = len(M)
    aug = [M[i][:] + [1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for col in range(n):
        # 部分主元选取
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        aug[col], aug[pivot] = aug[pivot], aug[col]
        p = aug[col][col]
        if abs(p) < 1e-14:
            return None
        scale = 1.0 / p
        aug[col] = [v * scale for v in aug[col]]
        for row in range(n):
            if row != col and aug[row][col] != 0.0:
                f = aug[row][col]
                aug[row] = [aug[row][k] - f * aug[col][k] for k in range(2 * n)]
    return [row[n:] for row in aug]


# ---------------------------------------------------------------------------
# t 分布双尾 p 值（复用 descriptives 中的 _betai）
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
        if abs(d) < fpmin:
            d = fpmin
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
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
    if df <= 0:
        return float("nan")
    x = df / (df + t * t)
    return _betai(df / 2.0, 0.5, x)


def _f_sf(f_stat: float, df1: float, df2: float) -> float:
    """F 分布上尾 p 值。"""
    if f_stat <= 0 or df1 <= 0 or df2 <= 0:
        return float("nan")
    x = df2 / (df2 + df1 * f_stat)
    return _betai(df2 / 2.0, df1 / 2.0, x)


def _norm_ppf(p: float) -> float:
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
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    elif p <= p_high:
        q = p - 0.5
        r = q*q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    else:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)


def _t_ppf(p: float, df: float) -> float:
    """t 分布双尾 α 对应的 |t| 临界值（二分搜索）。"""
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


# ---------------------------------------------------------------------------
# OLS 核心
# ---------------------------------------------------------------------------

def compute_ols(
    y: list[float],
    X: list[list[float]],
    iv_names: list[str],
    dv_name: str = "y",
    alpha: float = 0.05,
) -> dict[str, Any]:
    """OLS 回归（含截距），X 为设计矩阵（不含常数列，函数内部添加）。

    返回
    ----
    {
      n, k (预测变量数), df_model, df_resid,
      coefficients: [{name, B, SE, t, p, ci_lower, ci_upper, beta}],
      R2, R2_adj, F, F_p, SSE, SSR, SST, MSE, RMSE,
      dv_name, iv_names
    }
    """
    n = len(y)
    k = len(X[0]) if X else 0  # 预测变量数（不含截距）

    if n < k + 2:
        raise ValueError(f"有效数据行数 ({n}) 不足以拟合 {k} 个预测变量 + 截距")

    # 设计矩阵：截距列 + IV 列
    Xd = [[1.0] + list(X[i]) for i in range(n)]
    Xt = _mat_transpose(Xd)
    XtX = _mat_mult(Xt, Xd)
    XtX_inv = _mat_invert(XtX)
    if XtX_inv is None:
        raise ValueError("设计矩阵奇异（预测变量完全多重共线），无法求逆")

    Xty = _mat_vec(Xt, y)
    betas = _mat_vec(XtX_inv, Xty)  # [intercept, b1, b2, ...]

    # 残差 & 拟合值
    y_hat = [sum(betas[j] * Xd[i][j] for j in range(k + 1)) for i in range(n)]
    residuals = [y[i] - y_hat[i] for i in range(n)]
    SSE = sum(r ** 2 for r in residuals)
    y_mean = sum(y) / n
    SST = sum((yi - y_mean) ** 2 for yi in y)
    SSR = SST - SSE

    df_model = k
    df_resid = n - k - 1
    MSE = SSE / df_resid if df_resid > 0 else float("nan")
    R2 = 1.0 - SSE / SST if SST > 0 else 0.0
    R2_adj = 1.0 - (1.0 - R2) * (n - 1) / df_resid if df_resid > 0 else float("nan")
    MSR = SSR / df_model if df_model > 0 else float("nan")
    F = MSR / MSE if MSE > 0 else float("nan")
    F_p = _f_sf(F, df_model, df_resid)

    # 标准化系数 β（基于标准化 X 和 y）
    def _sd(xs: list[float]) -> float:
        m = sum(xs) / len(xs)
        return math.sqrt(sum((v - m) ** 2 for v in xs) / (len(xs) - 1)) if len(xs) > 1 else 0.0

    sd_y = _sd(y) if n > 1 else 1.0
    sd_ivs = [_sd([X[i][j] for i in range(n)]) for j in range(k)]

    # SE for each coefficient
    t_crit = _t_ppf(alpha, df_resid)
    coefficients = []
    # 截距
    se_int = math.sqrt(MSE * XtX_inv[0][0]) if math.isfinite(MSE) else float("nan")
    t_int = betas[0] / se_int if se_int > 0 else float("nan")
    p_int = _t_sf2(abs(t_int), df_resid) if math.isfinite(t_int) else float("nan")
    coefficients.append({
        "name": "截距 (Intercept)",
        "B": round(betas[0], 4),
        "SE": round(se_int, 4),
        "t": round(t_int, 4),
        "p": round(p_int, 4) if math.isfinite(p_int) else None,
        "ci_lower": round(betas[0] - t_crit * se_int, 4) if math.isfinite(se_int) else None,
        "ci_upper": round(betas[0] + t_crit * se_int, 4) if math.isfinite(se_int) else None,
        "beta": None,  # 截距无标准化系数
    })
    # 各 IV
    for j, name in enumerate(iv_names):
        b = betas[j + 1]
        se_b = math.sqrt(MSE * XtX_inv[j + 1][j + 1]) if math.isfinite(MSE) and XtX_inv[j+1][j+1] >= 0 else float("nan")
        t_val = b / se_b if se_b > 0 else float("nan")
        p_val = _t_sf2(abs(t_val), df_resid) if math.isfinite(t_val) else float("nan")
        beta = (b * sd_ivs[j] / sd_y) if sd_y > 0 and sd_ivs[j] > 0 else None
        coefficients.append({
            "name": name,
            "B": round(b, 4),
            "SE": round(se_b, 4),
            "t": round(t_val, 4),
            "p": round(p_val, 4) if math.isfinite(p_val) else None,
            "ci_lower": round(b - t_crit * se_b, 4) if math.isfinite(se_b) else None,
            "ci_upper": round(b + t_crit * se_b, 4) if math.isfinite(se_b) else None,
            "beta": round(beta, 4) if beta is not None else None,
        })

    return {
        "n": n,
        "k": k,
        "df_model": df_model,
        "df_resid": df_resid,
        "coefficients": coefficients,
        "R2": round(R2, 4),
        "R2_adj": round(R2_adj, 4) if math.isfinite(R2_adj) else None,
        "F": round(F, 4) if math.isfinite(F) else None,
        "F_p": round(F_p, 4) if math.isfinite(F_p) else None,
        "SSE": round(SSE, 4),
        "SSR": round(SSR, 4),
        "SST": round(SST, 4),
        "MSE": round(MSE, 4) if math.isfinite(MSE) else None,
        "RMSE": round(math.sqrt(MSE), 4) if math.isfinite(MSE) else None,
        "dv_name": dv_name,
        "iv_names": list(iv_names),
        "alpha": alpha,
    }


# ---------------------------------------------------------------------------
# APA-7 格式化
# ---------------------------------------------------------------------------

def _fmt_p(p: float | None) -> str:
    """APA-7 p 值格式。"""
    if p is None or not math.isfinite(p):
        return "—"
    if p < 0.001:
        return "< .001"
    return f"= {p:.3f}".lstrip("0")  # .123 not 0.123


def _fmt_b(v: float | None) -> str:
    if v is None or not math.isfinite(v):
        return "—"
    return f"{v:.2f}"


def format_apa_regression_table(
    result: dict[str, Any],
    title: str | None = None,
) -> str:
    """生成 APA-7 Markdown 回归系数三线表。"""
    dv = result.get("dv_name", "y")
    if title is None:
        title = f"OLS 回归分析：预测 {dv}"
    lines = [
        f"*{title}*",
        "",
        "| 变量 | *B* | *SE* | *β* | *t* | *p* | 95% CI |",
        "|------|-----|------|-----|-----|-----|--------|",
    ]
    for c in result["coefficients"]:
        ci = (f"[{c['ci_lower']:.2f}, {c['ci_upper']:.2f}]"
              if c["ci_lower"] is not None else "—")
        beta_str = _fmt_b(c["beta"]) if c["beta"] is not None else "—"
        lines.append(
            f"| {c['name']} | {_fmt_b(c['B'])} | {_fmt_b(c['SE'])} | "
            f"{beta_str} | {_fmt_b(c['t'])} | {_fmt_p(c['p'])} | {ci} |"
        )
    # 模型拟合摘要行
    r2_adj_str = f"{result['R2_adj']:.3f}" if result.get("R2_adj") is not None else "—"
    f_str = f"{result['F']:.2f}" if result.get("F") is not None else "—"
    lines += [
        "",
        (f"*注：N* = {result['n']}。"
         f"*R*² = {result['R2']:.3f}，"
         f"调整 *R*² = {r2_adj_str}，"
         f"*F*({result['df_model']}, {result['df_resid']}) = {f_str}，"
         f"*p* {_fmt_p(result.get('F_p'))}。"),
    ]
    return "\n".join(lines)


def format_apa_paragraph(result: dict[str, Any]) -> str:
    """生成 APA-7 格式回归结果文字段落。"""
    dv = result.get("dv_name", "y")
    n = result["n"]
    R2 = result["R2"]
    R2_adj = result.get("R2_adj")
    F = result.get("F")
    F_p = result.get("F_p")
    df1, df2 = result["df_model"], result["df_resid"]

    f_str = f"*F*({df1}, {df2}) = {F:.2f}" if F is not None else ""
    p_str = f"*p* {_fmt_p(F_p)}" if F_p is not None else ""
    r2_str = f"*R*² = {R2:.3f}"
    adj_str = f"（调整 *R*² = {R2_adj:.3f}）" if R2_adj is not None else ""

    # 显著预测变量
    sig = [c for c in result["coefficients"]
           if c["name"] != "截距 (Intercept)" and c["p"] is not None and c["p"] < 0.05]
    sig_strs = []
    for c in sig:
        beta = f"*β* = {c['beta']:.2f}，" if c["beta"] is not None else ""
        sig_strs.append(f"{c['name']}（*B* = {c['B']:.2f}，{beta}*t*({df2}) = {c['t']:.2f}，*p* {_fmt_p(c['p'])}）")

    para = (
        f"以 {', '.join(result['iv_names'])} 为预测变量对 {dv} 进行 OLS 回归分析（N = {n}）。"
        f"模型整体显著，{f_str}，{p_str}，{r2_str}{adj_str}，解释方差比例为 {R2 * 100:.1f}%。"
    )
    if sig_strs:
        para += f"显著预测变量包括：{'；'.join(sig_strs)}。"
    else:
        para += "无预测变量达显著水平（p < .05）。"
    return para


# ---------------------------------------------------------------------------
# MD + JSON sidecar
# ---------------------------------------------------------------------------

def write_regression_report(
    result: dict[str, Any],
    out_dir: str | pathlib.Path = "notes",
) -> tuple[pathlib.Path, pathlib.Path]:
    """写 regression_report.md + regression_report.json。"""
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    lines = [
        "# OLS 回归分析报告",
        "",
        format_apa_regression_table(result),
        "",
        "## APA-7 文字摘要",
        "",
        format_apa_paragraph(result),
        "",
        "## 模型诊断",
        "",
        f"- **SST** = {result['SST']}  |  **SSR** = {result['SSR']}  |  **SSE** = {result['SSE']}",
        f"- **MSE** = {result.get('MSE', '—')}  |  **RMSE** = {result.get('RMSE', '—')}",
        f"- **自由度**：模型 df = {result['df_model']}，残差 df = {result['df_resid']}",
    ]

    md_path = out / "regression_report.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    json_path = out / "regression_report.json"
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return md_path, json_path


# ---------------------------------------------------------------------------
# CSV 主入口
# ---------------------------------------------------------------------------

def _read_col(rows: list[dict[str, str]], col: str) -> list[float | None]:
    """读取一列数值，非数值或 NaN/inf 返回 None。"""
    result = []
    for row in rows:
        raw = row.get(col, "").strip()
        if not raw:
            result.append(None)
            continue
        try:
            v = float(raw)
            result.append(None if not math.isfinite(v) else v)
        except ValueError:
            result.append(None)
    return result


def analyze_regression(
    csv_path: str,
    dv: str,
    ivs: list[str],
    alpha: float = 0.05,
    out_dir: str | pathlib.Path = "notes",
    write_files: bool = True,
) -> dict[str, Any]:
    """从 CSV 执行 OLS 回归，返回完整结果字典。"""
    rows: list[dict[str, str]] = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows.append(dict(row))

    if not rows:
        raise ValueError(f"CSV 文件无数据行：{csv_path}")

    # 读取各列，仅保留所有变量均有效的行
    all_cols = [dv] + list(ivs)
    raw: dict[str, list[float | None]] = {c: _read_col(rows, c) for c in all_cols}

    # 完整案例过滤
    valid_idx = [i for i in range(len(rows))
                 if all(raw[c][i] is not None for c in all_cols)]
    n_total = len(rows)
    n_valid = len(valid_idx)
    n_excluded = n_total - n_valid

    if n_valid < len(ivs) + 2:
        raise ValueError(
            f"有效数据行数 ({n_valid}) 不足以拟合 {len(ivs)} 个预测变量 + 截距"
        )

    y = [raw[dv][i] for i in valid_idx]
    X = [[raw[iv][i] for iv in ivs] for i in valid_idx]

    ols_result = compute_ols(y, X, iv_names=ivs, dv_name=dv, alpha=alpha)
    ols_result["n_total"] = n_total
    ols_result["n_excluded"] = n_excluded
    ols_result["input_file"] = csv_path

    if write_files:
        md_path, json_path = write_regression_report(ols_result, out_dir=out_dir)
        ols_result["report_md"] = str(md_path)
        ols_result["report_json"] = str(json_path)

    return ols_result


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def regression_cli(args: list[str]) -> int:
    """psyclaw regress <data.csv> --dv <col> --iv col1,col2,..."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="psyclaw regress",
        description="OLS 多元回归分析，输出 APA-7 系数表（B/β/SE/t/p/95%CI）",
    )
    parser.add_argument("csv_file", help="输入数据 CSV 路径")
    parser.add_argument("--dv", required=True, help="因变量列名")
    parser.add_argument("--iv", required=True,
                        help="预测变量（逗号分隔，如 --iv age,edu,score）")
    parser.add_argument("--alpha", type=float, default=0.05,
                        help="显著性水平（默认 .05，影响 CI 和 * 标注）")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    parser.add_argument("--out", default="notes", help="报告输出目录（默认 notes/）")
    opts = parser.parse_args(args)

    iv_list = [s.strip() for s in opts.iv.split(",") if s.strip()]

    try:
        result = analyze_regression(
            csv_path=opts.csv_file,
            dv=opts.dv,
            ivs=iv_list,
            alpha=opts.alpha,
            out_dir=opts.out,
        )
    except (ValueError, FileNotFoundError, KeyError) as exc:
        print(f"错误：{exc}")
        return 1

    if opts.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0

    print()
    print(format_apa_regression_table(result))
    print()
    print(format_apa_paragraph(result))
    if "report_md" in result:
        print(f"\n报告已写入 {result['report_md']}")
    return 0
