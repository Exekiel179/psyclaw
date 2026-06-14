"""二元 Logistic 回归 — IRLS 算法，OR/Wald/LR/Hosmer-Lemeshow，APA-7，stdlib only。

提供：
  - logistic_regression(X, y, ...)          → β/SE/z/p/OR/CI/R²/LR
  - hosmer_lemeshow(y_obs, y_pred, g=10)    → HL χ²/df/p
  - format_apa_logistic(result)             → APA-7 Markdown 表格 + 段落
  - write_logistic_report(result)           → MD + JSON sidecar
  - analyze_logistic(csv_path, dv, ivs)     → CSV 主入口
  - logistic_cli(argv)                      → CLI 入口

CLI:
  psyclaw logit <data.csv> --dv <col> --iv col1,col2,...
          [--alpha .05] [--json] [--out dir]

理论依据：
  Hosmer & Lemeshow (2000) Applied Logistic Regression (2nd ed.).
  Nagelkerke (1991). A note on a general definition of the coefficient of determination.
  Biometrika, 78(3), 691–692.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# 矩阵工具（Gauss-Jordan，stdlib only，与 regression.py 同款）
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

def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def _safe_exp(x: float) -> float:
    """math.exp clamped to avoid OverflowError；分离数据时 beta→∞ 会触发。"""
    if x > 709.0:
        return math.inf
    if x < -709.0:
        return 0.0
    return math.exp(x)


def _log_sigmoid(x: float) -> float:
    if x >= 0:
        return -math.log1p(math.exp(-x))
    return x - math.log1p(math.exp(x))


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
# 核心：IRLS Logistic 回归
# ─────────────────────────────────────────────────────────────────────────────

def logistic_regression(
    X: list[list[float]],
    y: list[float],
    *,
    max_iter: int = 200,
    tol: float = 1e-8,
    alpha: float = 0.05,
    predictor_names: list[str] | None = None,
) -> dict[str, Any]:
    """
    二元 Logistic 回归（IRLS = Newton-Raphson 精确 Hessian）。

    参数
    ----
    X              n×k 设计矩阵（**已含**第一列全为 1 的截距列）
    y              长度 n 的二元响应向量（0 / 1）
    predictor_names  k-1 个预测变量名称（不含截距；默认 X1, X2, …）

    返回
    ----
    dict 键：
      term_names, predictor_names
      coef, se, z, p, or_, or_ci_lower, or_ci_upper, ci_lower, ci_upper
      log_lik_null, log_lik_model, lr_chi2, lr_df, lr_p
      cox_snell_r2, nagelkerke_r2
      n, n_pos, n_neg, alpha
      convergence, n_iter, mu（各观测预测概率，供 HL 检验用）
    """
    n = len(y)
    k = len(X[0])

    if predictor_names is None:
        predictor_names = [f"X{i}" for i in range(1, k)]
    term_names = ["(Intercept)"] + list(predictor_names)

    # 零模型对数似然（仅截距）
    p_null = max(1e-15, min(1.0 - 1e-15, sum(y) / n))
    ll_null = sum(y) * math.log(p_null) + (n - sum(y)) * math.log(1.0 - p_null)

    # ── IRLS ──────────────────────────────────────────────────────────────────
    beta = [0.0] * k
    ll_prev = -1e300
    converged = False
    n_iter = 0

    for iteration in range(max_iter):
        n_iter = iteration + 1
        eta = [sum(X[i][j] * beta[j] for j in range(k)) for i in range(n)]
        mu  = [_sigmoid(e) for e in eta]
        w   = [max(m * (1.0 - m), 1e-10) for m in mu]

        ll = sum(
            y[i] * _log_sigmoid(eta[i]) + (1.0 - y[i]) * _log_sigmoid(-eta[i])
            for i in range(n)
        )

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
    mu  = [_sigmoid(e) for e in eta]
    w   = [max(m * (1.0 - m), 1e-10) for m in mu]

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

    ll_model = sum(
        y[i] * _log_sigmoid(eta[i]) + (1.0 - y[i]) * _log_sigmoid(-eta[i])
        for i in range(n)
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
    or_      = [_safe_exp(beta[j]) for j in range(k)]
    or_ci_lo = [_safe_exp(c) for c in ci_lower]
    or_ci_hi = [_safe_exp(c) for c in ci_upper]

    # 完全分离检测（任意 OR = ∞ 是强烈信号）
    complete_separation = any(math.isinf(o) for o in or_)

    lr_chi2 = max(0.0, 2.0 * (ll_model - ll_null))
    lr_df   = k - 1  # 预测变量个数（不含截距）
    lr_p    = _chi2_sf(lr_chi2, lr_df) if lr_df > 0 else float("nan")

    cox_snell = 1.0 - math.exp(-lr_chi2 / n)
    max_cs    = 1.0 - math.exp(2.0 * ll_null / n)
    nagelkerke = cox_snell / max_cs if max_cs > 1e-15 else float("nan")

    return {
        "term_names":    term_names,
        "predictor_names": list(predictor_names),
        "coef":          beta,
        "se":            se_list,
        "z":             z_vals,
        "p":             p_vals,
        "or_":           or_,
        "or_ci_lower":   or_ci_lo,
        "or_ci_upper":   or_ci_hi,
        "ci_lower":      ci_lower,
        "ci_upper":      ci_upper,
        "log_lik_null":  ll_null,
        "log_lik_model": ll_model,
        "lr_chi2":       lr_chi2,
        "lr_df":         lr_df,
        "lr_p":          lr_p,
        "cox_snell_r2":  cox_snell,
        "nagelkerke_r2": nagelkerke,
        "n":             n,
        "n_pos":         int(sum(y)),
        "n_neg":         n - int(sum(y)),
        "alpha":         alpha,
        "convergence":        converged,
        "complete_separation": complete_separation,
        "n_iter":             n_iter,
        "mu":                 mu,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Hosmer-Lemeshow 拟合优度检验
# ─────────────────────────────────────────────────────────────────────────────

def hosmer_lemeshow(
    y_obs: list[float],
    y_pred: list[float],
    g: int = 10,
) -> dict[str, Any]:
    """
    Hosmer-Lemeshow 拟合优度检验（按预测概率 g 十分位分组）。

    HL 统计量 ~ χ²(g-2)；p > .05 表示拟合可接受。
    推荐 g=10（Hosmer & Lemeshow, 2000, p. 147）。
    """
    n = len(y_obs)
    if n < g:
        g = max(2, n)

    # 按预测概率排序
    pairs = sorted(zip(y_pred, y_obs), key=lambda t: t[0])

    # 均匀分成 g 组
    hl_stat = 0.0
    groups = []
    for g_idx in range(g):
        lo = g_idx * n // g
        hi = (g_idx + 1) * n // g
        if g_idx == g - 1:
            hi = n
        chunk = pairs[lo:hi]
        ng   = len(chunk)
        o1   = sum(obs for _, obs in chunk)
        e1   = sum(pred for pred, _ in chunk)
        o0   = ng - o1
        e0   = ng - e1
        denom1 = e1 if e1 > 1e-10 else 1e-10
        denom0 = e0 if e0 > 1e-10 else 1e-10
        hl_stat += (o1 - e1) ** 2 / denom1 + (o0 - e0) ** 2 / denom0
        groups.append({"n": ng, "o1": o1, "e1": round(e1, 4),
                       "o0": o0, "e0": round(e0, 4)})

    df  = g - 2
    p   = _chi2_sf(hl_stat, df) if df > 0 else float("nan")
    return {"hl_chi2": hl_stat, "hl_df": df, "hl_p": p, "g": g, "groups": groups}


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


def format_apa_logistic(
    result: dict[str, Any],
    hl: dict[str, Any] | None = None,
    dv_name: str = "outcome",
) -> str:
    """
    生成 APA-7 Logistic 回归结果文本：
      ① Markdown 三线系数表（*B*/SE/*z*/*p*/OR/95%CI[OR]）
      ② 模型整体拟合段落
      ③ 显著预测变量文字总结
      ④ Hosmer-Lemeshow 拟合优度（若提供）
    """
    names = result["term_names"]
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
    col_w = [max(len(n), 16) for n in names]
    header = (
        f"| {'Predictor':<{col_w[0]}} | {'*B*':>7} | {'SE':>6} | "
        f"{'*z*':>7} | {'*p*':>7} | {'OR':>6} | "
        f"{f'{ci_pct}% CI [OR]':>18} |"
    )
    sep = (
        f"|:{'-' * col_w[0]}-|{'-' * 8}:|{'-' * 7}:|"
        f"{'-' * 8}:|{'-' * 8}:|{'-' * 7}:|{'-' * 19}:|"
    )
    rows = [header, sep]
    for j, name in enumerate(names):
        sig = "*" if (math.isfinite(p[j]) and p[j] < alpha) else ""
        p_str = _fmt_p(p[j])
        ci_str = f"[{_fmt_or(or_lo[j])}, {_fmt_or(or_hi[j])}]"
        rows.append(
            f"| {name + sig:<{col_w[0]}} | {_fmt(coef[j]):>7} | {_fmt(se[j]):>6} | "
            f"{_fmt(z[j]):>7} | {p_str:>7} | {_fmt_or(or_[j]):>6} | "
            f"{ci_str:>18} |"
        )

    table = "\n".join(rows)
    note = (
        f"*Note.* Logistic regression predicting {dv_name} "
        f"(*N* = {result['n']}, {result['n_pos']} events). "
        f"OR = odds ratio. CI = confidence interval. "
        f"* *p* {_fmt_p(alpha)}."
    )

    # ── 模型整体拟合 ──
    conv_note = "" if result["convergence"] else " (**收敛警告：未达到收敛判据，解可能不稳定**)"
    model_fit = (
        f"The overall model was statistically significant, "
        f"χ²({result['lr_df']}) = {_fmt(result['lr_chi2'])}, "
        f"*p* {_fmt_p(result['lr_p'])}, "
        f"Nagelkerke *R*² = {_fmt(result['nagelkerke_r2'])}, "
        f"Cox–Snell *R*² = {_fmt(result['cox_snell_r2'])}.{conv_note}"
    )

    # ── HL 拟合优度 ──
    hl_text = ""
    if hl is not None:
        hl_text = (
            f"\n\nHosmer–Lemeshow goodness-of-fit test indicated "
            f"{'acceptable' if hl['hl_p'] > .05 else 'poor'} model fit, "
            f"χ²({hl['hl_df']}) = {_fmt(hl['hl_chi2'])}, "
            f"*p* {_fmt_p(hl['hl_p'])}."
        )

    # ── 显著预测变量段落 ──
    sig_preds = [
        (names[j], coef[j], or_[j], or_lo[j], or_hi[j], p[j])
        for j in range(1, len(names))  # 跳过截距
        if math.isfinite(p[j]) and p[j] < alpha
    ]
    if sig_preds:
        parts = []
        for name, b, orv, olo, ohi, pv in sig_preds:
            dir_word = "positively" if b > 0 else "negatively"
            parts.append(
                f"{name} {dir_word} predicted {dv_name} "
                f"(*B* = {_fmt(b)}, OR = {_fmt_or(orv)}, "
                f"{ci_pct}% CI [{_fmt_or(olo)}, {_fmt_or(ohi)}], "
                f"*p* {_fmt_p(pv)})"
            )
        pred_text = "\n\n" + "; ".join(parts) + "."
    else:
        pred_text = f"\n\nNo predictors reached statistical significance (*p* < {alpha:.2f})."

    return "\n\n".join([table, note, model_fit]) + hl_text + pred_text


# ─────────────────────────────────────────────────────────────────────────────
# 报告写出
# ─────────────────────────────────────────────────────────────────────────────

def write_logistic_report(
    result: dict[str, Any],
    hl: dict[str, Any] | None = None,
    *,
    out_dir: str | pathlib.Path | None = None,
    dv_name: str = "outcome",
    filename: str = "logistic_report",
) -> dict[str, str]:
    """写 MD + JSON sidecar，返回实际写入路径字典。"""
    md_text  = format_apa_logistic(result, hl=hl, dv_name=dv_name)
    payload  = {k: v for k, v in result.items() if k != "mu"}
    if hl is not None:
        payload["hosmer_lemeshow"] = hl

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

def analyze_logistic(
    csv_path: str,
    dv: str,
    ivs: list[str],
    *,
    alpha: float = 0.05,
    out_dir: str | pathlib.Path | None = None,
    run_hl: bool = True,
) -> dict[str, Any]:
    """
    从 CSV 文件读取数据并跑 Logistic 回归。

    参数
    ----
    csv_path  CSV 文件路径
    dv        因变量列名（必须为 0/1 二元编码）
    ivs       预测变量列名列表
    alpha     显著性水平（默认 .05）
    out_dir   sidecar 输出目录（None 则不写文件）
    run_hl    是否运行 Hosmer-Lemeshow 检验（默认 True）
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
        raise ValueError(f"完整案例不足（{len(complete)} 行），无法运行 Logistic 回归。")

    y_vals = [r[dv] for r in complete]
    unique_y = set(y_vals)
    if unique_y - {0.0, 1.0}:
        raise ValueError(
            f"因变量 '{dv}' 含非 0/1 值 {unique_y - {0.0, 1.0}}，"
            "Logistic 回归要求二元 0/1 编码。"
        )
    if len(unique_y) < 2:
        raise ValueError(f"因变量 '{dv}' 只有一个类别，无法估计模型。")

    # 构建设计矩阵（含截距列）
    X = [[1.0] + [r[iv] for iv in ivs] for r in complete]
    y = y_vals

    result = logistic_regression(
        X, y,
        alpha=alpha,
        predictor_names=ivs,
    )
    result["n_excluded"] = n_missing
    result["dv"] = dv

    hl: dict[str, Any] | None = None
    if run_hl and len(complete) >= 20:
        hl = hosmer_lemeshow(y, result["mu"])

    write_logistic_report(result, hl=hl, out_dir=out_dir, dv_name=dv)
    return {"result": result, "hl": hl}


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def logistic_cli(argv: list[str] | None = None) -> int:
    """
    psyclaw logit <data.csv> --dv <col> --iv col1,col2,...
            [--alpha .05] [--no-hl] [--json] [--out dir]
    """
    ap = argparse.ArgumentParser(
        prog="psyclaw logit",
        description="二元 Logistic 回归（IRLS；OR/Wald/LR/Hosmer-Lemeshow；APA-7）",
    )
    ap.add_argument("csv", help="输入数据 CSV 路径")
    ap.add_argument("--dv",  required=True, help="因变量列名（必须为 0/1 二元编码）")
    ap.add_argument("--iv",  required=True,
                    help="预测变量列名，逗号分隔（如 age,sex,score）")
    ap.add_argument("--alpha",  type=float, default=0.05, help="显著性水平（默认 .05）")
    ap.add_argument("--no-hl",  action="store_true",
                    help="跳过 Hosmer-Lemeshow 拟合优度检验")
    ap.add_argument("--out",    default=None, help="sidecar 输出目录（默认不写文件）")
    ap.add_argument("--json",   action="store_true", help="输出机器可读 JSON")
    args = ap.parse_args(argv)

    ivs = [c.strip() for c in args.iv.split(",") if c.strip()]
    try:
        output = analyze_logistic(
            args.csv, args.dv, ivs,
            alpha=args.alpha,
            out_dir=args.out,
            run_hl=not args.no_hl,
        )
    except Exception as exc:
        print(f"错误：{exc}")
        return 1

    result = output["result"]
    hl     = output["hl"]

    if args.json:
        payload = {k: v for k, v in result.items() if k != "mu"}
        if hl is not None:
            payload["hosmer_lemeshow"] = hl
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(format_apa_logistic(result, hl=hl, dv_name=args.dv))
        n_ex = result.get("n_excluded", 0)
        if n_ex:
            print(f"\n（已排除 {n_ex} 个含缺失值的案例）")
        conv_status = "已收敛" if result["convergence"] else "⚠ 未完全收敛"
        print(f"\n迭代次数：{result['n_iter']}  收敛状态：{conv_status}")
        if args.out:
            print(f"\n报告已写入：{args.out}/logistic_report.{{md,json}}")

    return 0
