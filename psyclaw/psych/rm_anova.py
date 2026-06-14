"""重复测量单因素 ANOVA — Mauchly 球形检验 / GG/HF ε 校正 / partial η² / ω²，stdlib only。

提供：
  - one_way_rm_anova(data, dv, subject, within)  → 完整结果 dict
  - pairwise_rm(Y, conditions, n, k, alpha)       → 成对配对 t + Holm 校正
  - format_apa_rm_anova(result, post_hoc)         → APA-7 Markdown 段落 + 表格
  - write_rm_anova_report(result, out_dir, ...)   → MD + JSON sidecar
  - analyze_rm_anova(csv_path, ...)               → CSV 主入口
  - rm_anova_cli(argv)                            → CLI 入口
  - CLI: psyclaw rm-anova <data.csv>
         --dv <col> --subject <col> --within <col>
         [--alpha .05] [--post-hoc] [--json] [--out dir]

理论依据：
  Greenhouse & Geisser (1959). Estimates of the degree of sphericity.
  Huynh & Feldt (1976). Estimation of the Box correction for degrees of freedom.
  Mauchly (1940). Significance test for sphericity.
  Maxwell, Delaney & Kelley (2017). Designing Experiments and Analyzing Data. 3rd ed.
  Olejnik & Algina (2003). Generalized eta and omega squared statistics.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
from typing import Any


# ---------------------------------------------------------------------------
# 分布工具（从 ttest.py 独立拷贝，避免循环导入）
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
    c, d = 1.0, 1.0 - (a + b) * x / (a + 1)
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, 200):
        m2 = 2 * m
        for j in range(2):
            if j == 0:
                num = m * (b - m) * x / ((a + m2 - 1) * (a + m2))
            else:
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


def _f_sf(f: float, df1: float, df2: float) -> float:
    """F 分布上尾 P(F > f)，接受非整数 df（用于 GG/HF 校正后）。"""
    if not math.isfinite(f) or f <= 0 or df1 <= 0 or df2 <= 0:
        return 1.0 if f <= 0 else 0.0
    x = df2 / (df2 + df1 * f)
    return _betai(df2 / 2.0, df1 / 2.0, x)


def _t_sf2(t: float, df: float) -> float:
    """学生 t 双尾 p。"""
    if df <= 0:
        return float("nan")
    x = df / (df + t * t)
    return _betai(df / 2.0, 0.5, x)


def _gammainc(a: float, x: float) -> float:
    """正则化下不完全 Gamma P(a, x)（级数 + 连分式）。"""
    if x < 0 or a <= 0:
        return float("nan")
    if x < a + 1.0:
        ap, s, d = a, 1.0 / a, 1.0 / a
        for _ in range(200):
            ap += 1
            d *= x / ap
            s += d
            if abs(d) < abs(s) * 1e-14:
                break
        return s * math.exp(-x + a * math.log(x) - math.lgamma(a))
    fpmin = 1e-300
    b = x + 1.0 - a
    c, d, h = 1.0 / fpmin, 1.0 / b, 1.0 / b
    for i in range(1, 200):
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
        if abs(delta - 1.0) < 1e-14:
            break
    return 1.0 - math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def _chi2_sf(x: float, df: float) -> float:
    if x <= 0:
        return 1.0
    return 1.0 - _gammainc(df / 2.0, x / 2.0)


def _norm_ppf(p: float) -> float:
    if p <= 0 or p >= 1:
        return float("nan")
    if p > 0.5:
        return -_norm_ppf(1 - p)
    t = math.sqrt(-2 * math.log(p))
    c = [2.515517, 0.802853, 0.010328]
    d = [1.432788, 0.189269, 0.001308]
    return -(t - (c[0] + c[1] * t + c[2] * t * t) /
             (1 + d[0] * t + d[1] * t * t + d[2] * t * t * t))


def _t_ppf(p: float, df: float) -> float:
    """t 分位数（二分法，对称分布）。"""
    if df > 1e6:
        return _norm_ppf(p)
    target = 2 * (1 - p) if p > 0.5 else 2 * p
    lo, hi = 0.0, 100.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if _t_sf2(mid, df) > target:
            lo = mid
        else:
            hi = mid
    val = (lo + hi) / 2
    return val if p > 0.5 else -val


# ---------------------------------------------------------------------------
# 小矩阵工具（所有矩阵均以 list[list[float]] 表示）
# ---------------------------------------------------------------------------

def _mat_mul(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
    m, p, n = len(A), len(A[0]), len(B[0])
    C = [[0.0] * n for _ in range(m)]
    for i in range(m):
        for j in range(n):
            C[i][j] = sum(A[i][kk] * B[kk][j] for kk in range(p))
    return C


def _mat_det(mat: list[list[float]]) -> float:
    """行主元 LU 分解求行列式（就地操作副本）。"""
    n = len(mat)
    m = [row[:] for row in mat]
    sign = 1.0
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-300:
            return 0.0
        if pivot != col:
            m[col], m[pivot] = m[pivot], m[col]
            sign *= -1
        for row in range(col + 1, n):
            f = m[row][col] / m[col][col]
            for j in range(col, n):
                m[row][j] -= f * m[col][j]
    det = sign
    for i in range(n):
        det *= m[i][i]
    return det


def _cov_matrix(data: list[list[float]]) -> list[list[float]]:
    """计算 n×k 数据矩阵的 k×k 样本协方差矩阵。"""
    n, k = len(data), len(data[0])
    means = [sum(data[i][j] for i in range(n)) / n for j in range(k)]
    cov = [[0.0] * k for _ in range(k)]
    for i in range(n):
        for a in range(k):
            for b in range(a, k):
                cov[a][b] += (data[i][a] - means[a]) * (data[i][b] - means[b])
    for a in range(k):
        for b in range(a, k):
            cov[a][b] /= (n - 1)
            cov[b][a] = cov[a][b]
    return cov


# ---------------------------------------------------------------------------
# Helmert 正交归一对比矩阵 k × (k-1)
# ---------------------------------------------------------------------------

def _helmert_contrast(k: int) -> list[list[float]]:
    """返回 k×(k-1) 正交归一 Helmert 对比矩阵（每列范数 = 1，列间正交）。"""
    C = [[0.0] * (k - 1) for _ in range(k)]
    for j in range(k - 1):
        val_pos = 1.0 / math.sqrt((j + 1) * (j + 2))
        val_neg = -(j + 1) / math.sqrt((j + 1) * (j + 2))
        for i in range(j + 1):
            C[i][j] = val_pos
        C[j + 1][j] = val_neg
    return C


# ---------------------------------------------------------------------------
# Mauchly 球形检验
# ---------------------------------------------------------------------------

def _mauchly_test(Y: list[list[float]], k: int, n: int) -> dict[str, Any]:
    """
    Mauchly's W 球形检验（Mauchly, 1940）。
    k=2 时球形性自动成立（W=1, p=1）。
    df_W = k(k-1)/2 - 1。
    """
    if k == 2:
        return {"W": 1.0, "chi2": 0.0, "df": 0, "p": 1.0, "spherical": True}

    C = _helmert_contrast(k)          # k × (k-1)
    C_T = [[C[r][c] for r in range(k)] for c in range(k - 1)]  # (k-1) × k

    # Z = Y @ C  →  n × (k-1)
    Z = _mat_mul(Y, C)

    # S_Z: (k-1)×(k-1) 协方差矩阵
    S_Z = _cov_matrix(Z)

    tr = sum(S_Z[i][i] for i in range(k - 1))
    det = _mat_det(S_Z)

    df_W = k * (k - 1) // 2 - 1

    if tr <= 0 or det <= 0:
        return {"W": 0.0, "chi2": float("inf"), "df": df_W, "p": 0.0, "spherical": False}

    W = min(1.0, max(0.0, det / (tr / (k - 1)) ** (k - 1)))

    if df_W <= 0 or W <= 0:
        p = 1.0 if W >= 1.0 else 0.0
        return {"W": W, "chi2": 0.0, "df": df_W, "p": p,
                "spherical": p > 0.05}

    # chi-squared 近似（Field, 2013, Eq 8.9；Maxwell et al., 2017）
    p_val = k - 1
    bias = (n - 1) - (2 * p_val ** 2 + p_val + 2) / (6 * p_val)
    chi2 = -bias * math.log(W)
    p = _chi2_sf(chi2, df_W)
    return {"W": W, "chi2": chi2, "df": df_W, "p": p, "spherical": p > 0.05}


# ---------------------------------------------------------------------------
# Greenhouse-Geisser 和 Huynh-Feldt ε
# ---------------------------------------------------------------------------

def _epsilon_gg(S: list[list[float]], k: int) -> float:
    """Greenhouse-Geisser epsilon（从 k 条件 k×k 协方差矩阵计算）。"""
    mean_all = sum(S[i][j] for i in range(k) for j in range(k)) / (k * k)
    mean_diag = sum(S[i][i] for i in range(k)) / k
    col_means = [sum(S[i][j] for i in range(k)) / k for j in range(k)]
    sum_sq = sum(S[i][j] ** 2 for i in range(k) for j in range(k))
    sum_col_sq = sum(cm ** 2 for cm in col_means)

    numer = k ** 2 * (mean_diag - mean_all) ** 2
    denom = (k - 1) * (sum_sq - 2 * k * sum_col_sq + k ** 2 * mean_all ** 2)
    if abs(denom) < 1e-300:
        return 1.0
    return max(1.0 / (k - 1), min(1.0, numer / denom))


def _epsilon_hf(eps_gg: float, n: int, k: int) -> float:
    """Huynh-Feldt epsilon（Huynh & Feldt, 1976）。"""
    p = k - 1
    denom = p * (n - 1 - p * eps_gg)
    if abs(denom) < 1e-14:
        return 1.0
    return max(1.0 / (k - 1), min(1.0, (n * p * eps_gg - 2) / denom))


# ---------------------------------------------------------------------------
# 主计算：单因素重复测量 ANOVA
# ---------------------------------------------------------------------------

def one_way_rm_anova(
    data: list[dict],
    dv: str,
    subject: str,
    within: str,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """
    单因素重复测量 ANOVA（长格式数据）。

    data:    行字典列表，每行一个观测
    dv:      因变量列名（数值）
    subject: 被试 ID 列名
    within:  被试内因子列名（条件/时间点）
    alpha:   显著性水平

    返回含 F/p/eta²/partial_eta²/omega²/Mauchly/GG/HF/condition_stats 的 dict。
    """
    subjects: list = []
    conditions: list = []
    seen_s: dict = {}
    seen_c: dict = {}
    cell: dict = {}

    for row in data:
        try:
            y = float(row[dv])
        except (KeyError, ValueError, TypeError):
            continue
        s, c = row.get(subject), row.get(within)
        if s is None or c is None:
            continue
        if s not in seen_s:
            seen_s[s] = len(subjects)
            subjects.append(s)
        if c not in seen_c:
            seen_c[c] = len(conditions)
            conditions.append(c)
        cell[(s, c)] = y

    n, k = len(subjects), len(conditions)
    if n < 2:
        raise ValueError("重复测量 ANOVA 至少需要 2 个被试。")
    if k < 2:
        raise ValueError("重复测量 ANOVA 至少需要 2 个条件/水平。")

    missing = [(s, c) for s in subjects for c in conditions if (s, c) not in cell]
    if missing:
        raise ValueError(
            f"数据不均衡：{len(missing)} 个 subject×condition 格缺失 "
            f"（如 subject={missing[0][0]!r}, within={missing[0][1]!r}）。"
        )

    # n×k 矩阵
    Y: list[list[float]] = [[cell[(s, c)] for c in conditions] for s in subjects]

    # --- SS 分解 ---
    GM = sum(Y[i][j] for i in range(n) for j in range(k)) / (n * k)
    cond_means = [sum(Y[i][j] for i in range(n)) / n for j in range(k)]
    subj_means = [sum(Y[i][j] for j in range(k)) / k for i in range(n)]

    SS_between = n * sum((cond_means[j] - GM) ** 2 for j in range(k))
    SS_subjects = k * sum((subj_means[i] - GM) ** 2 for i in range(n))
    SS_total = sum((Y[i][j] - GM) ** 2 for i in range(n) for j in range(k))
    SS_error = SS_total - SS_between - SS_subjects

    df_between = k - 1
    df_error = (k - 1) * (n - 1)

    MS_between = SS_between / df_between
    MS_error = SS_error / df_error if df_error > 0 else float("nan")

    if math.isnan(MS_error) or MS_error <= 0:
        F = float("nan")
        p_uncorr = float("nan")
    else:
        F = MS_between / MS_error
        p_uncorr = _f_sf(F, df_between, df_error)

    # 效应量
    eta2 = SS_between / SS_total if SS_total > 0 else 0.0
    partial_eta2 = SS_between / (SS_between + SS_error) if (SS_between + SS_error) > 0 else 0.0
    # ω²（Olejnik & Algina, 2003）
    if not math.isnan(MS_error):
        omega2 = max(0.0, (df_between * (MS_between - MS_error)) / (SS_total + MS_error))
    else:
        omega2 = float("nan")

    # --- 球形检验 + epsilon ---
    mauchly = _mauchly_test(Y, k, n)
    S = _cov_matrix(Y)
    eps_gg = _epsilon_gg(S, k)
    eps_hf = _epsilon_hf(eps_gg, n, k)

    df1_gg, df2_gg = eps_gg * df_between, eps_gg * df_error
    p_gg = _f_sf(F, df1_gg, df2_gg) if not math.isnan(F) else float("nan")

    df1_hf, df2_hf = eps_hf * df_between, eps_hf * df_error
    p_hf = _f_sf(F, df1_hf, df2_hf) if not math.isnan(F) else float("nan")

    # APA 建议：违反球形性时 eps_gg≥.75 报 HF，否则报 GG
    report_correction = "none"
    if not mauchly["spherical"] and k > 2:
        report_correction = "hf" if eps_gg >= 0.75 else "gg"

    # 依据校正选取 p 判断显著性
    if report_correction == "gg":
        p_report = p_gg
    elif report_correction == "hf":
        p_report = p_hf
    else:
        p_report = p_uncorr

    # 条件描述统计
    cond_stats = []
    for j, cond in enumerate(conditions):
        vals = [Y[i][j] for i in range(n)]
        m = cond_means[j]
        sd = math.sqrt(sum((v - m) ** 2 for v in vals) / (n - 1)) if n > 1 else 0.0
        se = sd / math.sqrt(n)
        cond_stats.append({"condition": cond, "n": n, "mean": m, "sd": sd, "se": se})

    return {
        "dv": dv,
        "subject": subject,
        "within": within,
        "n_subjects": n,
        "k_conditions": k,
        "conditions": conditions,
        "grand_mean": GM,
        "condition_stats": cond_stats,
        "SS_between": SS_between,
        "SS_subjects": SS_subjects,
        "SS_error": SS_error,
        "SS_total": SS_total,
        "df_between": df_between,
        "df_subjects": n - 1,
        "df_error": df_error,
        "MS_between": MS_between,
        "MS_error": MS_error,
        "F": F,
        "p": p_uncorr,
        "eta2": eta2,
        "partial_eta2": partial_eta2,
        "omega2": omega2,
        "mauchly": mauchly,
        "epsilon_gg": eps_gg,
        "df1_gg": df1_gg,
        "df2_gg": df2_gg,
        "p_gg": p_gg,
        "epsilon_hf": eps_hf,
        "df1_hf": df1_hf,
        "df2_hf": df2_hf,
        "p_hf": p_hf,
        "report_correction": report_correction,
        "p_report": p_report,
        "alpha": alpha,
        "significant": (p_report < alpha) if not math.isnan(p_report) else False,
        # 保存矩阵供事后检验
        "_Y": Y,
    }


# ---------------------------------------------------------------------------
# 成对事后检验（配对 t + Holm 校正）
# ---------------------------------------------------------------------------

def pairwise_rm(
    Y: list[list[float]],
    conditions: list,
    n: int,
    k: int,
    alpha: float = 0.05,
) -> list[dict[str, Any]]:
    """所有条件对做配对 t 检验，Holm 法校正多重比较。"""
    pairs: list[dict] = []
    t_crit = _t_ppf(1 - alpha / 2, n - 1)

    for j1 in range(k):
        for j2 in range(j1 + 1, k):
            diffs = [Y[i][j1] - Y[i][j2] for i in range(n)]
            m_d = sum(diffs) / n
            sd_d = math.sqrt(sum((d - m_d) ** 2 for d in diffs) / (n - 1)) if n > 1 else 0.0
            se_d = sd_d / math.sqrt(n) if sd_d > 0 else 0.0
            if se_d == 0:
                t = float("inf") if abs(m_d) > 0 else 0.0
                p_raw = 0.0 if abs(m_d) > 0 else 1.0
            else:
                t = m_d / se_d
                p_raw = _t_sf2(t, n - 1)
            d_z = m_d / sd_d if sd_d > 0 else float("nan")
            ci_lo = m_d - t_crit * se_d
            ci_hi = m_d + t_crit * se_d
            pairs.append({
                "cond1": conditions[j1],
                "cond2": conditions[j2],
                "mean_diff": m_d,
                "ci_lower": ci_lo,
                "ci_upper": ci_hi,
                "t": t,
                "df": n - 1,
                "p_raw": p_raw,
                "d_z": d_z,
            })

    # Holm 校正（单调递增保证）
    m = len(pairs)
    order = sorted(range(m), key=lambda i: pairs[i]["p_raw"])
    p_adj = [0.0] * m
    running_max = 0.0
    for rank, idx in enumerate(order):
        p_adj[idx] = min(1.0, pairs[idx]["p_raw"] * (m - rank))
        if p_adj[idx] < running_max:
            p_adj[idx] = running_max
        running_max = p_adj[idx]

    for i, pair in enumerate(pairs):
        pair["p_holm"] = p_adj[i]
        pair["significant"] = p_adj[i] < alpha

    return pairs


# ---------------------------------------------------------------------------
# APA-7 格式化
# ---------------------------------------------------------------------------

def _fmt_p(p: float) -> str:
    if not math.isfinite(p):
        return "= ?"
    if p < 0.001:
        return "< .001"
    return f"= {p:.3f}".replace("0.", ".")


def _fmt_num(x: float, decimals: int = 2) -> str:
    if not math.isfinite(x):
        return "?"
    fmt = f"{x:.{decimals}f}"
    return fmt


def format_apa_rm_anova(
    result: dict[str, Any],
    post_hoc: list[dict] | None = None,
) -> str:
    n = result["n_subjects"]
    k = result["k_conditions"]
    within = result["within"]
    dv = result["dv"]
    F = result["F"]
    alpha = result["alpha"]
    corr = result["report_correction"]

    # 依校正选取汇报的 F 和 df
    if corr == "gg":
        df1_r, df2_r, p_r, eps_label = (
            result["df1_gg"], result["df2_gg"], result["p_gg"], f"ε_GG = {result['epsilon_gg']:.3f}"
        )
    elif corr == "hf":
        df1_r, df2_r, p_r, eps_label = (
            result["df1_hf"], result["df2_hf"], result["p_hf"], f"ε_HF = {result['epsilon_hf']:.3f}"
        )
    else:
        df1_r, df2_r, p_r, eps_label = (
            result["df_between"], result["df_error"], result["p"], ""
        )

    df1_str = f"{df1_r:.2f}" if corr != "none" else str(int(round(df1_r)))
    df2_str = f"{df2_r:.2f}" if corr != "none" else str(int(round(df2_r)))
    corr_note = f", {eps_label}" if eps_label else ""
    sig_word = "显著" if result["significant"] else "不显著"

    lines = []
    lines.append(f"## 重复测量 ANOVA 结果 — {dv} × {within}")
    lines.append("")

    # 条件均值表
    lines.append("**各条件描述统计**")
    lines.append("")
    lines.append("| 条件 | *N* | *M* | *SD* | *SE* |")
    lines.append("|------|-----|-----|------|------|")
    for cs in result["condition_stats"]:
        lines.append(
            f"| {cs['condition']} | {cs['n']} "
            f"| {_fmt_num(cs['mean'])} | {_fmt_num(cs['sd'])} | {_fmt_num(cs['se'])} |"
        )
    lines.append("")

    # ANOVA 摘要表（APA-7 三线表）
    lines.append("**ANOVA 摘要**")
    lines.append("")
    lines.append("| 来源 | *SS* | *df* | *MS* | *F* | *p* | η²p |")
    lines.append("|------|------|------|------|-----|-----|-----|")
    # 条件（校正 df）
    df1_disp = df1_str
    df2_disp = df2_str
    lines.append(
        f"| {within}（条件） "
        f"| {_fmt_num(result['SS_between'])} "
        f"| {df1_disp} "
        f"| {_fmt_num(result['MS_between'])} "
        f"| {_fmt_num(F)} "
        f"| {_fmt_p(p_r)} "
        f"| {_fmt_num(result['partial_eta2'], 3)} |"
    )
    # 误差
    lines.append(
        f"| 误差 "
        f"| {_fmt_num(result['SS_error'])} "
        f"| {df2_disp} "
        f"| {_fmt_num(result['MS_error'])} "
        f"| | | |"
    )
    lines.append("")

    # Mauchly 球形检验（k > 2 时报告）
    if k > 2:
        mw = result["mauchly"]
        sph_label = "成立" if mw["spherical"] else "违反"
        lines.append("**Mauchly 球形检验**")
        lines.append("")
        if mw["df"] > 0:
            lines.append(
                f"Mauchly's *W* = {mw['W']:.3f}, χ²({mw['df']}) = {mw['chi2']:.3f}, "
                f"*p* {_fmt_p(mw['p'])}。球形性假设{sph_label}。"
            )
        else:
            lines.append(f"Mauchly's *W* = {mw['W']:.3f}（自由度不足，无法检验）。")
        if not mw["spherical"]:
            lines.append(
                f"已应用 {'Huynh-Feldt (ε = ' + _fmt_num(result['epsilon_hf'], 3) + ')' if corr == 'hf' else 'Greenhouse-Geisser (ε = ' + _fmt_num(result['epsilon_gg'], 3) + ')'} 自由度校正。"
            )
        lines.append("")

    # 结果段落
    lines.append("**结果段落（APA-7）**")
    lines.append("")
    lines.append(
        f"对 {dv} 进行单因素重复测量 ANOVA，被试内因子为 {within}（{k} 个水平，"
        f"*N* = {n}）。"
    )
    main_line = (
        f"主效应{sig_word}，*F*({df1_str}, {df2_str}) = {_fmt_num(F)}, "
        f"*p* {_fmt_p(p_r)}{corr_note}, "
        f"η²p = {_fmt_num(result['partial_eta2'], 3)}, "
        f"ω² = {_fmt_num(result['omega2'], 3)}。"
    )
    lines.append(main_line)
    lines.append("")

    # 事后检验
    if post_hoc:
        lines.append("**成对比较（配对 *t* 检验，Holm 校正）**")
        lines.append("")
        lines.append("| 比较 | *M*diff | 95% CI | *t* | *df* | *p*_holm | *d*z | 显著 |")
        lines.append("|------|---------|--------|-----|------|----------|------|------|")
        for ph in post_hoc:
            ci = f"[{_fmt_num(ph['ci_lower'])}, {_fmt_num(ph['ci_upper'])}]"
            sig = "✓" if ph["significant"] else ""
            dz_str = _fmt_num(ph["d_z"], 3) if math.isfinite(ph.get("d_z", float("nan"))) else "—"
            lines.append(
                f"| {ph['cond1']} vs {ph['cond2']} "
                f"| {_fmt_num(ph['mean_diff'])} "
                f"| {ci} "
                f"| {_fmt_num(ph['t'])} "
                f"| {ph['df']} "
                f"| {_fmt_p(ph['p_holm'])} "
                f"| {dz_str} "
                f"| {sig} |"
            )
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# sidecar 输出
# ---------------------------------------------------------------------------

def write_rm_anova_report(
    result: dict[str, Any],
    out_dir: str | pathlib.Path = "notes",
    post_hoc: list[dict] | None = None,
) -> pathlib.Path:
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    md_text = format_apa_rm_anova(result, post_hoc=post_hoc)
    md_path = out / "rm_anova_report.md"
    md_path.write_text(md_text, encoding="utf-8")

    # JSON 不含内部矩阵 _Y
    safe = {k: v for k, v in result.items() if not k.startswith("_")}
    if post_hoc:
        safe["post_hoc"] = post_hoc
    json_path = out / "rm_anova_report.json"
    json_path.write_text(json.dumps(safe, ensure_ascii=False, indent=2, default=str),
                         encoding="utf-8")
    return md_path


# ---------------------------------------------------------------------------
# CSV 主入口
# ---------------------------------------------------------------------------

def analyze_rm_anova(
    csv_path: str | pathlib.Path,
    dv: str,
    subject: str,
    within: str,
    alpha: float = 0.05,
    post_hoc: bool = False,
    out_dir: str | pathlib.Path | None = None,
    as_json: bool = False,
) -> dict[str, Any]:
    rows = []
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append(row)

    result = one_way_rm_anova(rows, dv=dv, subject=subject, within=within, alpha=alpha)
    Y = result["_Y"]
    conditions = result["conditions"]
    n = result["n_subjects"]
    k = result["k_conditions"]

    ph = pairwise_rm(Y, conditions, n, k, alpha=alpha) if post_hoc else None

    if out_dir:
        write_rm_anova_report(result, out_dir=out_dir, post_hoc=ph)

    safe = {kk: v for kk, v in result.items() if not kk.startswith("_")}
    if ph:
        safe["post_hoc"] = ph

    if as_json:
        print(json.dumps(safe, ensure_ascii=False, indent=2, default=str))
    else:
        print(format_apa_rm_anova(result, post_hoc=ph))

    return safe


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def rm_anova_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="psyclaw rm-anova",
        description="单因素重复测量 ANOVA — Mauchly 球形检验 / GG/HF ε 校正 / APA-7 报告",
    )
    parser.add_argument("csv", help="输入数据 CSV 路径（长格式：每行一个 subject×condition 观测）")
    parser.add_argument("--dv", required=True, help="因变量列名（数值）")
    parser.add_argument("--subject", required=True, help="被试 ID 列名")
    parser.add_argument("--within", required=True, help="被试内因子列名（条件/时间点）")
    parser.add_argument("--alpha", type=float, default=0.05, help="显著性水平（默认 .05）")
    parser.add_argument("--post-hoc", action="store_true", dest="post_hoc",
                        help="输出所有条件对配对 t 检验（Holm 校正）")
    parser.add_argument("--out", default=None, help="sidecar 输出目录（写 rm_anova_report.*）")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = parser.parse_args(argv)

    try:
        analyze_rm_anova(
            csv_path=args.csv,
            dv=args.dv,
            subject=args.subject,
            within=args.within,
            alpha=args.alpha,
            post_hoc=args.post_hoc,
            out_dir=args.out,
            as_json=args.json,
        )
        return 0
    except (ValueError, FileNotFoundError) as exc:
        print(f"错误：{exc}")
        return 1
