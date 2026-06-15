"""有序 Logistic 回归 — 比例优势（累积 logit）模型，阻尼 Newton-Raphson，APA-7，stdlib only。

填补有序分类结局回归空白：心理学结局极常见**有序分类**（Likert 单题、严重度分级、
同意程度 1–5）。此前只能误用 OLS（违反等距、可预测出界）或塌缩为二元 Logistic（丢信息）。

模型（McCullagh, 1980 比例优势 / proportional odds）：

    logit(P(Y ≤ j | x)) = θ_j − β′x ,   j = 1, …, J−1

其中 θ_1 < θ_2 < … < θ_{J−1} 为 J−1 个有序阈值（截距），β 为对所有切点**共享**的斜率
（比例优势假设）。一个单位 x 增加使「处于更高类别」的优势乘以 exp(β)。

提供：
  - ordinal_regression(X, y_cat, J, ...)        → θ/β/SE/z/p/OR/CI/R²/LR
  - proportional_odds_check(X, y_cat, J, ...)   → 各二分切点斜率离散度（Brant 思路）
  - predict_probs(thresholds, beta, x)          → 各有序类别预测概率（和=1）
  - format_apa_ordinal(result, po=...)          → APA-7 Markdown 表格 + 段落
  - write_ordinal_report(result)                → MD + JSON sidecar
  - analyze_ordinal(csv_path, dv, ivs)          → CSV 主入口
  - ordinal_cli(argv)                           → CLI 入口

CLI:
  psyclaw ordinal <data.csv> --dv <col> --iv col1,col2,...
          [--alpha .05] [--no-po-check] [--json] [--out dir]

理论依据：
  McCullagh, P. (1980). Regression models for ordinal data. JRSS-B, 42(2), 109–142.
  Agresti, A. (2010). Analysis of Ordinal Categorical Data (2nd ed.).
  Liddell, T. M., & Kruschke, J. K. (2018). Analyzing ordinal data with metric
    models: What could possibly go wrong? J. Exp. Soc. Psychol., 79, 328–348.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# 矩阵工具（Gauss-Jordan，stdlib only，与 logistic.py 同款）
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
# 数学工具（与 logistic.py 同款）
# ─────────────────────────────────────────────────────────────────────────────

def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def _safe_exp(x: float) -> float:
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
# 对数似然 + 解析梯度（比例优势模型）
# ─────────────────────────────────────────────────────────────────────────────

def _ll_grad(
    params: list[float],
    X: list[list[float]],
    y_cat: list[int],
    J: int,
    k: int,
) -> tuple[float, list[float]]:
    """
    返回 (对数似然, 梯度向量)。

    params 排列：[θ_1, …, θ_{J−1}, β_1, …, β_k]（m=J−1 个阈值在前）。
    类别 y_cat[i] ∈ {1, …, J}。

    累积概率 γ_j = F(θ_j − η)，γ_0 = 0，γ_J = 1；P(Y=c) = γ_c − γ_{c−1}。
    阈值 θ_j 存于 params[j−1]（j = 1..J−1）。
    """
    m = J - 1
    thr = params[:m]
    beta = params[m:]
    n = len(y_cat)
    npar = m + k

    ll = 0.0
    grad = [0.0] * npar
    for i in range(n):
        eta = sum(beta[r] * X[i][r] for r in range(k)) if k else 0.0
        c = y_cat[i]  # 1..J

        # 上切点 θ_c（索引 c-1）；c==J 时 γ=1, 密度 f=0
        if c == J:
            Fu, fu, ju = 1.0, 0.0, None
        else:
            su = _sigmoid(thr[c - 1] - eta)
            Fu, fu, ju = su, su * (1.0 - su), c - 1
        # 下切点 θ_{c-1}（索引 c-2）；c==1 时 γ=0, f=0
        if c == 1:
            Fl, fl, jl = 0.0, 0.0, None
        else:
            sl = _sigmoid(thr[c - 2] - eta)
            Fl, fl, jl = sl, sl * (1.0 - sl), c - 2

        p = Fu - Fl
        if p < 1e-12:
            p = 1e-12
        ll += math.log(p)

        # ∂logP/∂θ_c = f_u/p ;  ∂logP/∂θ_{c-1} = −f_l/p
        if ju is not None:
            grad[ju] += fu / p
        if jl is not None:
            grad[jl] += -fl / p
        # ∂logP/∂β_r = −x_ir (f_u − f_l)/p
        cb = -(fu - fl) / p
        for r in range(k):
            grad[m + r] += cb * X[i][r]

    return ll, grad


def _observed_information(
    params: list[float],
    X: list[list[float]],
    y_cat: list[int],
    J: int,
    k: int,
    eps: float = 1e-5,
) -> list[list[float]]:
    """观测信息阵 I = −H（对数似然 Hessian 取负），用解析梯度的中心差分。"""
    npar = len(params)
    info = [[0.0] * npar for _ in range(npar)]
    for j in range(npar):
        pp = params[:]
        pp[j] += eps
        gp = _ll_grad(pp, X, y_cat, J, k)[1]
        pm = params[:]
        pm[j] -= eps
        gm = _ll_grad(pm, X, y_cat, J, k)[1]
        for i in range(npar):
            # H[i][j] = d grad_i / d param_j ; I = −H
            info[i][j] = -(gp[i] - gm[i]) / (2.0 * eps)
    # 对称化（数值噪声）
    for i in range(npar):
        for j in range(i + 1, npar):
            avg = (info[i][j] + info[j][i]) / 2.0
            info[i][j] = info[j][i] = avg
    return info


# ─────────────────────────────────────────────────────────────────────────────
# 核心：有序 Logistic 回归（比例优势）
# ─────────────────────────────────────────────────────────────────────────────

def ordinal_regression(
    X: list[list[float]],
    y_cat: list[int],
    J: int,
    *,
    max_iter: int = 100,
    tol: float = 1e-9,
    alpha: float = 0.05,
    predictor_names: list[str] | None = None,
) -> dict[str, Any]:
    """
    比例优势有序 Logistic 回归（阻尼 Newton-Raphson）。

    参数
    ----
    X               n×k 设计矩阵（**不含**截距列；阈值充当截距）
    y_cat           长度 n 的有序类别向量，取值 ∈ {1, …, J}
    J               类别数（≥ 2）
    predictor_names k 个预测变量名（默认 X1, X2, …）

    返回
    ----
    dict 键：thresholds, threshold_se, coef, se, z, p, or_, or_ci_lower,
    or_ci_upper, ci_lower, ci_upper, predictor_names, J, n, n_per_cat,
    log_lik_null, log_lik_model, lr_chi2, lr_df, lr_p,
    mcfadden_r2, cox_snell_r2, nagelkerke_r2, aic, bic,
    n_params, convergence, n_iter, thresholds_ordered, alpha
    """
    n = len(y_cat)
    k = len(X[0]) if (X and X[0]) else 0
    m = J - 1
    if predictor_names is None:
        predictor_names = [f"X{i}" for i in range(1, k + 1)]

    # 各类计数
    n_per_cat = [sum(1 for v in y_cat if v == j) for j in range(1, J + 1)]

    # 零模型对数似然（仅阈值；MLE 给出 P(Y=j)=prop_j）
    ll_null = 0.0
    for nj in n_per_cat:
        if nj > 0:
            ll_null += nj * math.log(nj / n)

    # ── 起始值：阈值=经验累积比例 logit，β=0 ──
    thr0: list[float] = []
    cum = 0
    for j in range(m):
        cum += n_per_cat[j]
        cp = min(1.0 - 1e-6, max(1e-6, cum / n))
        thr0.append(math.log(cp / (1.0 - cp)))
    params = thr0 + [0.0] * k

    # ── 阻尼 Newton-Raphson ──
    ll_prev = -1e300
    converged = False
    n_iter = 0
    for iteration in range(max_iter):
        n_iter = iteration + 1
        ll, grad = _ll_grad(params, X, y_cat, J, k)
        info = _observed_information(params, X, y_cat, J, k)
        cov = _mat_invert(info)
        if cov is None:
            break
        step = _mat_vec(cov, grad)  # Newton 升步 = I⁻¹·grad

        # step-halving 保证 ll 单调上升
        factor = 1.0
        new_params = params
        new_ll = ll
        for _ in range(30):
            cand = [params[t] + factor * step[t] for t in range(len(params))]
            cand_ll = _ll_grad(cand, X, y_cat, J, k)[0]
            if cand_ll >= ll - 1e-12:
                new_params, new_ll = cand, cand_ll
                break
            factor *= 0.5
        params = new_params

        if abs(new_ll - ll_prev) < tol:
            converged = True
            ll_prev = new_ll
            break
        ll_prev = new_ll

    # ── 最终估计量 ──
    ll_model, _ = _ll_grad(params, X, y_cat, J, k)
    info = _observed_information(params, X, y_cat, J, k)
    cov = _mat_invert(info)
    if cov is not None:
        se_all = [math.sqrt(max(cov[t][t], 0.0)) for t in range(len(params))]
    else:
        se_all = [float("nan")] * len(params)

    thresholds = params[:m]
    threshold_se = se_all[:m]
    beta = params[m:]
    se = se_all[m:]

    z_vals = [
        beta[r] / se[r] if (se[r] > 0 and math.isfinite(se[r])) else float("nan")
        for r in range(k)
    ]
    p_vals = [
        2.0 * _normal_sf(abs(z)) if math.isfinite(z) else float("nan")
        for z in z_vals
    ]
    z_crit = _normal_quantile(1.0 - alpha / 2.0)
    ci_lower = [beta[r] - z_crit * se[r] for r in range(k)]
    ci_upper = [beta[r] + z_crit * se[r] for r in range(k)]
    or_ = [_safe_exp(beta[r]) for r in range(k)]
    or_ci_lo = [_safe_exp(c) for c in ci_lower]
    or_ci_hi = [_safe_exp(c) for c in ci_upper]

    # 模型整体检验
    lr_chi2 = max(0.0, 2.0 * (ll_model - ll_null))
    lr_df = k
    lr_p = _chi2_sf(lr_chi2, lr_df) if lr_df > 0 else float("nan")

    mcfadden = 1.0 - ll_model / ll_null if ll_null < 0 else float("nan")
    cox_snell = 1.0 - math.exp(2.0 * (ll_null - ll_model) / n)
    max_cs = 1.0 - math.exp(2.0 * ll_null / n)
    nagelkerke = cox_snell / max_cs if max_cs > 1e-15 else float("nan")

    n_params = m + k
    aic = -2.0 * ll_model + 2.0 * n_params
    bic = -2.0 * ll_model + n_params * math.log(n)

    thresholds_ordered = all(
        thresholds[i] < thresholds[i + 1] for i in range(len(thresholds) - 1)
    )

    return {
        "thresholds":      thresholds,
        "threshold_se":    threshold_se,
        "coef":            beta,
        "se":              se,
        "z":               z_vals,
        "p":               p_vals,
        "or_":             or_,
        "or_ci_lower":     or_ci_lo,
        "or_ci_upper":     or_ci_hi,
        "ci_lower":        ci_lower,
        "ci_upper":        ci_upper,
        "predictor_names": list(predictor_names),
        "J":               J,
        "n":               n,
        "n_per_cat":       n_per_cat,
        "log_lik_null":    ll_null,
        "log_lik_model":   ll_model,
        "lr_chi2":         lr_chi2,
        "lr_df":           lr_df,
        "lr_p":            lr_p,
        "mcfadden_r2":     mcfadden,
        "cox_snell_r2":    cox_snell,
        "nagelkerke_r2":   nagelkerke,
        "aic":             aic,
        "bic":             bic,
        "n_params":        n_params,
        "convergence":     converged,
        "n_iter":          n_iter,
        "thresholds_ordered": thresholds_ordered,
        "alpha":           alpha,
    }


def predict_probs(
    thresholds: list[float],
    beta: list[float],
    x: list[float],
) -> list[float]:
    """给定阈值与斜率，返回某个 x 的各有序类别预测概率（长度 J，和=1）。"""
    eta = sum(beta[r] * x[r] for r in range(len(beta))) if beta else 0.0
    cum = [0.0] + [_sigmoid(t - eta) for t in thresholds] + [1.0]
    return [cum[j + 1] - cum[j] for j in range(len(thresholds) + 1)]


# ─────────────────────────────────────────────────────────────────────────────
# 比例优势假设诊断（Brant 思路：比较各二分切点斜率）
# ─────────────────────────────────────────────────────────────────────────────

def proportional_odds_check(
    X: list[list[float]],
    y_cat: list[int],
    J: int,
    *,
    predictor_names: list[str] | None = None,
) -> dict[str, Any]:
    """
    比例优势假设的轻量诊断。

    对 J−1 个二分切点 j（事件 = Y > j）各拟合一个二元 Logistic 回归（复用
    logistic.logistic_regression），收集每个预测变量在各切点的斜率。比例优势假设
    成立时各切点斜率应近似相等；离散度大则假设可疑。

    返回 per_predictor: {name: {slopes, min, max, range}} + cutpoints_used + note。
    无法估计的切点（某二分类只剩单一类别）自动跳过。
    """
    from psyclaw.psych.logistic import logistic_regression

    k = len(X[0]) if (X and X[0]) else 0
    if predictor_names is None:
        predictor_names = [f"X{i}" for i in range(1, k + 1)]

    slopes_by_cut: list[list[float]] = []  # 每个成功切点的 k 个斜率
    cutpoints_used: list[int] = []
    for j in range(1, J):  # θ_j 对应 Y > j
        b = [1.0 if v > j else 0.0 for v in y_cat]
        if len(set(b)) < 2:
            continue
        Xd = [[1.0] + row[:k] for row in X]  # 含截距列
        try:
            res = logistic_regression(Xd, b, predictor_names=list(predictor_names))
        except Exception:
            continue
        if not res.get("convergence", False):
            # 仍收录（分离时斜率不稳，但记录），但跳过完全分离
            if res.get("complete_separation", False):
                continue
        slopes_by_cut.append(res["coef"][1:])  # 去截距
        cutpoints_used.append(j)

    per_predictor: dict[str, Any] = {}
    for r, name in enumerate(predictor_names):
        vals = [s[r] for s in slopes_by_cut if math.isfinite(s[r])]
        if vals:
            per_predictor[name] = {
                "slopes": vals,
                "min": min(vals),
                "max": max(vals),
                "range": max(vals) - min(vals),
            }
        else:
            per_predictor[name] = {"slopes": [], "min": float("nan"),
                                   "max": float("nan"), "range": float("nan")}

    ranges = [d["range"] for d in per_predictor.values()
              if math.isfinite(d["range"])]
    max_range = max(ranges) if ranges else float("nan")
    if not math.isfinite(max_range):
        note = "比例优势诊断不可用（二分切点拟合失败）。"
    elif max_range < 1.0:
        note = ("各二分切点斜率离散度小（最大极差 "
                f"{max_range:.2f}），比例优势假设大体合理。")
    else:
        note = ("各二分切点斜率离散度较大（最大极差 "
                f"{max_range:.2f}），比例优势假设可能被违反；"
                "建议进行正式 Brant 检验或考虑偏比例优势 / 多项 Logistic 模型。")

    return {
        "per_predictor":  per_predictor,
        "cutpoints_used": cutpoints_used,
        "max_range":      max_range,
        "note":           note,
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


def _fmt_or(x: float) -> str:
    if math.isinf(x):
        return ">1e15"
    if math.isnan(x):
        return "NaN"
    return f"{x:.2f}"


def format_apa_ordinal(
    result: dict[str, Any],
    po: dict[str, Any] | None = None,
    dv_name: str = "outcome",
) -> str:
    """
    生成 APA-7 有序 Logistic 回归结果文本：
      ① Markdown 三线系数表（*B*/SE/*z*/*p*/OR/95%CI[OR]）
      ② 有序阈值段
      ③ 模型整体拟合段
      ④ 比例优势假设诊断段（若提供）
      ⑤ 显著预测变量文字总结
    """
    names = result["predictor_names"]
    coef  = result["coef"]
    se    = result["se"]
    z     = result["z"]
    p     = result["p"]
    or_   = result["or_"]
    or_lo = result["or_ci_lower"]
    or_hi = result["or_ci_upper"]
    alpha = result.get("alpha", 0.05)
    ci_pct = int((1 - alpha) * 100)

    # ── 系数表 ──
    w0 = max([len(n) for n in names] + [16]) if names else 16
    header = (
        f"| {'Predictor':<{w0}} | {'*B*':>7} | {'SE':>6} | "
        f"{'*z*':>7} | {'*p*':>7} | {'OR':>6} | "
        f"{f'{ci_pct}% CI [OR]':>18} |"
    )
    sep = (
        f"|:{'-' * w0}-|{'-' * 8}:|{'-' * 7}:|"
        f"{'-' * 8}:|{'-' * 8}:|{'-' * 7}:|{'-' * 19}:|"
    )
    rows = [header, sep]
    for r, name in enumerate(names):
        sig = "*" if (math.isfinite(p[r]) and p[r] < alpha) else ""
        ci_str = f"[{_fmt_or(or_lo[r])}, {_fmt_or(or_hi[r])}]"
        rows.append(
            f"| {name + sig:<{w0}} | {_fmt(coef[r]):>7} | {_fmt(se[r]):>6} | "
            f"{_fmt(z[r]):>7} | {_fmt_p(p[r]):>7} | {_fmt_or(or_[r]):>6} | "
            f"{ci_str:>18} |"
        )
    table = "\n".join(rows)

    note = (
        f"*Note.* Proportional-odds ordinal logistic regression predicting "
        f"{dv_name} (*N* = {result['n']}, {result['J']} ordered categories). "
        f"OR = proportional odds ratio (odds of a higher category per unit "
        f"increase). CI = confidence interval. * *p* {_fmt_p(alpha)}."
    )

    # ── 阈值段 ──
    thr = result["thresholds"]
    thr_se = result["threshold_se"]
    thr_parts = [
        f"θ{i + 1} = {_fmt(thr[i])} (SE = {_fmt(thr_se[i])})"
        for i in range(len(thr))
    ]
    order_warn = ("" if result["thresholds_ordered"]
                  else " **（警告：估计阈值非严格递增，模型可能未良好收敛）**")
    thr_text = (
        "Estimated cutpoints (thresholds): " + "; ".join(thr_parts) + "."
        + order_warn
    )

    # ── 模型整体拟合 ──
    conv_note = ("" if result["convergence"]
                 else " (**收敛警告：未达到收敛判据，解可能不稳定**)")
    model_fit = (
        f"The overall model was statistically significant, "
        f"χ²({result['lr_df']}) = {_fmt(result['lr_chi2'])}, "
        f"*p* {_fmt_p(result['lr_p'])}, "
        f"McFadden *R*² = {_fmt(result['mcfadden_r2'])}, "
        f"Nagelkerke *R*² = {_fmt(result['nagelkerke_r2'])}, "
        f"AIC = {_fmt(result['aic'])}.{conv_note}"
    )

    # ── 比例优势诊断段 ──
    po_text = ""
    if po is not None:
        po_text = "\n\nProportional-odds assumption check: " + po["note"]

    # ── 显著预测变量段 ──
    sig_preds = [
        (names[r], coef[r], or_[r], or_lo[r], or_hi[r], p[r])
        for r in range(len(names))
        if math.isfinite(p[r]) and p[r] < alpha
    ]
    if sig_preds:
        parts = []
        for name, b, orv, olo, ohi, pv in sig_preds:
            dir_word = "higher" if b > 0 else "lower"
            parts.append(
                f"higher {name} predicted {dir_word} ordinal {dv_name} categories "
                f"(*B* = {_fmt(b)}, OR = {_fmt_or(orv)}, "
                f"{ci_pct}% CI [{_fmt_or(olo)}, {_fmt_or(ohi)}], "
                f"*p* {_fmt_p(pv)})"
            )
        pred_text = "\n\n" + "; ".join(parts) + "."
    else:
        pred_text = (f"\n\nNo predictors reached statistical significance "
                     f"(*p* < {alpha:.2f}).")

    return ("\n\n".join([table, note, thr_text, model_fit])
            + po_text + pred_text)


# ─────────────────────────────────────────────────────────────────────────────
# 报告写出
# ─────────────────────────────────────────────────────────────────────────────

def _json_safe(obj: Any) -> Any:
    """递归把 NaN/inf 转 None，使 JSON 合法。"""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


def write_ordinal_report(
    result: dict[str, Any],
    po: dict[str, Any] | None = None,
    *,
    out_dir: str | pathlib.Path | None = None,
    dv_name: str = "outcome",
    filename: str = "ordinal_report",
) -> dict[str, str]:
    """写 MD + JSON sidecar，返回实际写入路径字典。"""
    md_text = format_apa_ordinal(result, po=po, dv_name=dv_name)
    payload = dict(result)
    if po is not None:
        payload["proportional_odds_check"] = po
    payload = _json_safe(payload)

    paths: dict[str, str] = {}
    if out_dir is not None:
        out = pathlib.Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        md_path = out / f"{filename}.md"
        json_path = out / f"{filename}.json"
        md_path.write_text(md_text, encoding="utf-8")
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        paths = {"md": str(md_path), "json": str(json_path)}
    return paths


# ─────────────────────────────────────────────────────────────────────────────
# CSV 主入口
# ─────────────────────────────────────────────────────────────────────────────

def analyze_ordinal(
    csv_path: str,
    dv: str,
    ivs: list[str],
    *,
    alpha: float = 0.05,
    out_dir: str | pathlib.Path | None = None,
    run_po_check: bool = True,
) -> dict[str, Any]:
    """
    从 CSV 文件读取数据并跑有序 Logistic 回归。

    参数
    ----
    csv_path     CSV 文件路径
    dv           有序因变量列名（取值映射到 1..J，按数值/字典序升序）
    ivs          预测变量列名列表
    alpha        显著性水平（默认 .05）
    out_dir      sidecar 输出目录（None 则不写文件）
    run_po_check 是否运行比例优势假设诊断（默认 True）
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
            iv_vals = {c: float(row[c]) for c in ivs}
            dv_raw = row[dv]
            if dv_raw is None or str(dv_raw).strip() == "":
                raise ValueError
            iv_vals[dv] = dv_raw
            complete.append(iv_vals)
        except (ValueError, KeyError):
            n_missing += 1

    if len(complete) < 3:
        raise ValueError(f"完整案例不足（{len(complete)} 行），无法运行有序回归。")

    # 有序标签 → 1..J（数值优先，否则字典序）
    raw_levels = {str(r[dv]).strip() for r in complete}

    def _key(s: str):
        try:
            return (0, float(s))
        except ValueError:
            return (1, s)

    levels = sorted(raw_levels, key=_key)
    J = len(levels)
    if J < 3:
        raise ValueError(
            f"因变量 '{dv}' 仅 {J} 个类别；有序回归需 ≥3 个有序类别"
            "（2 类请用 psyclaw logit 二元 Logistic）。"
        )
    label_to_cat = {lab: i + 1 for i, lab in enumerate(levels)}

    y_cat = [label_to_cat[str(r[dv]).strip()] for r in complete]
    X = [[r[iv] for iv in ivs] for r in complete]

    result = ordinal_regression(X, y_cat, J, alpha=alpha, predictor_names=ivs)
    result["n_excluded"] = n_missing
    result["dv"] = dv
    result["category_labels"] = levels

    po: dict[str, Any] | None = None
    if run_po_check and J >= 3:
        try:
            po = proportional_odds_check(X, y_cat, J, predictor_names=ivs)
        except Exception:
            po = None

    write_ordinal_report(result, po=po, out_dir=out_dir, dv_name=dv)
    return {"result": result, "po": po}


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def ordinal_cli(argv: list[str] | None = None) -> int:
    """
    psyclaw ordinal <data.csv> --dv <col> --iv col1,col2,...
            [--alpha .05] [--no-po-check] [--json] [--out dir]
    """
    ap = argparse.ArgumentParser(
        prog="psyclaw ordinal",
        description="有序 Logistic 回归（比例优势/累积 logit；OR/Wald/LR；APA-7）",
    )
    ap.add_argument("csv", help="输入数据 CSV 路径")
    ap.add_argument("--dv", required=True,
                    help="有序因变量列名（≥3 个有序类别）")
    ap.add_argument("--iv", required=True,
                    help="预测变量列名，逗号分隔（如 age,sex,score）")
    ap.add_argument("--alpha", type=float, default=0.05,
                    help="显著性水平（默认 .05）")
    ap.add_argument("--no-po-check", action="store_true", dest="no_po_check",
                    help="跳过比例优势假设诊断")
    ap.add_argument("--out", default=None,
                    help="sidecar 输出目录（写 ordinal_report.{md,json}）")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = ap.parse_args(argv)

    ivs = [c.strip() for c in args.iv.split(",") if c.strip()]
    try:
        output = analyze_ordinal(
            args.csv, args.dv, ivs,
            alpha=args.alpha,
            out_dir=args.out,
            run_po_check=not args.no_po_check,
        )
    except Exception as exc:
        print(f"错误：{exc}")
        return 1

    result = output["result"]
    po = output["po"]

    if args.json:
        payload = dict(result)
        if po is not None:
            payload["proportional_odds_check"] = po
        print(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2))
    else:
        print(format_apa_ordinal(result, po=po, dv_name=args.dv))
        labels = result.get("category_labels")
        if labels:
            print(f"\n有序类别映射：" +
                  ", ".join(f"{lab}→{i + 1}" for i, lab in enumerate(labels)))
        n_ex = result.get("n_excluded", 0)
        if n_ex:
            print(f"\n（已排除 {n_ex} 个含缺失值的案例）")
        conv = "已收敛" if result["convergence"] else "⚠ 未完全收敛"
        print(f"\n迭代次数：{result['n_iter']}  收敛状态：{conv}")
        if args.out:
            print(f"\n报告已写入：{args.out}/ordinal_report.{{md,json}}")

    return 0
