"""负二项回归（NB2，过度离散计数结局）— stdlib only，APA-7。

填补过度离散计数回归空白：心理学计数结局（症状频次、攻击事件数、错误数等）
几乎总是过度离散（条件方差 > 条件均值），此时泊松回归会低估标准误、夸大显著性。
NB2 用色散参数 θ（α = 1/θ）建模 Var(y) = μ + μ²/θ = μ + αμ²，当 θ → ∞ 时退化为泊松。

与 `poisson.py` 同构，复用其矩阵 / 分布工具模式。核心增值是 **α = 0 的边界 LR 检验**
（泊松 vs NB 嵌套检验），直接回答「这份数据到底需不需要负二项模型」。

估计采用交替优化（profile / coordinate ascent，等价 MASS::glm.nb）：
  1. 给定 θ，用 Fisher scoring 拟合 β（对数连接 GLM，工作权重 W = θμ/(θ+μ)）；
  2. 给定 μ，用黄金分割最大化 θ 的条件对数似然；
  3. 交替直至对数似然收敛。

提供：
  - negbin_regression(X, y, ...)            → β/SE/z/p/IRR/CI/θ/α/偏差/LR/AIC/泊松检验
  - format_apa_negbin(result)               → APA-7 Markdown 表格 + 段落
  - write_negbin_report(result)             → MD + JSON sidecar
  - analyze_negbin(csv_path, dv, ivs)       → CSV 主入口
  - negbin_cli(argv)                        → CLI 入口

CLI:
  psyclaw negbin <data.csv> --dv <col> --iv col1,col2,...
          [--alpha .05] [--json] [--out dir]

理论依据：
  Cameron, A. C., & Trivedi, P. K. (2013). Regression Analysis of Count Data
  (2nd ed.). Cambridge University Press.
  Hilbe, J. M. (2011). Negative Binomial Regression (2nd ed.). Cambridge UP.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
from typing import Any

import numpy as np
from scipy import special, stats


# ─────────────────────────────────────────────────────────────────────────────
# 矩阵工具（numpy；测试直接 import _mat_invert/_mat_vec）
# ─────────────────────────────────────────────────────────────────────────────

def _mat_invert(M: list[list[float]]) -> list[list[float]] | None:
    """n×n 矩阵逆（numpy），奇异返回 None。"""
    try:
        return np.linalg.inv(np.asarray(M, dtype=float)).tolist()
    except np.linalg.LinAlgError:
        return None


def _mat_vec(A: list[list[float]], v: list[float]) -> list[float]:
    return (np.asarray(A, dtype=float) @ np.asarray(v, dtype=float)).tolist()


# ─────────────────────────────────────────────────────────────────────────────
# 数学工具（与 poisson.py 同款）
# ─────────────────────────────────────────────────────────────────────────────

def _safe_exp(x: float) -> float:
    """math.exp clamped to avoid OverflowError；分离数据时 beta→∞ 会触发。"""
    if x > 709.0:
        return math.inf
    if x < -709.0:
        return 0.0
    return math.exp(x)


def _normal_sf(z: float) -> float:
    """标准正态上尾概率 P(Z > |z|) —— scipy.stats.norm.sf。"""
    return float(stats.norm.sf(abs(z)))


def _normal_quantile(p: float) -> float:
    """标准正态分位数 —— scipy.special.ndtri。"""
    if p <= 0.0:
        return -1e300
    if p >= 1.0:
        return 1e300
    return float(special.ndtri(p))


def _chi2_sf(x: float, df: float) -> float:
    """χ² 分布上尾概率（生存函数）—— scipy.stats.chi2.sf。"""
    if x <= 0:
        return 1.0
    return float(stats.chi2.sf(x, df))


# ─────────────────────────────────────────────────────────────────────────────
# 对数似然（NB2 与泊松，对数连接）
# ─────────────────────────────────────────────────────────────────────────────

# 估计与数值搜索中 μ 的上界，避免 θ+μ 溢出（计数结局远小于此）
_MU_CAP = 1e12
# θ 搜索区间：θ→∞ 即泊松极限
_THETA_LO = 1e-4
_THETA_HI = 1e8


def _nb_loglik(y: list[float], mu: list[float], theta: float) -> float:
    """NB2 对数似然 Σ[lnΓ(y+θ) − lnΓ(θ) − lnΓ(y+1)
       + θ·ln(θ/(θ+μ)) + y·ln(μ/(θ+μ))]。θ→∞ 时趋于泊松对数似然。"""
    ll = 0.0
    lg_theta = math.lgamma(theta)
    for yi, mi in zip(y, mu):
        m = max(min(mi, _MU_CAP), 1e-300)
        tm = theta + m
        ll += (
            math.lgamma(yi + theta) - lg_theta - math.lgamma(yi + 1.0)
            + theta * math.log(theta / tm)
            + yi * math.log(m / tm)
        )
    return ll


def _poisson_loglik(y: list[float], mu: list[float]) -> float:
    """泊松对数似然 Σ[y·log μ − μ − log(y!)]（用于 α=0 边界 LR 检验）。"""
    ll = 0.0
    for yi, mi in zip(y, mu):
        m = max(min(mi, _MU_CAP), 1e-300)
        term = -m - math.lgamma(yi + 1.0)
        if yi > 0:
            term += yi * math.log(m)
        ll += term
    return ll


def _nb_deviance(y: list[float], mu: list[float], theta: float) -> float:
    """NB2 偏差 D = 2·Σ[y·ln(y/μ) − (y+θ)·ln((y+θ)/(μ+θ))]，y=0 项取极限。"""
    d = 0.0
    for yi, mi in zip(y, mu):
        m = max(min(mi, _MU_CAP), 1e-300)
        comp = 0.0
        if yi > 0:
            comp += yi * math.log(yi / m)
        comp -= (yi + theta) * math.log((yi + theta) / (m + theta))
        d += comp
    return max(0.0, 2.0 * d)


# ─────────────────────────────────────────────────────────────────────────────
# 估计子程序：给定 θ 用 Fisher scoring 拟合 β；给定 μ 用黄金分割拟合 θ
# ─────────────────────────────────────────────────────────────────────────────

def _eval_mu(X: list[list[float]], beta: list[float]) -> list[float]:
    n, k = len(X), len(beta)
    out = []
    for i in range(n):
        eta = sum(X[i][j] * beta[j] for j in range(k))
        out.append(min(_safe_exp(eta), _MU_CAP))
    return out


def _fit_beta(
    X: list[list[float]],
    y: list[float],
    theta: float,
    beta_init: list[float],
    *,
    max_iter: int = 100,
    tol: float = 1e-12,
) -> tuple[list[float], bool]:
    """给定色散 θ，用 Fisher scoring 拟合对数连接 NB2 的 β。

    NB2（对数连接）的 IRLS 量：
      工作权重 W_i = θ·μ_i / (θ + μ_i)
      score_j    = Σ_i x_ij · θ·(y_i − μ_i) / (θ + μ_i)
    当 θ → ∞ 时 W → μ、score 因子 → 1，即退化为泊松 IRLS。
    """
    n, k = len(X), len(beta_init)
    beta = beta_init[:]
    ll_prev = -1e300
    converged = False
    for _ in range(max_iter):
        mu = _eval_mu(X, beta)
        ll = _nb_loglik(y, mu, theta)

        XtWX = [[0.0] * k for _ in range(k)]
        score = [0.0] * k
        for i in range(n):
            mi = mu[i]
            tm = theta + mi
            wi = theta * mi / tm if tm > 0 else 0.0
            wi = max(wi, 1e-12)
            sfac = theta * (y[i] - mi) / tm if tm > 0 else 0.0
            xi = X[i]
            for a in range(k):
                xa = xi[a]
                score[a] += xa * sfac
                for b in range(k):
                    XtWX[a][b] += wi * xa * xi[b]

        inv_H = _mat_invert(XtWX)
        if inv_H is None:
            break  # 矩阵奇异，停止
        beta = [beta[j] + d for j, d in enumerate(_mat_vec(inv_H, score))]

        if abs(ll - ll_prev) < tol:
            converged = True
            break
        ll_prev = ll
    return beta, converged


def _fit_theta(y: list[float], mu: list[float]) -> float:
    """给定 μ，用黄金分割在 log θ 空间最大化 θ 的条件对数似然。

    若真 MLE 在 θ→∞（数据非过度离散），返回接近 θ_HI 的值（泊松极限）。
    """
    inv_phi = (math.sqrt(5.0) - 1.0) / 2.0  # 0.618…
    a, b = math.log(_THETA_LO), math.log(_THETA_HI)
    c = b - inv_phi * (b - a)
    d = a + inv_phi * (b - a)
    fc = _nb_loglik(y, mu, math.exp(c))
    fd = _nb_loglik(y, mu, math.exp(d))
    for _ in range(200):
        if fc > fd:
            b, d, fd = d, c, fc
            c = b - inv_phi * (b - a)
            fc = _nb_loglik(y, mu, math.exp(c))
        else:
            a, c, fc = c, d, fd
            d = a + inv_phi * (b - a)
            fd = _nb_loglik(y, mu, math.exp(d))
        if abs(b - a) < 1e-9:
            break
    return math.exp((a + b) / 2.0)


def _theta_se(y: list[float], mu: list[float], theta: float) -> float:
    """θ 的标准误：θ 条件对数似然在 MLE 处的二阶中心差分 → 1/√(−ll'')。

    near-Poisson（θ 撞上界、ll 关于 θ 几乎平坦）时返回 nan。
    """
    if not (math.isfinite(theta) and theta > 0):
        return float("nan")
    h = max(theta * 1e-4, 1e-6)
    f0 = _nb_loglik(y, mu, theta)
    fp = _nb_loglik(y, mu, theta + h)
    fm = _nb_loglik(y, mu, max(theta - h, _THETA_LO))
    second = (fp - 2.0 * f0 + fm) / (h * h)
    info = -second
    if not (math.isfinite(info) and info > 0):
        return float("nan")
    return math.sqrt(1.0 / info)


# ─────────────────────────────────────────────────────────────────────────────
# 核心：负二项（NB2）回归
# ─────────────────────────────────────────────────────────────────────────────

def negbin_regression(
    X: list[list[float]],
    y: list[float],
    *,
    max_iter: int = 100,
    tol: float = 1e-10,
    alpha: float = 0.05,
    predictor_names: list[str] | None = None,
) -> dict[str, Any]:
    """
    负二项回归（NB2，对数连接，交替优化 β / θ）。

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
      theta, theta_se, alpha_dispersion
      log_lik_null, log_lik_model, log_lik_poisson, deviance, null_deviance
      lr_chi2, lr_df, lr_p, mcfadden_r2, aic, bic
      lr_alpha_chi2, lr_alpha_p          (α=0 边界检验：泊松 vs NB)
      pearson_chi2, df_resid, n, sum_y, mean_y, alpha, convergence, n_iter, mu
    """
    n = len(y)
    k = len(X[0])

    if predictor_names is None:
        predictor_names = [f"X{i}" for i in range(1, k)]
    term_names = ["(Intercept)"] + list(predictor_names)

    sum_y = sum(y)
    mean_y = sum_y / n

    # ── θ 的矩估计初值：Var = μ + μ²/θ → θ ≈ ȳ²/(s² − ȳ)；非过度离散则用大值 ──
    var_y = sum((yi - mean_y) ** 2 for yi in y) / max(n - 1, 1)
    if var_y > mean_y and (var_y - mean_y) > 1e-9 and mean_y > 0:
        theta = mean_y * mean_y / (var_y - mean_y)
    else:
        theta = 1e6
    theta = min(max(theta, _THETA_LO), _THETA_HI)

    # ── β 初值：截距 = log ȳ，其余 0 ──
    beta = [0.0] * k
    beta[0] = math.log(max(mean_y, 1e-300))

    # ── 交替优化（coordinate ascent）──────────────────────────────────────────
    ll_prev = -1e300
    converged = False
    n_iter = 0
    for iteration in range(max_iter):
        n_iter = iteration + 1
        beta, _ = _fit_beta(X, y, theta, beta)
        mu = _eval_mu(X, beta)
        theta = _fit_theta(y, mu)
        ll = _nb_loglik(y, mu, theta)
        if abs(ll - ll_prev) < tol:
            converged = True
            break
        ll_prev = ll

    # ── 最终估计量 ─────────────────────────────────────────────────────────────
    mu = _eval_mu(X, beta)
    ll_model = _nb_loglik(y, mu, theta)
    deviance = _nb_deviance(y, mu, theta)

    # β 的信息矩阵（θ 视为已知；NB2 下 β 与 θ 渐近正交）
    XtWX = [[0.0] * k for _ in range(k)]
    for i in range(n):
        mi = mu[i]
        tm = theta + mi
        wi = max(theta * mi / tm if tm > 0 else 0.0, 1e-12)
        xi = X[i]
        for a in range(k):
            xa = xi[a]
            for b in range(k):
                XtWX[a][b] += wi * xa * xi[b]
    inv_H = _mat_invert(XtWX)
    se_list = (
        [math.sqrt(max(inv_H[j][j], 0.0)) for j in range(k)]
        if inv_H is not None
        else [float("nan")] * k
    )

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

    theta_se = _theta_se(y, mu, theta)
    alpha_disp = 1.0 / theta if theta > 0 else float("inf")

    # ── 零模型（仅截距 NB，自身 θ）：MLE μ̂ = ȳ ───────────────────────────────
    mu_null = [max(mean_y, 1e-300)] * n
    theta_null = _fit_theta(y, mu_null)
    ll_null = _nb_loglik(y, mu_null, theta_null)
    null_deviance = _nb_deviance(y, mu_null, theta_null)

    lr_chi2 = max(0.0, 2.0 * (ll_model - ll_null))
    lr_df   = k - 1
    lr_p    = _chi2_sf(lr_chi2, lr_df) if lr_df > 0 else float("nan")
    mcfadden = 1.0 - ll_model / ll_null if abs(ll_null) > 1e-15 else float("nan")

    # AIC/BIC：参数计 k + 1（含 θ）
    n_params = k + 1
    aic = -2.0 * ll_model + 2.0 * n_params
    bic = -2.0 * ll_model + n_params * math.log(n)

    # ── α=0 边界 LR 检验（泊松 vs NB）──────────────────────────────────────────
    beta_pois, _ = _fit_beta(X, y, _THETA_HI, [b for b in beta])
    mu_pois = _eval_mu(X, beta_pois)
    ll_poisson = _poisson_loglik(y, mu_pois)
    lr_alpha = max(0.0, 2.0 * (ll_model - ll_poisson))
    # α=0 在参数空间边界上 → ½·χ²₀ + ½·χ²₁ 混合分布（Cameron & Trivedi 2013）
    lr_alpha_p = 0.5 * _chi2_sf(lr_alpha, 1) if lr_alpha > 0 else 1.0

    # Pearson χ²（NB2 方差函数）
    pearson_chi2 = sum(
        (y[i] - mu[i]) ** 2 / max(mu[i] + mu[i] * mu[i] / theta, 1e-300)
        for i in range(n)
    )
    df_resid = n - k

    return {
        "term_names":       term_names,
        "predictor_names":  list(predictor_names),
        "coef":             beta,
        "se":               se_list,
        "z":                z_vals,
        "p":                p_vals,
        "irr":              irr,
        "irr_ci_lower":     irr_ci_lo,
        "irr_ci_upper":     irr_ci_hi,
        "ci_lower":         ci_lower,
        "ci_upper":         ci_upper,
        "theta":            theta,
        "theta_se":         theta_se,
        "alpha_dispersion": alpha_disp,
        "log_lik_null":     ll_null,
        "log_lik_model":    ll_model,
        "log_lik_poisson":  ll_poisson,
        "deviance":         deviance,
        "null_deviance":    null_deviance,
        "lr_chi2":          lr_chi2,
        "lr_df":            lr_df,
        "lr_p":             lr_p,
        "mcfadden_r2":      mcfadden,
        "aic":              aic,
        "bic":              bic,
        "lr_alpha_chi2":    lr_alpha,
        "lr_alpha_p":       lr_alpha_p,
        "pearson_chi2":     pearson_chi2,
        "df_resid":         df_resid,
        "n":                n,
        "sum_y":            sum_y,
        "mean_y":           mean_y,
        "alpha":            alpha,
        "convergence":      converged,
        "n_iter":           n_iter,
        "mu":               mu,
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


def format_apa_negbin(
    result: dict[str, Any],
    dv_name: str = "count",
) -> str:
    """
    生成 APA-7 负二项回归结果文本：
      ① Markdown 三线系数表（*B*/SE/*z*/*p*/IRR/95%CI[IRR]）
      ② 模型整体拟合段落（LR/偏差/McFadden R²/AIC）
      ③ 色散参数 θ/α 段落
      ④ α=0 边界 LR 检验段落（泊松 vs NB）
      ⑤ 显著预测变量文字总结
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
        f"*Note.* Negative binomial (NB2, log link) regression predicting {dv_name} "
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

    # ── 色散参数段落 ──
    theta = result["theta"]
    theta_se = result["theta_se"]
    a_disp = result["alpha_dispersion"]
    se_str = f" (*SE* = {_fmt(theta_se, 3)})" if math.isfinite(theta_se) else ""
    disp_text = (
        f"\n\nThe estimated dispersion parameter was θ = {_fmt(theta, 3)}{se_str} "
        f"(α = 1/θ = {_fmt(a_disp, 3)}), modeling the conditional variance as "
        f"Var(*Y*) = μ + μ²/θ."
    )

    # ── α=0 边界 LR 检验段落（泊松 vs NB）──
    lr_a = result["lr_alpha_chi2"]
    lr_a_p = result["lr_alpha_p"]
    if math.isfinite(lr_a_p) and lr_a_p < alpha:
        alpha_text = (
            f"\n\nThe likelihood-ratio test of overdispersion (H₀: α = 0, "
            f"Poisson vs. negative binomial) was significant, "
            f"χ̄²(1) = {_fmt(lr_a)}, *p* {_fmt_p(lr_a_p)} (boundary-corrected, "
            f"½·χ²₁ mixture), indicating that the negative binomial model is "
            f"preferred over Poisson."
        )
    else:
        alpha_text = (
            f"\n\nThe likelihood-ratio test of overdispersion (H₀: α = 0, "
            f"Poisson vs. negative binomial) was not significant, "
            f"χ̄²(1) = {_fmt(lr_a)}, *p* {_fmt_p(lr_a_p)} (boundary-corrected), "
            f"suggesting a Poisson model may suffice."
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

    return "\n\n".join([table, note, model_fit]) + disp_text + alpha_text + pred_text


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


def write_negbin_report(
    result: dict[str, Any],
    *,
    out_dir: str | pathlib.Path | None = None,
    dv_name: str = "count",
    filename: str = "negbin_report",
) -> dict[str, str]:
    """写 MD + JSON sidecar，返回实际写入路径字典。"""
    md_text  = format_apa_negbin(result, dv_name=dv_name)
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

def analyze_negbin(
    csv_path: str,
    dv: str,
    ivs: list[str],
    *,
    alpha: float = 0.05,
    out_dir: str | pathlib.Path | None = None,
) -> dict[str, Any]:
    """
    从 CSV 文件读取数据并跑负二项回归（NB2）。

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
        raise ValueError(f"完整案例不足（{len(complete)} 行），无法运行负二项回归。")

    y_vals = [r[dv] for r in complete]

    # 计数结局校验：非负整数
    for v in y_vals:
        if v < 0:
            raise ValueError(
                f"因变量 '{dv}' 含负值 {v}，负二项回归要求非负计数。"
            )
        if abs(v - round(v)) > 1e-9:
            raise ValueError(
                f"因变量 '{dv}' 含非整数值 {v}，负二项回归要求计数（整数）结局。"
            )
    if sum(y_vals) <= 0:
        raise ValueError(f"因变量 '{dv}' 全为 0，无法估计模型。")

    # 构建设计矩阵（含截距列）
    X = [[1.0] + [r[iv] for iv in ivs] for r in complete]
    y = y_vals

    result = negbin_regression(
        X, y,
        alpha=alpha,
        predictor_names=ivs,
    )
    result["n_excluded"] = n_missing
    result["dv"] = dv

    write_negbin_report(result, out_dir=out_dir, dv_name=dv)
    return {"result": result}


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def negbin_cli(argv: list[str] | None = None) -> int:
    """
    psyclaw negbin <data.csv> --dv <col> --iv col1,col2,...
            [--alpha .05] [--json] [--out dir]
    """
    ap = argparse.ArgumentParser(
        prog="psyclaw negbin",
        description="负二项回归（NB2，过度离散计数；交替优化 β/θ；IRR/Wald/泊松-NB 检验；APA-7）",
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
        output = analyze_negbin(
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
        print(format_apa_negbin(result, dv_name=args.dv))
        n_ex = result.get("n_excluded", 0)
        if n_ex:
            print(f"\n（已排除 {n_ex} 个含缺失值的案例）")
        conv_status = "已收敛" if result["convergence"] else "⚠ 未完全收敛"
        print(f"\n迭代次数：{result['n_iter']}  收敛状态：{conv_status}")
        if args.out:
            print(f"\n报告已写入：{args.out}/negbin_report.{{md,json}}")

    return 0
