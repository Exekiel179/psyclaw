"""混合 ANOVA（Split-plot ANOVA）— 一个被试间因素 × 一个被试内因素。

提供：
  - mixed_anova(data, dv, between, within, subject[, alpha])  → 结果 dict
  - simple_effects_within(result)                             → 各 between 水平的单纯主效应
  - format_apa_mixed(result[, post_hoc])                      → APA-7 Markdown
  - write_mixed_report(result, out_dir[, ...])                → MD + JSON sidecar
  - analyze_mixed(csv_path, ...)                              → CSV 主入口
  - mixed_anova_cli(argv)                                     → CLI 入口
  - CLI: psyclaw mixed-anova <data.csv>
         --dv <col> --between <col> --within <col> --subject <col>
         [--alpha .05] [--post-hoc] [--json] [--out dir]

SS 分解（Kirk, 2013 / Maxwell et al., 2017）：
  SS_total = SS_A + SS_S(A) + SS_B + SS_AB + SS_BS(A)
  F_A  = MS_A  / MS_S(A)     （被试间因素）
  F_B  = MS_B  / MS_BS(A)    （被试内因素）
  F_AB = MS_AB / MS_BS(A)    （交互效应）

效应量：partial η²（Lakens, 2013）、partial ω²（Olejnik & Algina, 2003）。
球形检验：Mauchly W，GG/HF ε 校正（Greenhouse & Geisser, 1959；Huynh & Feldt, 1976）。

理论依据：
  Kirk, R.E. (2013). Experimental Design, 4th ed.
  Maxwell, S.A., Delaney, H.D., & Kelley, K. (2017). Designing Experiments and Analyzing Data, 3rd ed.
  Olejnik, S., & Algina, J. (2003). Generalized eta and omega squared statistics.
  Greenhouse, S.W., & Geisser, S. (1959). Estimates of the degree of sphericity.
  Huynh, H., & Feldt, L.S. (1976). Estimation of the Box correction.
  Lakens, D. (2013). Calculating and reporting effect sizes to facilitate cumulative science.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
from typing import Any


# ---------------------------------------------------------------------------
# 分布工具
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
    if not math.isfinite(f) or f < 0 or df1 <= 0 or df2 <= 0:
        return 1.0 if (not math.isfinite(f) or f <= 0) else 0.0
    if f == 0:
        return 1.0
    x = df2 / (df2 + df1 * f)
    return _betai(df2 / 2.0, df1 / 2.0, x)


def _t_sf2(t: float, df: float) -> float:
    if not math.isfinite(t) or df <= 0:
        return float("nan")
    x = df / (df + t * t)
    return _betai(df / 2.0, 0.5, x)


def _igammap(a: float, x: float) -> float:
    if x <= 0 or a <= 0:
        return 0.0
    lga = math.lgamma(a)
    ap, delta, s = a, 1.0 / a, 1.0 / a
    for _ in range(300):
        ap += 1
        delta *= x / ap
        s += delta
        if abs(delta) < abs(s) * 1e-14:
            break
    return math.exp(-x + a * math.log(x) - lga) * s


def _igammac(a: float, x: float) -> float:
    if x < 0 or a <= 0:
        return 1.0
    if x < a + 1:
        return 1.0 - _igammap(a, x)
    lga = math.lgamma(a)
    b = x + 1 - a
    c, d = 1e300, 1.0 / b if b != 0 else 1e300
    h = d
    for i in range(1, 200):
        num = -i * (i - a)
        b += 2
        d = num * d + b
        if abs(d) < 1e-300:
            d = 1e-300
        c = b + num / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    return math.exp(-x + a * math.log(x) - lga) * h


def _chi2_sf(x: float, df: float) -> float:
    if x <= 0 or df <= 0:
        return 1.0
    return _igammac(df / 2.0, x / 2.0)


# ---------------------------------------------------------------------------
# 矩阵 / 球形检验工具
# ---------------------------------------------------------------------------

def _mat_cov(rows: list[list[float]]) -> list[list[float]]:
    n = len(rows)
    k = len(rows[0])
    means = [sum(rows[i][j] for i in range(n)) / n for j in range(k)]
    cov = [[0.0] * k for _ in range(k)]
    for i in range(n):
        for r in range(k):
            for c in range(k):
                cov[r][c] += (rows[i][r] - means[r]) * (rows[i][c] - means[c])
    for r in range(k):
        for c in range(k):
            cov[r][c] /= (n - 1)
    return cov


def _log_det_chol(M: list[list[float]]) -> float:
    n = len(M)
    L = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            s = sum(L[i][k] * L[j][k] for k in range(j))
            if i == j:
                v = M[i][i] - s
                if v <= 0:
                    return float("-inf")
                L[i][j] = math.sqrt(v)
            else:
                if L[j][j] == 0:
                    return float("-inf")
                L[i][j] = (M[i][j] - s) / L[j][j]
    return 2.0 * sum(math.log(L[i][i]) for i in range(n))


def _helmert(k: int) -> list[list[float]]:
    """k×(k-1) Helmert 对比矩阵（行=条件，列=对比），每列 L2 归一化。"""
    contrasts = []
    for c in range(k - 1):
        col = [0.0] * k
        for i in range(c + 1):
            col[i] = -1.0 / (c + 1)
        col[c + 1] = 1.0
        norm = math.sqrt(sum(v * v for v in col))
        contrasts.append([v / norm for v in col])
    return [[contrasts[j][i] for j in range(k - 1)] for i in range(k)]


def _mauchly_test(data_mat: list[list[float]], k: int) -> dict[str, Any]:
    """
    Mauchly 球形检验（Mitchell, 2016 表述）。

    data_mat : N×k 矩阵（所有被试的 b 水平观测）
    k        : 被试内因素水平数
    返回 {W, chi2, df, p, epsilon_gg, epsilon_hf, epsilon_lb}
    """
    if k <= 2:
        return dict(W=1.0, chi2=float("nan"), df=0, p=1.0,
                    epsilon_gg=1.0, epsilon_hf=1.0, epsilon_lb=1.0)
    n = len(data_mat)
    p = k - 1
    if n <= p:
        return dict(W=float("nan"), chi2=float("nan"), df=0, p=float("nan"),
                    epsilon_gg=float("nan"), epsilon_hf=float("nan"),
                    epsilon_lb=1.0 / p)
    H = _helmert(k)
    Y = [[sum(data_mat[i][c] * H[c][j] for c in range(k)) for j in range(p)]
         for i in range(n)]
    S = _mat_cov(Y)
    tr = sum(S[i][i] for i in range(p))
    if tr <= 0:
        return dict(W=0.0, chi2=float("nan"), df=0, p=float("nan"),
                    epsilon_gg=float("nan"), epsilon_hf=float("nan"),
                    epsilon_lb=1.0 / p)
    log_det = _log_det_chol(S)
    log_W = log_det - p * math.log(tr / p)
    W = math.exp(log_W) if log_W > -700 else 0.0
    df_w = p * (p + 1) // 2 - 1
    if df_w == 0:
        return dict(W=W, chi2=float("nan"), df=0, p=1.0,
                    epsilon_gg=1.0, epsilon_hf=1.0, epsilon_lb=1.0 / p)
    chi2 = -(n - 1 - (2 * p * p + p + 2) / (6 * p)) * math.log(W) if W > 0 else float("inf")
    p_val = _chi2_sf(chi2, df_w)
    # GG ε
    ss2 = sum(S[i][j] ** 2 for i in range(p) for j in range(p))
    eps_gg = max(1.0 / p, min(1.0, (tr ** 2) / (p * ss2)))
    # HF ε (Huynh & Feldt, 1976)
    eps_hf = min(1.0, (n * p * eps_gg - 2) / (p * (n - 1 - p * eps_gg)))
    eps_lb = 1.0 / p
    return dict(W=W, chi2=chi2, df=df_w, p=p_val,
                epsilon_gg=eps_gg, epsilon_hf=eps_hf, epsilon_lb=eps_lb)


# ---------------------------------------------------------------------------
# 混合 ANOVA 核心
# ---------------------------------------------------------------------------

def mixed_anova(
    data: list[dict[str, Any]],
    dv: str,
    between: str,
    within: str,
    subject: str,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """
    混合 ANOVA（Split-plot）：一个被试间因素 × 一个被试内因素。

    Parameters
    ----------
    data    : 长格式，每行一个观测，列 dv / between / within / subject 均必需
    dv      : 因变量列名
    between : 被试间因素列名
    within  : 被试内因素列名
    subject : 被试 ID 列名
    alpha   : 显著性水平（默认 .05）

    Returns
    -------
    dict，含：
      effects / sphericity / corrected / cell_means / group_means /
      condition_means / n_per_group / N / warnings
    """
    warnings: list[str] = []

    # ---- 数据解析 ----
    parsed: list[dict] = []
    for row in data:
        try:
            y = float(row[dv])
        except (KeyError, TypeError, ValueError):
            continue
        if not math.isfinite(y):
            continue
        parsed.append({"s": str(row.get(subject, "")),
                        "A": str(row.get(between, "")),
                        "B": str(row.get(within, "")),
                        "y": y})

    if not parsed:
        raise ValueError("无有效数据行（检查列名或缺失值）")

    a_levels = sorted(set(r["A"] for r in parsed))
    b_levels = sorted(set(r["B"] for r in parsed))
    a, b = len(a_levels), len(b_levels)

    if a < 2:
        raise ValueError(f"被试间因素需要 ≥ 2 水平，实际：{a}")
    if b < 2:
        raise ValueError(f"被试内因素需要 ≥ 2 水平，实际：{b}")

    # ---- 按被试组织观测 ----
    subj_group: dict[str, str] = {}
    subj_obs: dict[str, dict[str, float]] = {}
    for r in parsed:
        s, A, B, y = r["s"], r["A"], r["B"], r["y"]
        if s in subj_group and subj_group[s] != A:
            warnings.append(f"被试 {s!r} 出现在多个 between 水平，已忽略冲突观测。")
            continue
        subj_group[s] = A
        if s not in subj_obs:
            subj_obs[s] = {}
        subj_obs[s][B] = y  # 重复取最后值

    # 剔除数据不完整的被试
    complete: list[str] = []
    for s, obs in subj_obs.items():
        if all(bl in obs for bl in b_levels):
            complete.append(s)
        else:
            warnings.append(f"被试 {s!r} 缺少部分条件数据，已排除。")

    if not complete:
        raise ValueError("无数据完整的被试")

    group_complete: dict[str, list[str]] = {lvl: [] for lvl in a_levels}
    for s in complete:
        group_complete[subj_group[s]].append(s)

    n_per_group = {lvl: len(group_complete[lvl]) for lvl in a_levels}
    if any(v < 2 for v in n_per_group.values()):
        raise ValueError("每组至少需要 2 名完整被试")
    if len(set(n_per_group.values())) > 1:
        warnings.append("各组被试量不等（非均衡设计），采用 Type-I SS，解释时需谨慎。")

    N = sum(n_per_group.values())

    def Y(s: str, bl: str) -> float:
        return subj_obs[s][bl]

    # ---- 均值 ----
    all_vals = [Y(s, bl) for s in complete for bl in b_levels]
    grand = sum(all_vals) / len(all_vals)

    mean_A: dict[str, float] = {}
    for lvl in a_levels:
        vals = [Y(s, bl) for s in group_complete[lvl] for bl in b_levels]
        mean_A[lvl] = sum(vals) / len(vals)

    mean_B: dict[str, float] = {}
    for bl in b_levels:
        vals = [Y(s, bl) for s in complete]
        mean_B[bl] = sum(vals) / len(vals)

    mean_AB: dict[str, dict[str, float]] = {}
    for lvl in a_levels:
        mean_AB[lvl] = {}
        for bl in b_levels:
            vals = [Y(s, bl) for s in group_complete[lvl]]
            mean_AB[lvl][bl] = sum(vals) / len(vals)

    mean_s: dict[str, float] = {}
    for s in complete:
        mean_s[s] = sum(Y(s, bl) for bl in b_levels) / b

    # ---- SS ----
    SS_A = sum(len(group_complete[lvl]) * b * (mean_A[lvl] - grand) ** 2
               for lvl in a_levels)

    SS_SA = sum(b * (mean_s[s] - mean_A[subj_group[s]]) ** 2
                for s in complete)

    SS_B = sum(N * (mean_B[bl] - grand) ** 2 for bl in b_levels)

    SS_AB = sum(
        len(group_complete[lvl]) * (mean_AB[lvl][bl] - mean_A[lvl] - mean_B[bl] + grand) ** 2
        for lvl in a_levels
        for bl in b_levels
    )

    SS_BSA = sum(
        (Y(s, bl) - mean_s[s] - mean_AB[subj_group[s]][bl] + mean_A[subj_group[s]]) ** 2
        for s in complete
        for bl in b_levels
    )

    SS_total = sum((v - grand) ** 2 for v in all_vals)

    # ---- df ----
    df_A = a - 1
    df_SA = N - a
    df_B = b - 1
    df_AB = (a - 1) * (b - 1)
    df_BSA = (N - a) * (b - 1)

    # ---- MS ----
    MS_A   = SS_A   / df_A   if df_A   > 0 else float("nan")
    MS_SA  = SS_SA  / df_SA  if df_SA  > 0 else float("nan")
    MS_B   = SS_B   / df_B   if df_B   > 0 else float("nan")
    MS_AB  = SS_AB  / df_AB  if df_AB  > 0 else float("nan")
    MS_BSA = SS_BSA / df_BSA if df_BSA > 0 else float("nan")

    # ---- F ----
    F_A  = MS_A  / MS_SA  if math.isfinite(MS_SA)  and MS_SA  > 0 else float("nan")
    F_B  = MS_B  / MS_BSA if math.isfinite(MS_BSA) and MS_BSA > 0 else float("nan")
    F_AB = MS_AB / MS_BSA if math.isfinite(MS_BSA) and MS_BSA > 0 else float("nan")

    p_A  = _f_sf(F_A,  df_A,  df_SA)  if math.isfinite(F_A)  else 1.0
    p_B  = _f_sf(F_B,  df_B,  df_BSA) if math.isfinite(F_B)  else 1.0
    p_AB = _f_sf(F_AB, df_AB, df_BSA) if math.isfinite(F_AB) else 1.0

    # ---- partial η² ----
    peta2_A  = SS_A  / (SS_A  + SS_SA)  if (SS_A  + SS_SA)  > 0 else float("nan")
    peta2_B  = SS_B  / (SS_B  + SS_BSA) if (SS_B  + SS_BSA) > 0 else float("nan")
    peta2_AB = SS_AB / (SS_AB + SS_BSA) if (SS_AB + SS_BSA) > 0 else float("nan")

    # ---- partial ω² (Olejnik & Algina, 2003) ----
    denom_ow = SS_total + MS_SA if math.isfinite(MS_SA) and MS_SA > 0 else float("nan")
    pomega2_A  = max(0.0, (SS_A  - df_A  * MS_SA)  / denom_ow) if math.isfinite(denom_ow) else float("nan")
    pomega2_B  = max(0.0, (SS_B  - df_B  * MS_BSA) / denom_ow) if math.isfinite(denom_ow) and math.isfinite(MS_BSA) else float("nan")
    pomega2_AB = max(0.0, (SS_AB - df_AB * MS_BSA) / denom_ow) if math.isfinite(denom_ow) and math.isfinite(MS_BSA) else float("nan")

    # ---- 球形检验（所有被试组合用于 Mauchly W） ----
    data_mat = [[Y(s, bl) for bl in b_levels] for s in complete]
    sphericity = _mauchly_test(data_mat, b)

    # 选择校正 epsilon
    eps_gg = sphericity["epsilon_gg"]
    eps_hf = sphericity["epsilon_hf"]
    sph_violated = (math.isfinite(sphericity.get("p", float("nan"))) and
                    sphericity["p"] < alpha and b > 2)
    if math.isfinite(eps_gg) and eps_gg >= 0.75 and math.isfinite(eps_hf):
        eps_use, eps_label = eps_hf, "Huynh-Feldt"
    else:
        eps_use = eps_gg if math.isfinite(eps_gg) else 1.0
        eps_label = "Greenhouse-Geisser"

    df_B_c    = df_B   * eps_use
    df_AB_c   = df_AB  * eps_use
    df_BSA_c  = df_BSA * eps_use
    p_B_c  = _f_sf(F_B,  df_B_c,  df_BSA_c) if math.isfinite(F_B)  else 1.0
    p_AB_c = _f_sf(F_AB, df_AB_c, df_BSA_c) if math.isfinite(F_AB) else 1.0

    return {
        "between_factor": between,
        "within_factor": within,
        "subject_col": subject,
        "dv": dv,
        "between_levels": a_levels,
        "within_levels": b_levels,
        "n_per_group": n_per_group,
        "N": N,
        "grand_mean": grand,
        "alpha": alpha,
        "SS": {"A": SS_A, "SA": SS_SA, "B": SS_B, "AB": SS_AB, "BSA": SS_BSA, "total": SS_total},
        "df": {"A": df_A, "SA": df_SA, "B": df_B, "AB": df_AB, "BSA": df_BSA},
        "MS": {"A": MS_A, "SA": MS_SA, "B": MS_B, "AB": MS_AB, "BSA": MS_BSA},
        "effects": {
            "A": {"label": between, "F": F_A, "df_num": df_A, "df_den": df_SA,
                  "p": p_A, "partial_eta2": peta2_A, "partial_omega2": pomega2_A,
                  "sig": p_A < alpha},
            "B": {"label": within, "F": F_B, "df_num": df_B, "df_den": df_BSA,
                  "p": p_B, "partial_eta2": peta2_B, "partial_omega2": pomega2_B,
                  "sig": p_B < alpha},
            "AB": {"label": f"{between} × {within}", "F": F_AB,
                   "df_num": df_AB, "df_den": df_BSA,
                   "p": p_AB, "partial_eta2": peta2_AB, "partial_omega2": pomega2_AB,
                   "sig": p_AB < alpha},
        },
        "sphericity": sphericity,
        "sphericity_violated": sph_violated,
        "corrected": {
            "epsilon": eps_use,
            "epsilon_label": eps_label,
            "B":  {"df_num": df_B_c,  "df_den": df_BSA_c, "F": F_B,  "p": p_B_c,
                   "sig": math.isfinite(p_B_c)  and p_B_c  < alpha},
            "AB": {"df_num": df_AB_c, "df_den": df_BSA_c, "F": F_AB, "p": p_AB_c,
                   "sig": math.isfinite(p_AB_c) and p_AB_c < alpha},
        },
        "cell_means": {lvl: dict(mean_AB[lvl]) for lvl in a_levels},
        "group_means": dict(mean_A),
        "condition_means": dict(mean_B),
        "warnings": warnings,
        "_complete_subjs": complete,
        "_subj_group": dict(subj_group),
        "_subj_obs": {s: dict(subj_obs[s]) for s in complete},
    }


# ---------------------------------------------------------------------------
# 简单主效应（被试内因素在各 between 水平的单纯效应）
# ---------------------------------------------------------------------------

def simple_effects_within(result: dict[str, Any]) -> list[dict[str, Any]]:
    """
    计算各 between 水平上被试内因素的单纯主效应（Holm 校正）。
    每次对比：条件 k1 vs k2 做配对 t 检验。
    """
    b_levels = result["within_levels"]
    a_levels = result["between_levels"]
    complete = result["_complete_subjs"]
    subj_group = result["_subj_group"]
    subj_obs = result["_subj_obs"]
    alpha = result["alpha"]
    b = len(b_levels)
    effects = []

    for lvl in a_levels:
        subjs = [s for s in complete if subj_group[s] == lvl]
        n = len(subjs)
        pairs = []
        for i in range(b):
            for j in range(i + 1, b):
                bl1, bl2 = b_levels[i], b_levels[j]
                diffs = [subj_obs[s][bl1] - subj_obs[s][bl2] for s in subjs]
                mean_d = sum(diffs) / n
                var_d = sum((d - mean_d) ** 2 for d in diffs) / (n - 1) if n > 1 else 0.0
                se_d = math.sqrt(var_d / n) if var_d > 0 else 0.0
                t = mean_d / se_d if se_d > 0 else float("nan")
                p = _t_sf2(t, n - 1)
                pairs.append({"bl1": bl1, "bl2": bl2, "mean_diff": mean_d,
                               "t": t, "df": n - 1, "p": p})

        # Holm 校正
        pairs_sorted = sorted(pairs, key=lambda x: x["p"] if math.isfinite(x["p"]) else float("inf"))
        m = len(pairs_sorted)
        for rank, pr in enumerate(pairs_sorted):
            pr["p_holm"] = min(1.0, pr["p"] * (m - rank)) if math.isfinite(pr["p"]) else float("nan")
        # 单调性保证
        for k in range(1, m):
            if pairs_sorted[k]["p_holm"] < pairs_sorted[k - 1]["p_holm"]:
                pairs_sorted[k]["p_holm"] = pairs_sorted[k - 1]["p_holm"]
        for pr in pairs_sorted:
            pr["sig"] = math.isfinite(pr["p_holm"]) and pr["p_holm"] < alpha
        effects.append({"between_level": lvl, "n": n, "comparisons": pairs_sorted})

    return effects


# ---------------------------------------------------------------------------
# APA-7 格式化
# ---------------------------------------------------------------------------

def _fp(x: float, d: int = 2) -> str:
    if not math.isfinite(x):
        return "NA"
    return f"{x:.{d}f}"


def _pval(p: float) -> str:
    if not math.isfinite(p):
        return "NA"
    if p < 0.001:
        return "< .001"
    s = f"{p:.3f}".lstrip("0") or "0"
    return f"= {s}"


def _pval_full(p: float) -> str:
    if not math.isfinite(p):
        return "NA"
    if p < 0.001:
        return "< .001"
    s = f"{p:.3f}"
    return s.lstrip("0") or "0"


def format_apa_mixed(
    result: dict[str, Any],
    post_hoc: list[dict] | None = None,
) -> str:
    """生成 APA-7 Markdown 报告（ANOVA 汇总表 + 文字描述 + 可选事后检验）。"""
    between = result["between_factor"]
    within = result["within_factor"]
    a_levels = result["between_levels"]
    b_levels = result["within_levels"]
    N = result["N"]
    alpha = result["alpha"]
    eff = result["effects"]
    sph = result["sphericity"]
    corr = result["corrected"]
    n_per_group = result["n_per_group"]
    sph_violated = result["sphericity_violated"]

    lines: list[str] = []
    lines.append("## 混合 ANOVA 结果\n")

    # --- 参与者信息 ---
    group_desc = ", ".join(f"{lvl}（*n* = {n_per_group[lvl]}）" for lvl in a_levels)
    lines.append(f"**被试间因素**：{between}（{group_desc}，总 *N* = {N}）")
    lines.append(f"**被试内因素**：{within}（{len(b_levels)} 水平：{', '.join(b_levels)}）")
    lines.append("")

    # --- 单元格均值表 ---
    lines.append("### 单元格均值（*M*）\n")
    header = "| " + between + " | " + " | ".join(b_levels) + " | *M* |"
    sep    = "|" + "---|" * (len(b_levels) + 2)
    lines.append(header)
    lines.append(sep)
    for lvl in a_levels:
        cell_m = result["cell_means"][lvl]
        row_mean = result["group_means"][lvl]
        cells = " | ".join(_fp(cell_m[bl]) for bl in b_levels)
        lines.append(f"| {lvl} | {cells} | {_fp(row_mean)} |")
    cond_row = " | ".join(_fp(result["condition_means"][bl]) for bl in b_levels)
    grand_fp = _fp(result["grand_mean"])
    lines.append(f"| *M* | {cond_row} | {grand_fp} |")
    lines.append("")

    # --- 球形检验 ---
    if len(b_levels) > 2:
        W, chi2_w, df_w, p_w = sph["W"], sph["chi2"], sph["df"], sph["p"]
        eps_gg, eps_hf = sph["epsilon_gg"], sph["epsilon_hf"]
        lines.append("### Mauchly 球形检验\n")
        W_str   = _fp(W, 3) if math.isfinite(W) else "NA"
        chi2_str = _fp(chi2_w, 2) if math.isfinite(chi2_w) else "NA"
        p_str   = _pval_full(p_w) if math.isfinite(p_w) else "NA"
        gg_str  = _fp(eps_gg, 3) if math.isfinite(eps_gg) else "NA"
        hf_str  = _fp(eps_hf, 3) if math.isfinite(eps_hf) else "NA"
        lines.append(
            f"Mauchly's *W* = {W_str}, *χ*²({df_w}) = {chi2_str}, "
            f"*p* {_pval(p_w)}, ε_GG = {gg_str}, ε_HF = {hf_str}。"
        )
        if sph_violated:
            lines.append(
                f"球形性假设被违反（*p* {_pval(p_w)} < .{int(alpha*100):02d}），"
                f"被试内效应采用 {corr['epsilon_label']} 校正（ε = {_fp(corr['epsilon'], 3)}）。"
            )
        else:
            lines.append("球形性假设成立，df 未校正。")
        lines.append("")

    # --- ANOVA 汇总表 ---
    lines.append("### ANOVA 汇总表\n")
    lines.append("| 效应 | SS | df | MS | *F* | *p* | partial η² | partial ω² |")
    lines.append("|---|---|---|---|---|---|---|---|")

    def row(label: str, ss: float, df_: float, ms: float,
            F: float, p: float, eta2: float, omega2: float, corrected: bool = False) -> str:
        df_str = _fp(df_, 2) if not float(df_).is_integer() else str(int(df_))
        if corrected:
            label = label + " ᵉ"
        return (f"| {label} | {_fp(ss)} | {df_str} | {_fp(ms)} | "
                f"{_fp(F, 2)} | {_pval_full(p)} | {_fp(eta2, 3)} | {_fp(omega2, 3)} |")

    # Between-subjects section
    lines.append(row(between, result["SS"]["A"], result["df"]["A"], result["MS"]["A"],
                     eff["A"]["F"], eff["A"]["p"],
                     eff["A"]["partial_eta2"], eff["A"]["partial_omega2"]))
    lines.append(row(f"S({between})", result["SS"]["SA"], result["df"]["SA"], result["MS"]["SA"],
                     float("nan"), float("nan"), float("nan"), float("nan")))

    # Within-subjects section
    if sph_violated:
        lines.append(row(within, result["SS"]["B"], corr["B"]["df_num"], result["MS"]["B"],
                         corr["B"]["F"], corr["B"]["p"],
                         eff["B"]["partial_eta2"], eff["B"]["partial_omega2"], corrected=True))
        lines.append(row(f"{between} × {within}", result["SS"]["AB"], corr["AB"]["df_num"],
                         result["MS"]["AB"], corr["AB"]["F"], corr["AB"]["p"],
                         eff["AB"]["partial_eta2"], eff["AB"]["partial_omega2"], corrected=True))
    else:
        lines.append(row(within, result["SS"]["B"], result["df"]["B"], result["MS"]["B"],
                         eff["B"]["F"], eff["B"]["p"],
                         eff["B"]["partial_eta2"], eff["B"]["partial_omega2"]))
        lines.append(row(f"{between} × {within}", result["SS"]["AB"], result["df"]["AB"],
                         result["MS"]["AB"], eff["AB"]["F"], eff["AB"]["p"],
                         eff["AB"]["partial_eta2"], eff["AB"]["partial_omega2"]))
    lines.append(row(f"{within}×S({between})", result["SS"]["BSA"], result["df"]["BSA"],
                     result["MS"]["BSA"], float("nan"), float("nan"),
                     float("nan"), float("nan")))
    if sph_violated:
        lines.append(f"\n*ᵉ {corr['epsilon_label']} 校正（ε = {_fp(corr['epsilon'], 3)}）*")
    lines.append("")

    # --- APA 文字段落 ---
    lines.append("### APA-7 结果描述\n")

    def _ef_text(eff_key: str, use_corr: bool = False) -> str:
        e = eff[eff_key]
        if use_corr and eff_key in ("B", "AB"):
            c = corr[eff_key]
            F_v, p_v = c["F"], c["p"]
            df_n_v = c["df_num"]
            df_d_v = c["df_den"]
        else:
            F_v, p_v = e["F"], e["p"]
            df_n_v = float(result["df"]["A" if eff_key == "A" else
                                         "B" if eff_key == "B" else "AB"])
            df_d_v = float(result["df"]["SA" if eff_key == "A" else "BSA"])
        df_n_s = _fp(df_n_v, 2) if not float(df_n_v).is_integer() else str(int(df_n_v))
        df_d_s = _fp(df_d_v, 2) if not float(df_d_v).is_integer() else str(int(df_d_v))
        sig = p_v < alpha if math.isfinite(p_v) else False
        label = e["label"]
        eta2_s = _fp(e["partial_eta2"], 3)
        omega2_s = _fp(e["partial_omega2"], 3)
        sig_word = "显著" if sig else "未达显著"
        return (f"{label}的主效应{sig_word}，*F*({df_n_s}, {df_d_s}) = {_fp(F_v, 2)}, "
                f"*p* {_pval(p_v)}, partial η² = {eta2_s}, partial ω² = {omega2_s}。")

    lines.append(_ef_text("A"))
    lines.append(_ef_text("B", use_corr=sph_violated))
    lines.append(_ef_text("AB", use_corr=sph_violated))
    lines.append("")

    # --- 警告 ---
    if result["warnings"]:
        lines.append("### 警告\n")
        for w in result["warnings"]:
            lines.append(f"- {w}")
        lines.append("")

    # --- 事后检验 ---
    if post_hoc:
        lines.append("### 简单主效应（被试内因素 Holm 校正）\n")
        for grp in post_hoc:
            lines.append(f"**{between} = {grp['between_level']}**（*n* = {grp['n']}）\n")
            lines.append("| 对比 | *M*差 | *t* | df | *p* | *p*_Holm | 显著 |")
            lines.append("|---|---|---|---|---|---|---|")
            for pr in grp["comparisons"]:
                sig_mark = "✓" if pr.get("sig") else ""
                lines.append(
                    f"| {pr['bl1']} vs {pr['bl2']} | {_fp(pr['mean_diff'])} | "
                    f"{_fp(pr['t'], 3)} | {int(pr['df'])} | {_pval_full(pr['p'])} | "
                    f"{_pval_full(pr['p_holm'])} | {sig_mark} |"
                )
            lines.append("")

    # --- 参考文献 ---
    lines.append("### 参考文献\n")
    lines.append("- Kirk, R.E. (2013). *Experimental Design*, 4th ed. SAGE.")
    lines.append("- Maxwell, S.A., Delaney, H.D., & Kelley, K. (2017). "
                 "*Designing Experiments and Analyzing Data*, 3rd ed. Routledge.")
    lines.append("- Olejnik, S., & Algina, J. (2003). Generalized eta and omega squared statistics. "
                 "*Psychological Methods*, *8*(4), 434–447.")
    if len(b_levels) > 2:
        lines.append("- Greenhouse, S.W., & Geisser, S. (1959). Estimates of the degree of "
                     "sphericity. *Psychometrika*, *24*(2), 95–112.")
        lines.append("- Huynh, H., & Feldt, L.S. (1976). Estimation of the Box correction. "
                     "*Journal of Educational Statistics*, *1*(1), 69–82.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 序列化辅助（去除私有字段 / NaN/inf → null）
# ---------------------------------------------------------------------------

def _to_json_safe(obj: Any) -> Any:
    if isinstance(obj, float):
        if not math.isfinite(obj):
            return None
        return round(obj, 8)
    if isinstance(obj, dict):
        return {k: _to_json_safe(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [_to_json_safe(v) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# 报告写入
# ---------------------------------------------------------------------------

def write_mixed_report(
    result: dict[str, Any],
    out_dir: str | pathlib.Path,
    post_hoc: list[dict] | None = None,
) -> tuple[pathlib.Path, pathlib.Path]:
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    md_path   = out / "mixed_anova_report.md"
    json_path = out / "mixed_anova_report.json"
    md_path.write_text(format_apa_mixed(result, post_hoc), encoding="utf-8")
    safe = _to_json_safe(result)
    if post_hoc:
        safe["post_hoc"] = _to_json_safe(post_hoc)
    json_path.write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8")
    return md_path, json_path


# ---------------------------------------------------------------------------
# CSV 主入口
# ---------------------------------------------------------------------------

def analyze_mixed(
    csv_path: str | pathlib.Path,
    dv: str,
    between: str,
    within: str,
    subject: str,
    alpha: float = 0.05,
    post_hoc: bool = False,
    out_dir: str | pathlib.Path | None = None,
    return_json: bool = False,
) -> dict[str, Any] | str:
    path = pathlib.Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"找不到文件：{path}")
    with path.open(encoding="utf-8-sig") as f:
        data = list(csv.DictReader(f))
    result = mixed_anova(data, dv, between, within, subject, alpha=alpha)
    ph = simple_effects_within(result) if post_hoc else None
    if out_dir:
        write_mixed_report(result, out_dir, ph)
    if return_json:
        safe = _to_json_safe(result)
        if ph:
            safe["post_hoc"] = _to_json_safe(ph)
        return json.dumps(safe, ensure_ascii=False, indent=2)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def mixed_anova_cli(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="psyclaw mixed-anova",
        description="混合 ANOVA（between × within）：Mauchly / GG/HF ε / partial η² / ω²"
    )
    p.add_argument("csv",       help="输入 CSV（长格式，每行一个观测）")
    p.add_argument("--dv",      required=True, help="因变量列名")
    p.add_argument("--between", required=True, help="被试间因素列名")
    p.add_argument("--within",  required=True, help="被试内因素列名")
    p.add_argument("--subject", required=True, help="被试 ID 列名")
    p.add_argument("--alpha",   type=float, default=0.05, help="显著性水平（默认 .05）")
    p.add_argument("--post-hoc", action="store_true", dest="post_hoc",
                   help="输出各 between 水平上的被试内简单主效应（Holm 校正）")
    p.add_argument("--out",     default=None, help="报告输出目录（默认 notes/）")
    p.add_argument("--json",    action="store_true", help="输出机器可读 JSON")
    args = p.parse_args(argv)

    out_dir = args.out or "notes"
    try:
        result = analyze_mixed(
            args.csv, args.dv, args.between, args.within, args.subject,
            alpha=args.alpha, post_hoc=args.post_hoc,
            out_dir=out_dir,
            return_json=args.json,
        )
    except (FileNotFoundError, ValueError) as e:
        print(f"错误：{e}")
        return 1

    if args.json:
        print(result)
    else:
        ph = simple_effects_within(result) if args.post_hoc else None
        print(format_apa_mixed(result, ph))

    print(f"\n报告已写入：{out_dir}/mixed_anova_report.{{md,json}}")
    return 0
