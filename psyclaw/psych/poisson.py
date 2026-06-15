"""泊松回归（计数结局）— IRLS 算法，IRR/Wald/LR/过度离散，APA-7，stdlib only。

填补计数结局回归空白：心理学常见错误数、症状频次、攻击事件计数等计数变量，
其条件分布常服从泊松而非正态，OLS 会给出不当推断与负的预测计数。本模块以
对数连接 GLM（μ = exp(Xβ)）建模，配套发生率比（IRR）、偏差、过度离散诊断。

提供：
  - poisson_regression(X, y, ...)           → β/SE/z/p/IRR/CI/偏差/LR/AIC/φ
  - format_apa_poisson(result)              → APA-7 Markdown 表格 + 段落
  - write_poisson_report(result)            → MD + JSON sidecar
  - analyze_poisson(csv_path, dv, ivs)      → CSV 主入口
  - poisson_cli(argv)                       → CLI 入口

CLI:
  psyclaw poisson <data.csv> --dv <col> --iv col1,col2,...
          [--alpha .05] [--json] [--out dir]

理论依据：
  McCullagh, P., & Nelder, J. A. (1989). Generalized Linear Models (2nd ed.).
  Cameron, A. C., & Trivedi, P. K. (2013). Regression Analysis of Count Data
  (2nd ed.). Cambridge University Press.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# 矩阵工具（Gauss-Jordan，stdlib only，与 logistic.py / regression.py 同款）
# ─────────────────────────────────────────────────────────────────────────────

def _mat_invert(M: list[list[float]]) -> list[list[float]] | None:
    """Gauss-Jordan 消去求 n×n 矩阵逆，奇异返回 None。"""
    n = len(M)
    aug = [M[i][:] + [1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for col in range(n):
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


def _mat_vec(A: list[list[float]], v: list[float]) -> list[float]:
    return [sum(A[i][j] * v[j] for j in range(len(v))) for i in range(len(A))]


# ─────────────────────────────────────────────────────────────────────────────
# 数学工具
# ─────────────────────────────────────────────────────────────────────────────

def _safe_exp(x: float) -> float:
    """math.exp clamped to avoid OverflowError；分离数据时 beta→∞ 会触发。"""
    if x > 709.0:
        return math.inf
    if x < -709.0:
        return 0.0
    return math.exp(x)


def _erfc_approx(x: float) -> float:
    """互补误差函数近似（Abramowitz & Stegun 7.1.26）。"""
    t = 1.0 / (1.0 + 0.3275911 * abs(x))
    poly = t * (0.254829592 + t * (-0.284496736 + t * (1.421413741
           + t * (-1.453152027 + t * 1.061405429))))
    erfc_pos = poly * math.exp(-x * x)
    return erfc_pos if x >= 0 else 2.0 - erfc_pos


def _normal_sf(z: float) -> float:
    """标准正态上尾概率 P(Z > |z|)。"""
    return _erfc_approx(abs(z) / math.sqrt(2)) / 2.0


def _normal_quantile(p: float) -> float:
    """标准正态分位数（二分法，精度 1e-10）。"""
    if p <= 0.0:
        return -1e300
    if p >= 1.0:
        return 1e300
    lo, hi = -10.0, 10.0
    for _ in range(80):
        mid = (lo + hi) / 2.0
        cdf = 1.0 - _erfc_approx(mid / math.sqrt(2)) / 2.0
        if cdf < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _gammainc_series(a: float, x: float) -> float:
    """正则化下不完全 Gamma 函数 P(a, x) 级数展开。"""
    if x == 0.0:
        return 0.0
    ap, delta, summ = a, 1.0 / a, 1.0 / a
    for _ in range(300):
        ap += 1.0
        delta *= x / ap
        summ += delta
        if abs(delta) < abs(summ) * 1e-12:
            break
    return summ * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gammainc_cf(a: float, x: float) -> float:
    """Q(a, x) 连分式展开（Lentz 算法）。"""
    fpmin = 1e-300
    b, c, d = x + 1.0 - a, 1.0 / fpmin, 1.0 / max(abs(x + 1.0 - a), fpmin)
    if x + 1.0 - a < 0:
        d = 1.0 / fpmin
    h = d
    for i in range(1, 301):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < fpmin:
            d = fpmin
        c = b + an / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-12:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def _chi2_sf(x: float, df: float) -> float:
    """χ² 分布上尾概率（生存函数）。"""
    if x <= 0:
        return 1.0
    a, x2 = df / 2.0, x / 2.0
    if x2 < a + 1:
        return 1.0 - _gammainc_series(a, x2)
    return _gammainc_cf(a, x2)


# ─────────────────────────────────────────────────────────────────────────────
# 偏差与对数似然（泊松，对数连接）
# ─────────────────────────────────────────────────────────────────────────────

def _poisson_loglik(y: list[float], mu: list[float]) -> float:
    """泊松对数似然 Σ[y·log μ − μ − log(y!)]（μ→0 用 lim y·log μ=0 处理 y=0）。"""
    ll = 0.0
    for yi, mi in zip(y, mu):
        m = max(mi, 1e-300)
        term = -m - math.lgamma(yi + 1.0)
        if yi > 0:
            term += yi * math.log(m)
        ll += term
    return ll


def _poisson_deviance(y: list[float], mu: list[float]) -> float:
    """泊松偏差 D = 2·Σ[y·log(y/μ) − (y − μ)]，y=0 项的 y·log(y/μ)→0。"""
    d = 0.0
    for yi, mi in zip(y, mu):
        m = max(mi, 1e-300)
        comp = -(yi - m)
        if yi > 0:
            comp += yi * math.log(yi / m)
        d += comp
    return max(0.0, 2.0 * d)


# ─────────────────────────────────────────────────────────────────────────────
# 核心：IRLS 泊松回归
# ─────────────────────────────────────────────────────────────────────────────

def poisson_regression(
    X: list[list[float]],
    y: list[float],
    *,
    max_iter: int = 200,
    tol: float = 1e-10,
    alpha: float = 0.05,
    predictor_names: list[str] | None = None,
) -> dict[str, Any]:
    """
    泊松回归（对数连接，IRLS = Newton-Raphson 精确 Hessian）。

    参数
    ----
    X              n×k 设计矩阵（**已含**第一列全为 1 的截距列）
    y              长度 n 的非负计数响应向量
    predictor_names  k-1 个预测变量名称（不含截距；默认 X1, X2, …）

    返回
    ----
    dict 键：
      term_names, predictor_names
      coef, se, z, p, irr, irr_ci_lower, irr_ci_upper, ci_lower, ci_upper
      log_lik_null, log_lik_model, deviance, null_deviance
      lr_chi2, lr_df, lr_p, mcfadden_r2, aic, bic
      pearson_chi2, dispersion, overdispersed
      n, sum_y, mean_y, alpha, convergence, n_iter, mu
    """
    n = len(y)
    k = len(X[0])

    if predictor_names is None:
        predictor_names = [f"X{i}" for i in range(1, k)]
    term_names = ["(Intercept)"] + list(predictor_names)

    sum_y = sum(y)
    mean_y = sum_y / n

    # 零模型（仅截距）：MLE μ̂ = ȳ，β0 = log ȳ
    mu_null = max(mean_y, 1e-300)
    mu_null_vec = [mu_null] * n
    ll_null = _poisson_loglik(y, mu_null_vec)
    null_deviance = _poisson_deviance(y, mu_null_vec)

    # ── IRLS ──────────────────────────────────────────────────────────────────
    # 截距初值 = log ȳ（其余为 0），加速收敛并避免 μ 初始过小
    beta = [0.0] * k
    beta[0] = math.log(mu_null)
    ll_prev = -1e300
    converged = False
    n_iter = 0

    for iteration in range(max_iter):
        n_iter = iteration + 1
        eta = [sum(X[i][j] * beta[j] for j in range(k)) for i in range(n)]
        mu  = [_safe_exp(e) for e in eta]
        w   = [max(m, 1e-10) for m in mu]   # 泊松工作权重 = μ

        ll = _poisson_loglik(y, mu)

        # X^T W X
        XtWX = [[0.0] * k for _ in range(k)]
        for i in range(n):
            wi = w[i]
            for a in range(k):
                xa = X[i][a]
                for b in range(k):
                    XtWX[a][b] += wi * xa * X[i][b]

        # score = X^T (y - mu)
        score = [
            sum(X[i][j] * (y[i] - mu[i]) for i in range(n))
            for j in range(k)
        ]

        inv_H = _mat_invert(XtWX)
        if inv_H is None:
            break  # 矩阵奇异，停止

        beta = [beta[j] + d for j, d in enumerate(_mat_vec(inv_H, score))]

        if abs(ll - ll_prev) < tol:
            converged = True
            break
        ll_prev = ll

    # ── 最终估计量 ─────────────────────────────────────────────────────────────
    eta = [sum(X[i][j] * beta[j] for j in range(k)) for i in range(n)]
    mu  = [_safe_exp(e) for e in eta]
    w   = [max(m, 1e-10) for m in mu]

    XtWX = [[0.0] * k for _ in range(k)]
    for i in range(n):
        wi = w[i]
        for a in range(k):
            xa = X[i][a]
            for b in range(k):
                XtWX[a][b] += wi * xa * X[i][b]

    inv_H = _mat_invert(XtWX)
    se_list = (
        [math.sqrt(max(inv_H[j][j], 0.0)) for j in range(k)]
        if inv_H is not None
        else [float("nan")] * k
    )

    ll_model = _poisson_loglik(y, mu)
    deviance = _poisson_deviance(y, mu)

    z_vals = [
        beta[j] / se_list[j] if (se_list[j] > 0 and math.isfinite(se_list[j]))
        else float("nan")
        for j in range(k)
    ]
    p_vals = [
        2.0 * _normal_sf(abs(z)) if math.isfinite(z) else float("nan")
        for z in z_vals
    ]

    z_crit = _normal_quantile(1.0 - alpha / 2.0)
    ci_lower = [beta[j] - z_crit * se_list[j] for j in range(k)]
    ci_upper = [beta[j] + z_crit * se_list[j] for j in range(k)]
    irr      = [_safe_exp(beta[j]) for j in range(k)]
    irr_ci_lo = [_safe_exp(c) for c in ci_lower]
    irr_ci_hi = [_safe_exp(c) for c in ci_upper]

    lr_chi2 = max(0.0, 2.0 * (ll_model - ll_null))
    lr_df   = k - 1  # 预测变量个数（不含截距）
    lr_p    = _chi2_sf(lr_chi2, lr_df) if lr_df > 0 else float("nan")

    mcfadden = 1.0 - ll_model / ll_null if abs(ll_null) > 1e-15 else float("nan")

    aic = -2.0 * ll_model + 2.0 * k
    bic = -2.0 * ll_model + k * math.log(n)

    # 过度离散诊断：Pearson χ² / 残差自由度
    pearson_chi2 = sum(
        (y[i] - mu[i]) ** 2 / max(mu[i], 1e-300) for i in range(n)
    )
    df_resid = n - k
    dispersion = pearson_chi2 / df_resid if df_resid > 0 else float("nan")
    overdispersed = bool(math.isfinite(dispersion) and dispersion > 1.5)

    return {
        "term_names":      term_names,
        "predictor_names": list(predictor_names),
        "coef":            beta,
        "se":              se_list,
        "z":               z_vals,
        "p":               p_vals,
        "irr":             irr,
        "irr_ci_lower":    irr_ci_lo,
        "irr_ci_upper":    irr_ci_hi,
        "ci_lower":        ci_lower,
        "ci_upper":        ci_upper,
        "log_lik_null":    ll_null,
        "log_lik_model":   ll_model,
        "deviance":        deviance,
        "null_deviance":   null_deviance,
        "lr_chi2":         lr_chi2,
        "lr_df":           lr_df,
        "lr_p":            lr_p,
        "mcfadden_r2":     mcfadden,
        "aic":             aic,
        "bic":             bic,
        "pearson_chi2":    pearson_chi2,
        "df_resid":        df_resid,
        "dispersion":      dispersion,
        "overdispersed":   overdispersed,
        "n":               n,
        "sum_y":           sum_y,
        "mean_y":          mean_y,
        "alpha":           alpha,
        "convergence":     converged,
        "n_iter":          n_iter,
        "mu":              mu,
    }


# ─────────────────────────────────────────────────────────────────────────────
# APA-7 格式化
# ─────────────────────────────────────────────────────────────────────────────

def _fmt(x: float, dec: int = 2) -> str:
    if not math.isfinite(x):
        return str(x)
    return f"{x:.{dec}f}"


def _fmt_p(p: float) -> str:
    if not math.isfinite(p):
        return "N/A"
    if p < .001:
        return "< .001"
    return f"= {p:.3f}"


def _fmt_irr(x: float) -> str:
    if math.isinf(x):
        return ">1e15"
    if math.isnan(x):
        return "NaN"
    return f"{x:.2f}"


def format_apa_poisson(
    result: dict[str, Any],
    dv_name: str = "count",
) -> str:
    """
    生成 APA-7 泊松回归结果文本：
      ① Markdown 三线系数表（*B*/SE/*z*/*p*/IRR/95%CI[IRR]）
      ② 模型整体拟合段落（LR/偏差/McFadden R²/AIC）
      ③ 过度离散诊断段落
      ④ 显著预测变量文字总结
    """
    names = result["term_names"]
    coef  = result["coef"]
    se    = result["se"]
    z     = result["z"]
    p     = result["p"]
    irr   = result["irr"]
    irr_lo = result["irr_ci_lower"]
    irr_hi = result["irr_ci_upper"]
    alpha = result.get("alpha", 0.05)
    ci_pct = int((1 - alpha) * 100)

    # ── 系数表 ──
    col_w0 = max(max(len(n) for n in names) + 1, 16)
    header = (
        f"| {'Predictor':<{col_w0}} | {'*B*':>7} | {'SE':>6} | "
        f"{'*z*':>7} | {'*p*':>7} | {'IRR':>6} | "
        f"{f'{ci_pct}% CI [IRR]':>20} |"
    )
    sep = (
        f"|:{'-' * col_w0}-|{'-' * 8}:|{'-' * 7}:|"
        f"{'-' * 8}:|{'-' * 8}:|{'-' * 7}:|{'-' * 21}:|"
    )
    rows = [header, sep]
    for j, name in enumerate(names):
        sig = "*" if (math.isfinite(p[j]) and p[j] < alpha) else ""
        p_str = _fmt_p(p[j])
        ci_str = f"[{_fmt_irr(irr_lo[j])}, {_fmt_irr(irr_hi[j])}]"
        rows.append(
            f"| {name + sig:<{col_w0}} | {_fmt(coef[j]):>7} | {_fmt(se[j]):>6} | "
            f"{_fmt(z[j]):>7} | {p_str:>7} | {_fmt_irr(irr[j]):>6} | "
            f"{ci_str:>20} |"
        )

    table = "\n".join(rows)
    note = (
        f"*Note.* Poisson regression (log link) predicting {dv_name} "
        f"(*N* = {result['n']}, *M* = {_fmt(result['mean_y'])}). "
        f"IRR = incidence rate ratio. CI = confidence interval. "
        f"* *p* {_fmt_p(alpha)}."
    )

    # ── 模型整体拟合 ──
    conv_note = "" if result["convergence"] else " (**收敛警告：未达到收敛判据，解可能不稳定**)"
    model_fit = (
        f"The overall model was statistically significant, "
        f"χ²({result['lr_df']}) = {_fmt(result['lr_chi2'])}, "
        f"*p* {_fmt_p(result['lr_p'])}, "
        f"McFadden *R*² = {_fmt(result['mcfadden_r2'])}, "
        f"AIC = {_fmt(result['aic'])}, "
        f"residual deviance = {_fmt(result['deviance'])} "
        f"on {result['df_resid']} *df*.{conv_note}"
    )

    # ── 过度离散诊断 ──
    disp = result["dispersion"]
    if result["overdispersed"]:
        disp_text = (
            f"\n\nThe dispersion statistic (Pearson χ²/df) was "
            f"{_fmt(disp)}, indicating **overdispersion** (> 1.5). "
            f"A negative binomial or quasi-Poisson model is recommended, "
            f"as the Poisson standard errors are likely understated."
        )
    else:
        disp_text = (
            f"\n\nThe dispersion statistic (Pearson χ²/df) was "
            f"{_fmt(disp)}, consistent with the Poisson "
            f"equidispersion assumption."
        )

    # ── 显著预测变量段落 ──
    sig_preds = [
        (names[j], coef[j], irr[j], irr_lo[j], irr_hi[j], p[j])
        for j in range(1, len(names))  # 跳过截距
        if math.isfinite(p[j]) and p[j] < alpha
    ]
    if sig_preds:
        parts = []
        for name, b, irrv, ilo, ihi, pv in sig_preds:
            pct = (irrv - 1.0) * 100.0
            dir_word = "increase" if b > 0 else "decrease"
            mag = f"{abs(pct):.1f}% {dir_word}" if math.isfinite(pct) else "change"
            parts.append(
                f"a one-unit increase in {name} was associated with a {mag} "
                f"in the expected count of {dv_name} "
                f"(*B* = {_fmt(b)}, IRR = {_fmt_irr(irrv)}, "
                f"{ci_pct}% CI [{_fmt_irr(ilo)}, {_fmt_irr(ihi)}], "
                f"*p* {_fmt_p(pv)})"
            )
        pred_text = "\n\n" + "; ".join(parts) + "."
    else:
        pred_text = f"\n\nNo predictors reached statistical significance (*p* < {alpha:.2f})."

    return "\n\n".join([table, note, model_fit]) + disp_text + pred_text


# ─────────────────────────────────────────────────────────────────────────────
# 报告写出
# ─────────────────────────────────────────────────────────────────────────────

def _json_safe(obj: Any) -> Any:
    """递归把 NaN/inf 替换为 None，使 JSON 严格合法。"""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


def write_poisson_report(
    result: dict[str, Any],
    *,
    out_dir: str | pathlib.Path | None = None,
    dv_name: str = "count",
    filename: str = "poisson_report",
) -> dict[str, str]:
    """写 MD + JSON sidecar，返回实际写入路径字典。"""
    md_text  = format_apa_poisson(result, dv_name=dv_name)
    payload  = _json_safe({k: v for k, v in result.items() if k != "mu"})

    paths: dict[str, str] = {}
    if out_dir is not None:
        out = pathlib.Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        md_path   = out / f"{filename}.md"
        json_path = out / f"{filename}.json"
        md_path.write_text(md_text, encoding="utf-8")
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        paths = {"md": str(md_path), "json": str(json_path)}
    return paths


# ─────────────────────────────────────────────────────────────────────────────
# CSV 主入口
# ─────────────────────────────────────────────────────────────────────────────

def analyze_poisson(
    csv_path: str,
    dv: str,
    ivs: list[str],
    *,
    alpha: float = 0.05,
    out_dir: str | pathlib.Path | None = None,
) -> dict[str, Any]:
    """
    从 CSV 文件读取数据并跑泊松回归。

    参数
    ----
    csv_path  CSV 文件路径
    dv        因变量列名（必须为非负整数计数）
    ivs       预测变量列名列表
    alpha     显著性水平（默认 .05）
    out_dir   sidecar 输出目录（None 则不写文件）
    """
    rows: list[dict] = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    all_cols = [dv] + ivs
    complete: list[dict] = []
    n_missing = 0
    for row in rows:
        try:
            vals = {c: float(row[c]) for c in all_cols}
            complete.append(vals)
        except (ValueError, KeyError):
            n_missing += 1

    if len(complete) < 2:
        raise ValueError(f"完整案例不足（{len(complete)} 行），无法运行泊松回归。")

    y_vals = [r[dv] for r in complete]

    # 计数结局校验：非负整数
    for v in y_vals:
        if v < 0:
            raise ValueError(
                f"因变量 '{dv}' 含负值 {v}，泊松回归要求非负计数。"
            )
        if abs(v - round(v)) > 1e-9:
            raise ValueError(
                f"因变量 '{dv}' 含非整数值 {v}，泊松回归要求计数（整数）结局。"
            )
    if sum(y_vals) <= 0:
        raise ValueError(f"因变量 '{dv}' 全为 0，无法估计模型。")

    # 构建设计矩阵（含截距列）
    X = [[1.0] + [r[iv] for iv in ivs] for r in complete]
    y = y_vals

    result = poisson_regression(
        X, y,
        alpha=alpha,
        predictor_names=ivs,
    )
    result["n_excluded"] = n_missing
    result["dv"] = dv

    write_poisson_report(result, out_dir=out_dir, dv_name=dv)
    return {"result": result}


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def poisson_cli(argv: list[str] | None = None) -> int:
    """
    psyclaw poisson <data.csv> --dv <col> --iv col1,col2,...
            [--alpha .05] [--json] [--out dir]
    """
    ap = argparse.ArgumentParser(
        prog="psyclaw poisson",
        description="泊松回归（计数结局；IRLS；IRR/Wald/LR/过度离散诊断；APA-7）",
    )
    ap.add_argument("csv", help="输入数据 CSV 路径")
    ap.add_argument("--dv",  required=True, help="因变量列名（非负整数计数）")
    ap.add_argument("--iv",  required=True,
                    help="预测变量列名，逗号分隔（如 age,sex,score）")
    ap.add_argument("--alpha",  type=float, default=0.05, help="显著性水平（默认 .05）")
    ap.add_argument("--out",    default=None, help="sidecar 输出目录（默认不写文件）")
    ap.add_argument("--json",   action="store_true", help="输出机器可读 JSON")
    args = ap.parse_args(argv)

    ivs = [c.strip() for c in args.iv.split(",") if c.strip()]
    try:
        output = analyze_poisson(
            args.csv, args.dv, ivs,
            alpha=args.alpha,
            out_dir=args.out,
        )
    except Exception as exc:
        print(f"错误：{exc}")
        return 1

    result = output["result"]

    if args.json:
        payload = _json_safe({k: v for k, v in result.items() if k != "mu"})
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(format_apa_poisson(result, dv_name=args.dv))
        n_ex = result.get("n_excluded", 0)
        if n_ex:
            print(f"\n（已排除 {n_ex} 个含缺失值的案例）")
        conv_status = "已收敛" if result["convergence"] else "⚠ 未完全收敛"
        print(f"\n迭代次数：{result['n_iter']}  收敛状态：{conv_status}")
        if args.out:
            print(f"\n报告已写入：{args.out}/poisson_report.{{md,json}}")

    return 0
