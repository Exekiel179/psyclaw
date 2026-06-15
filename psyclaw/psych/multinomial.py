"""多项 Logistic 回归 — 基线类别 logit（无序多分类结局），Newton-Raphson，
OR/Wald/LR/伪 R²，APA-7，stdlib only。

与 logistic.py（二元）/ ordinal.py（有序）同构，填补**无序多分类结局**回归空白：
心理学常见无序多类别结局（诊断分组、依恋类型、选择类别、所属亚群），既非二元
亦无自然顺序，误用 OLS / 二元 Logistic（需两两塌缩，丢信息且不一致）均不当。

模型（基线类别 logit / baseline-category logit，Agresti 2013）：
  log(P(Y=j|x) / P(Y=ref|x)) = β_j′x,   j ∈ 非参照类别
  J−1 组系数向量 β_j（各含截距），参照类别系数恒为 0。
  softmax: P(Y=j)=exp(β_j′x)/(1+Σ_l exp(β_l′x))，P(Y=ref)=1/(1+Σ_l exp(β_l′x))。

提供：
  - multinomial_regression(X, y, ...)        → 各非参照类别 β/SE/z/p/OR/CI + 模型拟合
  - predict_probs(result, x_row)             → 给定 x 的各类别预测概率（和=1）
  - format_apa_multinomial(result)           → APA-7 Markdown 分类别系数表 + 段落
  - write_multinomial_report(result)         → MD + JSON sidecar
  - analyze_multinomial(csv_path, dv, ivs)   → CSV 主入口
  - multinomial_cli(argv)                    → CLI 入口

CLI:
  psyclaw multinom <data.csv> --dv <col> --iv col1,col2,...
          [--ref <label>] [--alpha .05] [--json] [--out dir]

理论依据：
  Agresti (2013) Categorical Data Analysis (3rd ed.), §8 (baseline-category logits).
  Hosmer, Lemeshow & Sturdivant (2013) Applied Logistic Regression (3rd ed.), §8.
  McFadden (1974); Nagelkerke (1991).
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

def _safe_exp(x: float) -> float:
    """math.exp clamped 防 OverflowError；分离数据 β→∞ 时触发。"""
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
# 核心：softmax + 对数似然 / 梯度 / 信息阵
# ─────────────────────────────────────────────────────────────────────────────

def _row_probs(
    x: list[float],
    beta: list[float],
    n_cat_nonref: int,
    k: int,
) -> tuple[list[float], float]:
    """
    给定 x 与堆叠系数 beta（长度 (J−1)·k），返回：
      - 各非参照类别概率 [p_0, …, p_{J−2}]
      - 参照类别概率 p_ref
    数值稳健 softmax（减去最大 η，参照类别 η=0）。
    """
    etas = [
        sum(x[m] * beta[c * k + m] for m in range(k))
        for c in range(n_cat_nonref)
    ]
    mx = max(0.0, max(etas) if etas else 0.0)
    denom = math.exp(0.0 - mx) + sum(_safe_exp(e - mx) for e in etas)
    p_nonref = [_safe_exp(e - mx) / denom for e in etas]
    p_ref = math.exp(0.0 - mx) / denom
    return p_nonref, p_ref


def _loglik(
    X: list[list[float]],
    targets: list[int],
    beta: list[float],
    n_cat_nonref: int,
    k: int,
) -> float:
    """
    多项 logit 对数似然。targets[i] = 非参照类别索引（0..J−2）或 −1（参照类别）。
    """
    n = len(X)
    ll = 0.0
    for i in range(n):
        etas = [
            sum(X[i][m] * beta[c * k + m] for m in range(k))
            for c in range(n_cat_nonref)
        ]
        mx = max(0.0, max(etas) if etas else 0.0)
        # log-sum-exp（含参照类别 η=0）
        lse = mx + math.log(
            math.exp(0.0 - mx) + sum(_safe_exp(e - mx) for e in etas)
        )
        t = targets[i]
        eta_obs = etas[t] if t >= 0 else 0.0
        ll += eta_obs - lse
    return ll


def multinomial_regression(
    X: list[list[float]],
    y: list[int],
    *,
    ref: int | None = None,
    max_iter: int = 200,
    tol: float = 1e-9,
    alpha: float = 0.05,
    predictor_names: list[str] | None = None,
) -> dict[str, Any]:
    """
    多项 Logistic 回归（基线类别 logit，Newton-Raphson + step-halving）。

    参数
    ----
    X              n×k 设计矩阵（**已含**第一列全为 1 的截距列）
    y              长度 n 的整数类别标签向量（任意整数，内部按升序排为 1..J）
    ref            参照类别标签（默认 = 最小标签）
    predictor_names  k−1 个预测变量名称（不含截距；默认 X1, X2, …）

    返回
    ----
    dict 键：
      categories（升序标签列表）, ref, nonref（非参照标签，与系数顺序一致）
      term_names（含截距）
      coef, se, z, p, or_, or_ci_lower, or_ci_upper, ci_lower, ci_upper
        —— 均为 {非参照标签: [k 个值]} 字典
      log_lik_null, log_lik_model, lr_chi2, lr_df, lr_p
      mcfadden_r2, cox_snell_r2, nagelkerke_r2, aic, bic
      n, n_per_cat（{标签: 计数}）, J, k, alpha
      convergence, complete_separation, n_iter, beta_flat
    """
    n = len(y)
    k = len(X[0])
    categories = sorted(set(y))
    J = len(categories)
    if J < 2:
        raise ValueError(f"因变量只有 {J} 个类别，无法估计多项模型（需 ≥ 2）。")

    if ref is None:
        ref = categories[0]
    if ref not in categories:
        raise ValueError(f"参照类别 {ref} 不在数据类别 {categories} 中。")

    nonref = [c for c in categories if c != ref]   # 非参照标签，固定顺序
    n_nr = len(nonref)                              # = J − 1
    nr_index = {lab: idx for idx, lab in enumerate(nonref)}
    targets = [nr_index.get(lab, -1) for lab in y]  # −1 表示参照类别

    if predictor_names is None:
        predictor_names = [f"X{i}" for i in range(1, k)]
    term_names = ["(Intercept)"] + list(predictor_names)

    n_per_cat = {c: y.count(c) for c in categories}

    # ── 零模型（仅截距）对数似然：MLE 给出 p_j = n_j / n ──
    ll_null = 0.0
    for c in categories:
        nj = n_per_cat[c]
        if nj > 0:
            ll_null += nj * math.log(nj / n)

    D = n_nr * k                       # 堆叠参数维度
    beta = [0.0] * D
    ll_prev = _loglik(X, targets, beta, n_nr, k)
    converged = False
    n_iter = 0

    for iteration in range(max_iter):
        n_iter = iteration + 1

        # 各观测的非参照类别概率
        P = []                          # P[i] = [p_i0, …, p_i,J−2]
        for i in range(n):
            p_nr, _ = _row_probs(X[i], beta, n_nr, k)
            P.append(p_nr)

        # 梯度（score）：block c 分量 m = Σ_i (y_ic − p_ic) X[i][m]
        score = [0.0] * D
        for i in range(n):
            t = targets[i]
            for c in range(n_nr):
                resid = (1.0 if t == c else 0.0) - P[i][c]
                base = c * k
                xi = X[i]
                for m in range(k):
                    score[base + m] += resid * xi[m]

        # 观测信息阵 I：block (c,d) 分量 (m,m') = Σ_i p_ic(δ_cd − p_id) X_im X_im'
        info = [[0.0] * D for _ in range(D)]
        for i in range(n):
            xi = X[i]
            pi = P[i]
            for c in range(n_nr):
                bc = c * k
                for d in range(n_nr):
                    bd = d * k
                    w = pi[c] * ((1.0 if c == d else 0.0) - pi[d])
                    if w == 0.0:
                        continue
                    for m in range(k):
                        wxm = w * xi[m]
                        rowc = info[bc + m]
                        for mp in range(k):
                            rowc[bd + mp] += wxm * xi[mp]

        inv = _mat_invert(info)
        if inv is None:
            break
        delta = _mat_vec(inv, score)

        # step-halving 保证对数似然单调上升
        step = 1.0
        ll_new = ll_prev
        for _ in range(40):
            cand = [beta[j] + step * delta[j] for j in range(D)]
            ll_cand = _loglik(X, targets, cand, n_nr, k)
            if ll_cand >= ll_prev - 1e-12:
                beta = cand
                ll_new = ll_cand
                break
            step *= 0.5
        else:
            # 无法上升，停止
            break

        if abs(ll_new - ll_prev) < tol:
            converged = True
            ll_prev = ll_new
            break
        ll_prev = ll_new

    ll_model = ll_prev

    # ── 最终信息阵 → SE ──
    P = []
    for i in range(n):
        p_nr, _ = _row_probs(X[i], beta, n_nr, k)
        P.append(p_nr)
    info = [[0.0] * D for _ in range(D)]
    for i in range(n):
        xi = X[i]
        pi = P[i]
        for c in range(n_nr):
            bc = c * k
            for d in range(n_nr):
                bd = d * k
                w = pi[c] * ((1.0 if c == d else 0.0) - pi[d])
                if w == 0.0:
                    continue
                for m in range(k):
                    wxm = w * xi[m]
                    rowc = info[bc + m]
                    for mp in range(k):
                        rowc[bd + mp] += wxm * xi[mp]
    inv = _mat_invert(info)
    se_flat = (
        [math.sqrt(max(inv[j][j], 0.0)) for j in range(D)]
        if inv is not None else [float("nan")] * D
    )

    z_crit = _normal_quantile(1.0 - alpha / 2.0)

    coef: dict[Any, list[float]] = {}
    se: dict[Any, list[float]] = {}
    z: dict[Any, list[float]] = {}
    p: dict[Any, list[float]] = {}
    or_: dict[Any, list[float]] = {}
    ci_lo: dict[Any, list[float]] = {}
    ci_hi: dict[Any, list[float]] = {}
    or_lo: dict[Any, list[float]] = {}
    or_hi: dict[Any, list[float]] = {}

    complete_separation = False
    for c, lab in enumerate(nonref):
        base = c * k
        b_c = [beta[base + m] for m in range(k)]
        s_c = [se_flat[base + m] for m in range(k)]
        zc = [
            b_c[m] / s_c[m] if (s_c[m] > 0 and math.isfinite(s_c[m]))
            else float("nan")
            for m in range(k)
        ]
        pc = [
            2.0 * _normal_sf(abs(v)) if math.isfinite(v) else float("nan")
            for v in zc
        ]
        clo = [b_c[m] - z_crit * s_c[m] for m in range(k)]
        chi = [b_c[m] + z_crit * s_c[m] for m in range(k)]
        oc = [_safe_exp(v) for v in b_c]
        olo = [_safe_exp(v) for v in clo]
        ohi = [_safe_exp(v) for v in chi]
        if any(math.isinf(v) for v in oc):
            complete_separation = True
        coef[lab], se[lab], z[lab], p[lab] = b_c, s_c, zc, pc
        ci_lo[lab], ci_hi[lab] = clo, chi
        or_[lab], or_lo[lab], or_hi[lab] = oc, olo, ohi

    lr_chi2 = max(0.0, 2.0 * (ll_model - ll_null))
    lr_df = n_nr * (k - 1)             # (J−1)·预测变量个数
    lr_p = _chi2_sf(lr_chi2, lr_df) if lr_df > 0 else float("nan")

    mcfadden = 1.0 - ll_model / ll_null if ll_null != 0.0 else float("nan")
    cox_snell = 1.0 - math.exp(-lr_chi2 / n)
    max_cs = 1.0 - math.exp(2.0 * ll_null / n)
    nagelkerke = cox_snell / max_cs if max_cs > 1e-15 else float("nan")

    aic = -2.0 * ll_model + 2.0 * D
    bic = -2.0 * ll_model + D * math.log(n)

    return {
        "categories":   categories,
        "ref":          ref,
        "nonref":       nonref,
        "term_names":   term_names,
        "predictor_names": list(predictor_names),
        "coef":         coef,
        "se":           se,
        "z":            z,
        "p":            p,
        "or_":          or_,
        "or_ci_lower":  or_lo,
        "or_ci_upper":  or_hi,
        "ci_lower":     ci_lo,
        "ci_upper":     ci_hi,
        "log_lik_null":  ll_null,
        "log_lik_model": ll_model,
        "lr_chi2":      lr_chi2,
        "lr_df":        lr_df,
        "lr_p":         lr_p,
        "mcfadden_r2":  mcfadden,
        "cox_snell_r2": cox_snell,
        "nagelkerke_r2": nagelkerke,
        "aic":          aic,
        "bic":          bic,
        "n":            n,
        "n_per_cat":    n_per_cat,
        "J":            J,
        "k":            k,
        "alpha":        alpha,
        "convergence":  converged,
        "complete_separation": complete_separation,
        "n_iter":       n_iter,
        "beta_flat":    beta,
    }


def predict_probs(result: dict[str, Any], x_row: list[float]) -> dict[Any, float]:
    """
    给定拟合结果与一行设计向量 x（含截距列），返回 {类别标签: 预测概率}（和=1）。
    """
    nonref = result["nonref"]
    ref = result["ref"]
    k = result["k"]
    beta = result["beta_flat"]
    p_nr, p_ref = _row_probs(x_row, beta, len(nonref), k)
    out = {lab: p_nr[c] for c, lab in enumerate(nonref)}
    out[ref] = p_ref
    return out


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


def format_apa_multinomial(
    result: dict[str, Any],
    dv_name: str = "outcome",
) -> str:
    """
    生成 APA-7 多项 Logistic 回归结果文本：
      ① 每个非参照类别一张 Markdown 三线系数表（*B*/SE/*z*/*p*/OR/95%CI[OR]）
      ② 模型整体拟合段落（LR/McFadden/Nagelkerke/AIC）
      ③ 显著预测变量文字总结（注明对比哪一类别 vs 参照）
    """
    names = result["term_names"]
    nonref = result["nonref"]
    ref = result["ref"]
    alpha = result.get("alpha", 0.05)
    ci_pct = int((1 - alpha) * 100)

    blocks = []
    for lab in nonref:
        coef = result["coef"][lab]
        se = result["se"][lab]
        z = result["z"][lab]
        p = result["p"][lab]
        or_ = result["or_"][lab]
        or_lo = result["or_ci_lower"][lab]
        or_hi = result["or_ci_upper"][lab]

        col_w = max(max((len(n) for n in names), default=10), 16)
        header = (
            f"| {'Predictor':<{col_w}} | {'*B*':>7} | {'SE':>6} | "
            f"{'*z*':>7} | {'*p*':>7} | {'OR':>6} | "
            f"{f'{ci_pct}% CI [OR]':>18} |"
        )
        sep = (
            f"|:{'-' * col_w}-|{'-' * 8}:|{'-' * 7}:|"
            f"{'-' * 8}:|{'-' * 8}:|{'-' * 7}:|{'-' * 19}:|"
        )
        rows = [
            f"**Category {lab} vs. reference ({ref})**",
            "",
            header,
            sep,
        ]
        for j, name in enumerate(names):
            sig = "*" if (math.isfinite(p[j]) and p[j] < alpha) else ""
            ci_str = f"[{_fmt_or(or_lo[j])}, {_fmt_or(or_hi[j])}]"
            rows.append(
                f"| {name + sig:<{col_w}} | {_fmt(coef[j]):>7} | {_fmt(se[j]):>6} | "
                f"{_fmt(z[j]):>7} | {_fmt_p(p[j]):>7} | {_fmt_or(or_[j]):>6} | "
                f"{ci_str:>18} |"
            )
        blocks.append("\n".join(rows))

    tables = "\n\n".join(blocks)

    cats_str = ", ".join(str(c) for c in result["categories"])
    note = (
        f"*Note.* Multinomial (baseline-category) logistic regression predicting "
        f"{dv_name} ({result['J']} categories: {cats_str}; reference = {ref}; "
        f"*N* = {result['n']}). OR = odds ratio. CI = confidence interval. "
        f"* *p* {_fmt_p(alpha)}."
    )

    conv_note = "" if result["convergence"] else " (**收敛警告：未达到收敛判据，解可能不稳定**)"
    sep_note = (
        " (**完全分离警告：某些 OR 发散，估计不可靠**)"
        if result.get("complete_separation") else ""
    )
    model_fit = (
        f"The overall model was statistically significant, "
        f"χ²({result['lr_df']}) = {_fmt(result['lr_chi2'])}, "
        f"*p* {_fmt_p(result['lr_p'])}, "
        f"McFadden *R*² = {_fmt(result['mcfadden_r2'])}, "
        f"Nagelkerke *R*² = {_fmt(result['nagelkerke_r2'])}, "
        f"AIC = {_fmt(result['aic'])}.{conv_note}{sep_note}"
    )

    # ── 显著预测变量段落 ──
    parts = []
    for lab in nonref:
        coef = result["coef"][lab]
        p = result["p"][lab]
        or_ = result["or_"][lab]
        or_lo = result["or_ci_lower"][lab]
        or_hi = result["or_ci_upper"][lab]
        for j in range(1, len(names)):           # 跳过截距
            if math.isfinite(p[j]) and p[j] < alpha:
                dir_word = "higher" if coef[j] > 0 else "lower"
                parts.append(
                    f"For category {lab} (vs. {ref}), {names[j]} was associated with "
                    f"{dir_word} odds (*B* = {_fmt(coef[j])}, OR = {_fmt_or(or_[j])}, "
                    f"{ci_pct}% CI [{_fmt_or(or_lo[j])}, {_fmt_or(or_hi[j])}], "
                    f"*p* {_fmt_p(p[j])})"
                )
    if parts:
        pred_text = "\n\n" + "; ".join(parts) + "."
    else:
        pred_text = f"\n\nNo predictors reached statistical significance (*p* < {alpha:.2f})."

    return "\n\n".join([tables, note, model_fit]) + pred_text


# ─────────────────────────────────────────────────────────────────────────────
# JSON 安全 + 报告写出
# ─────────────────────────────────────────────────────────────────────────────

def _json_safe(obj: Any) -> Any:
    """递归把 NaN/inf → None，使 JSON 合法。字典键转字符串。"""
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    return obj


def write_multinomial_report(
    result: dict[str, Any],
    *,
    out_dir: str | pathlib.Path | None = None,
    dv_name: str = "outcome",
    filename: str = "multinomial_report",
) -> dict[str, str]:
    """写 MD + JSON sidecar，返回实际写入路径字典。"""
    md_text = format_apa_multinomial(result, dv_name=dv_name)
    payload = _json_safe({k: v for k, v in result.items() if k != "beta_flat"})

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

def analyze_multinomial(
    csv_path: str,
    dv: str,
    ivs: list[str],
    *,
    ref: str | None = None,
    alpha: float = 0.05,
    out_dir: str | pathlib.Path | None = None,
) -> dict[str, Any]:
    """
    从 CSV 读取数据跑多项 Logistic 回归。

    因变量列含**无序多类别标签**（数值或字符串）；内部映射为整数 1..J：
    全为数值则按数值升序，否则按字典序。预测变量须为数值。缺失整行排除。

    参数
    ----
    csv_path  CSV 路径
    dv        无序多分类因变量列名（≥3 类）
    ivs       预测变量列名列表
    ref       参照类别原始标签字符串（默认 = 最小类别）
    """
    rows: list[dict] = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    complete: list[dict] = []
    n_missing = 0
    for row in rows:
        try:
            raw_dv = row[dv]
            if raw_dv is None or raw_dv == "":
                raise ValueError("missing dv")
            iv_vals = [float(row[iv]) for iv in ivs]
            complete.append({"dv": raw_dv, "iv": iv_vals})
        except (ValueError, KeyError):
            n_missing += 1

    if len(complete) < 2:
        raise ValueError(f"完整案例不足（{len(complete)} 行），无法运行多项回归。")

    raw_labels = [r["dv"] for r in complete]
    uniq = sorted(set(raw_labels))
    # 全数值 → 按数值排序
    try:
        numeric = {lab: float(lab) for lab in uniq}
        uniq_sorted = sorted(uniq, key=lambda l: numeric[l])
    except ValueError:
        uniq_sorted = uniq
    label_map = {lab: i + 1 for i, lab in enumerate(uniq_sorted)}   # 原始标签 → 1..J
    inv_label = {v: k for k, v in label_map.items()}

    J = len(uniq_sorted)
    if J < 3:
        raise ValueError(
            f"因变量 '{dv}' 只有 {J} 个类别。多项回归用于 ≥3 个无序类别；"
            "2 类请改用二元 Logistic（psyclaw logit）。"
        )

    y = [label_map[r["dv"]] for r in complete]
    X = [[1.0] + r["iv"] for r in complete]

    ref_int: int | None = None
    if ref is not None:
        if ref not in label_map:
            raise ValueError(
                f"参照类别 '{ref}' 不在数据类别 {uniq_sorted} 中。"
            )
        ref_int = label_map[ref]

    result = multinomial_regression(
        X, y,
        ref=ref_int,
        alpha=alpha,
        predictor_names=ivs,
    )
    # 把内部 1..J 标签还原为原始标签，便于阅读
    result["category_labels"] = {int(k): inv_label[k] for k in result["categories"]}
    result["ref_label"] = inv_label[result["ref"]]
    result["n_excluded"] = n_missing
    result["dv"] = dv

    write_multinomial_report(result, out_dir=out_dir, dv_name=dv)
    return {"result": result}


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def multinomial_cli(argv: list[str] | None = None) -> int:
    """
    psyclaw multinom <data.csv> --dv <col> --iv col1,col2,...
            [--ref <label>] [--alpha .05] [--json] [--out dir]
    """
    ap = argparse.ArgumentParser(
        prog="psyclaw multinom",
        description="多项 Logistic 回归（基线类别 logit；无序多分类结局；OR/Wald/LR；APA-7）",
    )
    ap.add_argument("csv", help="输入数据 CSV 路径")
    ap.add_argument("--dv",  required=True, help="无序多分类因变量列名（≥3 类）")
    ap.add_argument("--iv",  required=True,
                    help="预测变量列名，逗号分隔（如 age,sex,score）")
    ap.add_argument("--ref", default=None,
                    help="参照类别原始标签（默认 = 最小/首个类别）")
    ap.add_argument("--alpha", type=float, default=0.05, help="显著性水平（默认 .05）")
    ap.add_argument("--out",   default=None, help="sidecar 输出目录（默认不写文件）")
    ap.add_argument("--json",  action="store_true", help="输出机器可读 JSON")
    args = ap.parse_args(argv)

    ivs = [c.strip() for c in args.iv.split(",") if c.strip()]
    try:
        output = analyze_multinomial(
            args.csv, args.dv, ivs,
            ref=args.ref,
            alpha=args.alpha,
            out_dir=args.out,
        )
    except Exception as exc:
        print(f"错误：{exc}")
        return 1

    result = output["result"]
    if args.json:
        payload = _json_safe({k: v for k, v in result.items() if k != "beta_flat"})
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(format_apa_multinomial(result, dv_name=args.dv))
        n_ex = result.get("n_excluded", 0)
        if n_ex:
            print(f"\n（已排除 {n_ex} 个含缺失值的案例）")
        conv_status = "已收敛" if result["convergence"] else "⚠ 未完全收敛"
        print(f"\n迭代次数：{result['n_iter']}  收敛状态：{conv_status}")
        if args.out:
            print(f"\n报告已写入：{args.out}/multinomial_report.{{md,json}}")
    return 0
