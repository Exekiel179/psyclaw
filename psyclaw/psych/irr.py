"""评分者间信度 / 组间一致性（Inter-Rater Reliability, IRR）— APA-7（stdlib only）。

提供五类一致性指标：
  - cohens_kappa: 两评分者名义/有序一致性（Cohen's κ，含线性/二次加权）
  - fleiss_kappa: 多评分者名义一致性（Fleiss' κ）
  - krippendorff_alpha: 任意评分者数/缺失数据/任意测量层级（名义/有序/等距/等比），
    内容分析编码者间信度标准量；自助法 95% CI
  - intraclass_correlation: 连续评分组内相关系数（ICC，6 种 Shrout & Fleiss 1979 模型）
  - interpret_kappa / interpret_icc / interpret_krippendorff: 言语解读
    （Landis & Koch 1977；Koo & Li 2016；Krippendorff 2004）
  - APA-7 Markdown 段落 + 汇总表
  - CSV 主入口 + MD/JSON sidecar + CLI

理论依据：
  Cohen, J. (1960). A coefficient of agreement for nominal scales.
    Educational and Psychological Measurement, 20(1), 37–46.
  Cohen, J. (1968). Weighted kappa: Nominal scale agreement with provision for
    scaled disagreement or partial credit. Psychological Bulletin, 70(4), 213–220.
  Fleiss, J. L., Cohen, J., & Everitt, B. S. (1969). Large sample standard errors of
    kappa and weighted kappa. Psychological Bulletin, 72(5), 323–327.
  Fleiss, J. L. (1971). Measuring nominal scale agreement among many raters.
    Psychological Bulletin, 76(5), 378–382.
  Shrout, P. E., & Fleiss, J. L. (1979). Intraclass correlations: Uses in assessing
    rater reliability. Psychological Bulletin, 86(2), 420–428.
  McGraw, K. O., & Wong, S. P. (1996). Forming inferences about some intraclass
    correlation coefficients. Psychological Methods, 1(1), 30–46.
  Landis, J. R., & Koch, G. G. (1977). The measurement of observer agreement for
    categorical data. Biometrics, 33(1), 159–174.
  Koo, T. K., & Li, M. Y. (2016). A guideline of selecting and reporting intraclass
    correlation coefficients for reliability research. Journal of Chiropractic
    Medicine, 15(2), 155–163.

CLI:
  psyclaw irr <data.csv> --method kappa --rater-a colA --rater-b colB
          [--weights linear|quadratic]
  psyclaw irr <data.csv> --method fleiss --raters c1,c2,c3,...
  psyclaw irr <data.csv> --method icc --raters c1,c2,c3,...
  psyclaw irr <data.csv> --method krippendorff --raters c1,c2,c3,...
          [--metric nominal|ordinal|interval|ratio] [--n-boot 2000]
          [--alpha .05] [--json] [--out dir]

理论依据（续）：
  Krippendorff, K. (2004). Content analysis: An introduction to its methodology
    (2nd ed.). Sage.
  Hayes, A. F., & Krippendorff, K. (2007). Answering the call for a standard
    reliability measure for coding data. Communication Methods and Measures,
    1(1), 77–89.
"""

from __future__ import annotations

import csv
import json
import math
import pathlib
from typing import Any

import numpy as np
from scipy import special, stats


# ---------------------------------------------------------------------------
# 分布工具（正态 / F，stdlib only）
# ---------------------------------------------------------------------------

def _norm_cdf(z: float) -> float:
    """标准正态分布 CDF Φ(z) —— scipy.special.ndtr。"""
    return float(special.ndtr(z))


def _norm_sf2(z: float) -> float:
    """正态分布双尾 p 值 —— 2·scipy.stats.norm.sf(|z|)。"""
    if not math.isfinite(z):
        return float("nan")
    return 2.0 * float(stats.norm.sf(abs(z)))


def _betai(a: float, b: float, x: float) -> float:
    """正则化不完全 Beta 函数 I_x(a,b) —— scipy.special.betainc。"""
    if x < 0 or x > 1:
        return float("nan")
    return float(special.betainc(a, b, x))


def _f_cdf(f: float, df1: float, df2: float) -> float:
    """F 分布 CDF —— scipy.stats.f.cdf。"""
    if f <= 0:
        return 0.0
    return float(stats.f.cdf(f, df1, df2))


def _f_sf(f: float, df1: float, df2: float) -> float:
    """F 分布右尾 p 值 —— scipy.stats.f.sf。"""
    if f <= 0:
        return 1.0
    if not math.isfinite(f):
        return 0.0
    return float(stats.f.sf(f, df1, df2))


def _f_ppf(prob: float, df1: float, df2: float) -> float:
    """F 分布分位数 —— scipy.stats.f.ppf。"""
    if not 0 < prob < 1 or df1 <= 0 or df2 <= 0:
        return float("nan")
    return float(stats.f.ppf(prob, df1, df2))


# ---------------------------------------------------------------------------
# Cohen's kappa（两评分者；加权可选）
# ---------------------------------------------------------------------------

def _agreement_weights(k: int, scheme: str | None) -> list[list[float]]:
    """构建 k×k 一致性权重矩阵（w_ii=1，w_ij∈[0,1]）。

    scheme=None       : 名义（w_ij = 1 if i==j else 0）
    scheme="linear"   : 线性 w_ij = 1 − |i−j|/(k−1)
    scheme="quadratic": 二次 w_ij = 1 − (i−j)²/(k−1)²
    """
    if scheme is None:
        return [[1.0 if i == j else 0.0 for j in range(k)] for i in range(k)]
    if k < 2:
        raise ValueError("加权 kappa 需要至少 2 个有序类别")
    denom = (k - 1)
    W = [[0.0] * k for _ in range(k)]
    for i in range(k):
        for j in range(k):
            if scheme == "linear":
                W[i][j] = 1.0 - abs(i - j) / denom
            elif scheme == "quadratic":
                W[i][j] = 1.0 - (i - j) ** 2 / (denom ** 2)
            else:
                raise ValueError(f"未知加权方案: {scheme!r}（应为 linear/quadratic）")
    return W


def _kappa_variance(
    P: list[list[float]],
    pr: list[float],
    pc: list[float],
    W: list[list[float]],
    po_w: float,
    pe_w: float,
    N: int,
) -> float:
    """Cohen's (加权) kappa 大样本渐近方差（Fleiss, Cohen & Everitt 1969）。

    名义权重时退化为经典 Cohen kappa 方差；用于 95% CI 与 Wald z 检验。
    """
    k = len(P)
    if abs(1.0 - pe_w) < 1e-14 or N <= 0:
        return float("nan")
    # 加权行/列边际：w̄_i. = Σ_j pc_j w_ij，w̄_.j = Σ_i pr_i w_ij
    wbar_row = [sum(pc[j] * W[i][j] for j in range(k)) for i in range(k)]
    wbar_col = [sum(pr[i] * W[i][j] for i in range(k)) for j in range(k)]
    one_minus_pe = 1.0 - pe_w
    one_minus_po = 1.0 - po_w
    s = 0.0
    for i in range(k):
        for j in range(k):
            term = W[i][j] * one_minus_pe - (wbar_row[i] + wbar_col[j]) * one_minus_po
            s += P[i][j] * term * term
    s -= (po_w * pe_w - 2.0 * pe_w + po_w) ** 2
    return s / (N * one_minus_pe ** 4)


def cohens_kappa(
    rater_a: list[Any],
    rater_b: list[Any],
    weights: str | None = None,
    categories: list[Any] | None = None,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Cohen's kappa（两评分者一致性）。

    参数
    ----
    rater_a, rater_b : 等长的类别标签列表（可为数值或字符串）
    weights          : None（名义）/ "linear" / "quadratic"（有序加权）
    categories       : 自定义类别顺序（加权时决定序数距离）；缺省则取并集排序
    alpha            : 显著性水平（双尾 CI/检验，默认 .05）

    返回
    ----
    {kappa, se, z, p, ci_lower, ci_upper, p_o, p_e, n, n_categories,
     categories, weights, interpretation}
    """
    n = len(rater_a)
    if n != len(rater_b):
        raise ValueError(f"两评分者长度不一致: {n} vs {len(rater_b)}")
    if n == 0:
        raise ValueError("无数据")

    if categories is None:
        cats = sorted(set(rater_a) | set(rater_b), key=lambda v: (str(type(v)), v))
    else:
        cats = list(categories)
    k = len(cats)
    if k < 2:
        raise ValueError("Cohen's kappa 需要至少 2 个类别")
    idx = {c: i for i, c in enumerate(cats)}

    # 计数混淆矩阵
    counts = [[0] * k for _ in range(k)]
    for a, b in zip(rater_a, rater_b):
        if a not in idx or b not in idx:
            raise ValueError(f"类别 {a!r} 或 {b!r} 不在指定 categories 中")
        counts[idx[a]][idx[b]] += 1

    P = [[counts[i][j] / n for j in range(k)] for i in range(k)]
    pr = [sum(P[i][j] for j in range(k)) for i in range(k)]   # 行边际（rater_a）
    pc = [sum(P[i][j] for i in range(k)) for j in range(k)]   # 列边际（rater_b）

    W = _agreement_weights(k, weights)
    po_w = sum(W[i][j] * P[i][j] for i in range(k) for j in range(k))
    pe_w = sum(W[i][j] * pr[i] * pc[j] for i in range(k) for j in range(k))

    if abs(1.0 - pe_w) < 1e-14:
        kappa = float("nan")
    else:
        kappa = (po_w - pe_w) / (1.0 - pe_w)

    var = _kappa_variance(P, pr, pc, W, po_w, pe_w, n)
    se = math.sqrt(var) if (math.isfinite(var) and var >= 0) else float("nan")

    if math.isfinite(se) and se > 1e-14 and math.isfinite(kappa):
        z = kappa / se
        p_val = _norm_sf2(z)
        z_crit = abs(_inv_norm(1.0 - alpha / 2.0))
        ci_lower = kappa - z_crit * se
        ci_upper = kappa + z_crit * se
    else:
        z = p_val = ci_lower = ci_upper = float("nan")

    return {
        "kappa": _r(kappa),
        "se": _r(se),
        "z": _r(z),
        "p": _r(p_val),
        "ci_lower": _r(ci_lower),
        "ci_upper": _r(ci_upper),
        "p_o": _r(po_w),
        "p_e": _r(pe_w),
        "n": n,
        "n_categories": k,
        "categories": [str(c) for c in cats],
        "weights": weights or "unweighted",
        "alpha": alpha,
        "interpretation": interpret_kappa(kappa),
    }


def _inv_norm(p: float) -> float:
    """标准正态分位数 —— scipy.special.ndtri。"""
    if not 0 < p < 1:
        return float("nan")
    return float(special.ndtri(p))


# ---------------------------------------------------------------------------
# Fleiss' kappa（多评分者，名义）
# ---------------------------------------------------------------------------

def fleiss_kappa(
    counts: list[list[int]],
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Fleiss' kappa（N 个被评对象 × k 个类别的计数矩阵）。

    每行 i 为对象 i 落入各类别的评分者计数；要求每行总和 = n（固定评分者数）。

    返回
    ----
    {kappa, se, z, p, n_subjects, n_raters, n_categories, p_e, p_mean, category_p}
    """
    N = len(counts)
    if N < 2:
        raise ValueError("Fleiss' kappa 需要至少 2 个被评对象")
    k = len(counts[0])
    if k < 2:
        raise ValueError("Fleiss' kappa 需要至少 2 个类别")

    row_sums = [sum(row) for row in counts]
    n = row_sums[0]
    if any(rs != n for rs in row_sums):
        raise ValueError(f"各对象的评分者数不一致（应均为 {n}）: {row_sums}")
    if n < 2:
        raise ValueError("每个对象需要至少 2 名评分者")

    # 各对象一致度 P_i
    P_i = []
    for i in range(N):
        ssq = sum(counts[i][j] ** 2 for j in range(k))
        P_i.append((ssq - n) / (n * (n - 1)))
    P_mean = sum(P_i) / N

    # 类别比例 p_j
    total = N * n
    p_j = [sum(counts[i][j] for i in range(N)) / total for j in range(k)]
    P_e = sum(pj ** 2 for pj in p_j)

    if abs(1.0 - P_e) < 1e-14:
        kappa = float("nan")
    else:
        kappa = (P_mean - P_e) / (1.0 - P_e)

    # 渐近方差（Fleiss 1971，H0: κ=0 的标准误）
    sum_pq = sum(pj * (1.0 - pj) for pj in p_j)
    if sum_pq < 1e-14 or abs(1.0 - P_e) < 1e-14:
        se = z = p_val = float("nan")
    else:
        sum_pq3 = sum(pj * (1.0 - pj) * (1.0 - 2.0 * pj) for pj in p_j)
        var = (2.0 / (N * n * (n - 1))) * (sum_pq ** 2 - sum_pq3) / (sum_pq ** 2)
        se = math.sqrt(var) if var >= 0 else float("nan")
        if math.isfinite(se) and se > 1e-14:
            z = kappa / se
            p_val = _norm_sf2(z)
        else:
            z = p_val = float("nan")

    return {
        "kappa": _r(kappa),
        "se": _r(se),
        "z": _r(z),
        "p": _r(p_val),
        "n_subjects": N,
        "n_raters": n,
        "n_categories": k,
        "p_e": _r(P_e),
        "p_mean": _r(P_mean),
        "category_p": [_r(pj) for pj in p_j],
        "alpha": alpha,
        "interpretation": interpret_kappa(kappa),
    }


def ratings_to_fleiss_counts(
    table: list[list[Any]],
    categories: list[Any] | None = None,
) -> tuple[list[list[int]], list[Any]]:
    """将「对象 × 评分者」的标签表转换为 Fleiss 计数矩阵。

    table[i] 为对象 i 各评分者给出的类别标签（缺失项用 None，自动忽略）。
    返回 (counts, categories)。
    """
    if categories is None:
        seen = set()
        for row in table:
            for v in row:
                if v is not None and v != "":
                    seen.add(v)
        cats = sorted(seen, key=lambda v: (str(type(v)), v))
    else:
        cats = list(categories)
    idx = {c: i for i, c in enumerate(cats)}
    counts = []
    for row in table:
        c = [0] * len(cats)
        for v in row:
            if v is None or v == "":
                continue
            if v not in idx:
                raise ValueError(f"类别 {v!r} 不在指定 categories 中")
            c[idx[v]] += 1
        counts.append(c)
    return counts, cats


# ---------------------------------------------------------------------------
# Krippendorff's alpha（任意评分者数 / 缺失数据 / 任意测量层级）
# ---------------------------------------------------------------------------

def _kripp_delta2(metric: str, vals: list[Any], c: int, k: int,
                  n_marg: list[float]) -> float:
    """值索引 c、k 之间的差异函数 δ²（Krippendorff 2004）。

    nominal  : δ² = 0 if c==k else 1
    interval : δ² = (v_c − v_k)²
    ratio    : δ² = ((v_c − v_k)/(v_c + v_k))²
    ordinal  : δ² = (Σ_{g=c..k} n_g − (n_c + n_k)/2)²（n_g 为边际频数）
    """
    if c == k:
        return 0.0
    if metric == "nominal":
        return 1.0
    vc, vk = float(vals[c]), float(vals[k])
    if metric == "interval":
        return (vc - vk) ** 2
    if metric == "ratio":
        s = vc + vk
        if s == 0:
            return 0.0
        return ((vc - vk) / s) ** 2
    if metric == "ordinal":
        lo, hi = (c, k) if c < k else (k, c)
        g = sum(n_marg[t] for t in range(lo, hi + 1))
        half = (n_marg[c] + n_marg[k]) / 2.0
        d = g - half
        return d * d
    raise ValueError(f"未知 metric: {metric!r}（应为 nominal/ordinal/interval/ratio）")


def _krippendorff_core(
    units: list[list[Any]],
    metric: str,
    vals: list[Any],
) -> dict[str, float]:
    """Krippendorff's alpha 点估计（基于一致性/重合矩阵）。

    units : 单位（行）× 评分者（列）；缺失项为 None/""，自动按可配对处理。
    vals  : 固定的取值域（顺序对 ordinal/interval/ratio 有意义；bootstrap 复用）。

    返回 {alpha, n_total, n_units_pairable, d_o, d_e}。
    """
    idx = {v: i for i, v in enumerate(vals)}
    K = len(vals)
    o = [[0.0] * K for _ in range(K)]
    n_units_pairable = 0
    for u in units:
        valid = [v for v in u if v is not None and v != ""]
        m = len(valid)
        if m < 2:
            continue
        n_units_pairable += 1
        w = 1.0 / (m - 1)
        for a in range(m):
            ia = idx[valid[a]]
            for b in range(m):
                if a == b:
                    continue
                o[ia][idx[valid[b]]] += w

    n_marg = [sum(row) for row in o]
    n_total = sum(n_marg)
    if n_total < 2:
        return {"alpha": float("nan"), "n_total": n_total,
                "n_units_pairable": n_units_pairable,
                "d_o": float("nan"), "d_e": float("nan")}

    num = 0.0
    den = 0.0
    for c in range(K):
        nc = n_marg[c]
        for kk in range(K):
            if c == kk:
                continue
            d2 = _kripp_delta2(metric, vals, c, kk, n_marg)
            num += o[c][kk] * d2
            den += nc * n_marg[kk] * d2

    if den <= 0:
        # 无变异（仅单一取值）：期望不一致为 0，α 无定义
        return {"alpha": float("nan"), "n_total": n_total,
                "n_units_pairable": n_units_pairable,
                "d_o": num / n_total, "d_e": 0.0}

    d_obs = num / n_total
    d_exp = den / (n_total * (n_total - 1))
    a = 1.0 - d_obs / d_exp
    return {"alpha": a, "n_total": n_total, "n_units_pairable": n_units_pairable,
            "d_o": d_obs, "d_e": d_exp}


def _percentile(sorted_vals: list[float], q: float) -> float:
    """线性插值分位数（sorted_vals 已升序，q∈[0,1]）。"""
    if not sorted_vals:
        return float("nan")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def krippendorff_alpha(
    units: list[list[Any]],
    metric: str = "nominal",
    value_domain: list[Any] | None = None,
    n_boot: int = 2000,
    seed: int = 20240601,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Krippendorff's alpha（任意评分者数 / 缺失数据 / 任意测量层级）。

    参数
    ----
    units        : 单位（行）× 评分者（列）的标签表；缺失用 None/""。
                   一个单位需 ≥2 个有效评分才「可配对」，否则不计入。
    metric       : "nominal"（默认）/ "ordinal" / "interval" / "ratio"
                   ——ordinal/interval/ratio 要求取值可转 float。
    value_domain : 自定义取值域（顺序对 ordinal/interval/ratio 有意义）；
                   缺省自数据抽取（数值升序 / 名义按类型+字符串序）。
    n_boot       : 自助法重抽样次数（>0 时给出 95% 百分位 CI）；0 关闭。
    seed         : 自助法随机种子（默认固定，保证结果可复现）。
    alpha        : 置信区间显著性水平（双尾，默认 .05）。

    返回
    ----
    {alpha, ci_lower, ci_upper, metric, n_units, n_units_pairable,
     n_pairable_values, n_categories, categories, d_observed, d_expected,
     n_boot, alpha_level, interpretation}
    """
    if metric not in ("nominal", "ordinal", "interval", "ratio"):
        raise ValueError(
            f"未知 metric: {metric!r}（应为 nominal/ordinal/interval/ratio）")
    if not units:
        raise ValueError("无数据")

    if value_domain is not None:
        vals = list(value_domain)
    else:
        seen = set()
        for u in units:
            for v in u:
                if v is not None and v != "":
                    seen.add(v)
        if not seen:
            raise ValueError("无有效评分")
        if metric == "nominal":
            vals = sorted(seen, key=lambda v: (str(type(v)), str(v)))
        else:
            vals = sorted(seen)  # 数值升序（ordinal 距离依赖取值顺序）

    domain_set = set(vals)
    for u in units:
        for v in u:
            if v is not None and v != "" and v not in domain_set:
                raise ValueError(f"值 {v!r} 不在 value_domain 中")

    core = _krippendorff_core(units, metric, vals)
    point = core["alpha"]

    ci_lower = ci_upper = float("nan")
    n_boot_used = 0
    usable = [u for u in units
              if sum(1 for v in u if v is not None and v != "") >= 2]
    if math.isfinite(point) and len(usable) >= 2 and n_boot and n_boot > 0:
        import random
        rng = random.Random(seed)
        U = len(usable)
        boot_vals: list[float] = []
        for _ in range(n_boot):
            sample = [usable[rng.randrange(U)] for _ in range(U)]
            c2 = _krippendorff_core(sample, metric, vals)
            if math.isfinite(c2["alpha"]):
                boot_vals.append(c2["alpha"])
        if boot_vals:
            boot_vals.sort()
            ci_lower = _percentile(boot_vals, alpha / 2.0)
            ci_upper = _percentile(boot_vals, 1.0 - alpha / 2.0)
            n_boot_used = len(boot_vals)

    return {
        "alpha": _r(point),
        "ci_lower": _r(ci_lower),
        "ci_upper": _r(ci_upper),
        "metric": metric,
        "n_units": len(units),
        "n_units_pairable": core["n_units_pairable"],
        "n_pairable_values": _r(core["n_total"]),
        "n_categories": len(vals),
        "categories": [str(v) for v in vals],
        "d_observed": _r(core["d_o"]),
        "d_expected": _r(core["d_e"]),
        "n_boot": n_boot_used,
        "alpha_level": alpha,
        "interpretation": interpret_krippendorff(point),
    }


# ---------------------------------------------------------------------------
# ICC（Shrout & Fleiss 1979；McGraw & Wong 1996）
# ---------------------------------------------------------------------------

def _icc_ms(data: list[list[float]]) -> dict[str, float]:
    """双向 ANOVA 均方分解。data[i] 为对象 i 的 k 个评分（无缺失，均衡）。"""
    n = len(data)
    k = len(data[0])
    grand = sum(sum(row) for row in data) / (n * k)
    row_means = [sum(row) / k for row in data]
    col_means = [sum(data[i][j] for i in range(n)) / n for j in range(k)]

    ss_rows = k * sum((rm - grand) ** 2 for rm in row_means)
    ss_cols = n * sum((cm - grand) ** 2 for cm in col_means)
    ss_total = sum((data[i][j] - grand) ** 2 for i in range(n) for j in range(k))
    ss_error = ss_total - ss_rows - ss_cols
    ss_within = ss_total - ss_rows

    msr = ss_rows / (n - 1) if n > 1 else float("nan")
    msc = ss_cols / (k - 1) if k > 1 else float("nan")
    mse = ss_error / ((n - 1) * (k - 1)) if (n > 1 and k > 1) else float("nan")
    msw = ss_within / (n * (k - 1)) if k > 1 else float("nan")
    return {"MSR": msr, "MSC": msc, "MSE": mse, "MSW": msw, "n": n, "k": k}


def intraclass_correlation(
    data: list[list[float]],
    alpha: float = 0.05,
) -> dict[str, Any]:
    """六种 ICC（Shrout & Fleiss 1979）。

    data[i] 为对象 i 的 k 个评分者评分（要求均衡、无缺失）。

    返回每种模型 {icc, f, df1, df2, p, ci_lower, ci_upper}，键名：
      icc1_1 / icc2_1 / icc3_1（单次评分）
      icc1_k / icc2_k / icc3_k（k 次平均评分）
    并附 ms（均方分解）、n_subjects、n_raters。
    """
    n = len(data)
    if n < 2:
        raise ValueError("ICC 需要至少 2 个对象")
    k = len(data[0])
    if k < 2:
        raise ValueError("ICC 需要至少 2 个评分者")
    if any(len(row) != k for row in data):
        raise ValueError("ICC 要求均衡设计（各对象评分者数相同）")

    ms = _icc_ms(data)
    MSR, MSC, MSE, MSW = ms["MSR"], ms["MSC"], ms["MSE"], ms["MSW"]

    def _ci_one_way(icc: float) -> tuple[float, float]:
        # ICC(1,1) Shrout & Fleiss 1979
        f_obs = MSR / MSW if MSW > 0 else float("inf")
        df1, df2 = n - 1, n * (k - 1)
        fl = f_obs / _f_ppf(1 - alpha / 2, df1, df2)
        fu = f_obs * _f_ppf(1 - alpha / 2, df2, df1)
        lo = (fl - 1) / (fl + (k - 1))
        hi = (fu - 1) / (fu + (k - 1))
        return lo, hi

    def _ci_consistency(icc: float) -> tuple[float, float]:
        # ICC(3,1) Shrout & Fleiss 1979
        f_obs = MSR / MSE if MSE > 0 else float("inf")
        df1, df2 = n - 1, (n - 1) * (k - 1)
        fl = f_obs / _f_ppf(1 - alpha / 2, df1, df2)
        fu = f_obs * _f_ppf(1 - alpha / 2, df2, df1)
        lo = (fl - 1) / (fl + (k - 1))
        hi = (fu - 1) / (fu + (k - 1))
        return lo, hi

    def _ci_agreement(icc: float) -> tuple[float, float]:
        # ICC(2,1) Shrout & Fleiss 1979（含 MSC，自由度近似）
        if not math.isfinite(icc) or MSE <= 0:
            return float("nan"), float("nan")
        a = (k * icc) / (n * (1 - icc)) if abs(1 - icc) > 1e-14 else float("inf")
        b = 1 + (k * icc * (n - 1)) / (n * (1 - icc)) if abs(1 - icc) > 1e-14 else float("inf")
        if not (math.isfinite(a) and math.isfinite(b)):
            return float("nan"), float("nan")
        num = (a * MSC + b * MSE) ** 2
        den = (a * MSC) ** 2 / (k - 1) + (b * MSE) ** 2 / ((n - 1) * (k - 1))
        v = num / den if den > 0 else float("nan")
        if not math.isfinite(v) or v <= 0:
            return float("nan"), float("nan")
        f_lo = _f_ppf(1 - alpha / 2, n - 1, v)
        f_hi = _f_ppf(1 - alpha / 2, v, n - 1)
        lo = n * (MSR - f_lo * MSE) / (f_lo * (k * MSC + (k * n - k - n) * MSE) + n * MSR)
        hi = n * (f_hi * MSR - MSE) / (k * MSC + (k * n - k - n) * MSE + n * f_hi * MSR)
        return lo, hi

    def _avg(lo: float, hi: float) -> tuple[float, float]:
        # 单次→平均：ICC_k = k·ICC / (1 + (k−1)·ICC)（Spearman-Brown）
        def sb(x: float) -> float:
            d = 1 + (k - 1) * x
            return (k * x) / d if abs(d) > 1e-14 else float("nan")
        return sb(lo), sb(hi)

    # 点估计
    icc1_1 = (MSR - MSW) / (MSR + (k - 1) * MSW) if (MSR + (k - 1) * MSW) != 0 else float("nan")
    icc2_1 = ((MSR - MSE) / (MSR + (k - 1) * MSE + (k / n) * (MSC - MSE))
              if (MSR + (k - 1) * MSE + (k / n) * (MSC - MSE)) != 0 else float("nan"))
    icc3_1 = (MSR - MSE) / (MSR + (k - 1) * MSE) if (MSR + (k - 1) * MSE) != 0 else float("nan")
    icc1_k = (MSR - MSW) / MSR if MSR != 0 else float("nan")
    icc2_k = ((MSR - MSE) / (MSR + (MSC - MSE) / n)
              if (MSR + (MSC - MSE) / n) != 0 else float("nan"))
    icc3_k = (MSR - MSE) / MSR if MSR != 0 else float("nan")

    # F 检验
    f1 = MSR / MSW if MSW > 0 else float("inf")
    f23 = MSR / MSE if MSE > 0 else float("inf")
    df1_oneway, df2_oneway = n - 1, n * (k - 1)
    df1_two, df2_two = n - 1, (n - 1) * (k - 1)
    p1 = _f_sf(f1, df1_oneway, df2_oneway)
    p23 = _f_sf(f23, df1_two, df2_two)

    ci11 = _ci_one_way(icc1_1)
    ci31 = _ci_consistency(icc3_1)
    ci21 = _ci_agreement(icc2_1)
    ci1k = _avg(*ci11)
    ci3k = _avg(*ci31)
    ci2k = _avg(*ci21)

    def pack(icc, f, d1, d2, p, ci):
        return {
            "icc": _r(icc), "f": _r(f), "df1": d1, "df2": _r(d2),
            "p": _r(p), "ci_lower": _r(ci[0]), "ci_upper": _r(ci[1]),
        }

    return {
        "icc1_1": pack(icc1_1, f1, df1_oneway, df2_oneway, p1, ci11),
        "icc2_1": pack(icc2_1, f23, df1_two, df2_two, p23, ci21),
        "icc3_1": pack(icc3_1, f23, df1_two, df2_two, p23, ci31),
        "icc1_k": pack(icc1_k, f1, df1_oneway, df2_oneway, p1, ci1k),
        "icc2_k": pack(icc2_k, f23, df1_two, df2_two, p23, ci2k),
        "icc3_k": pack(icc3_k, f23, df1_two, df2_two, p23, ci3k),
        "ms": {kk: _r(vv) for kk, vv in ms.items()},
        "n_subjects": n,
        "n_raters": k,
        "alpha": alpha,
    }


# ---------------------------------------------------------------------------
# 言语解读
# ---------------------------------------------------------------------------

def interpret_kappa(k: float) -> str:
    """Landis & Koch (1977) kappa 解读。"""
    if not math.isfinite(k):
        return "无法计算"
    if k < 0:
        return "差（低于偶然，Poor）"
    if k <= 0.20:
        return "轻微（Slight）"
    if k <= 0.40:
        return "尚可（Fair）"
    if k <= 0.60:
        return "中等（Moderate）"
    if k <= 0.80:
        return "较强（Substantial）"
    return "几近完美（Almost perfect）"


def interpret_icc(v: float) -> str:
    """Koo & Li (2016) ICC 解读。"""
    if not math.isfinite(v):
        return "无法计算"
    if v < 0.50:
        return "差（Poor）"
    if v < 0.75:
        return "中等（Moderate）"
    if v < 0.90:
        return "良好（Good）"
    return "优秀（Excellent）"


def interpret_krippendorff(a: float) -> str:
    """Krippendorff (2004) α 经验门槛解读。"""
    if not math.isfinite(a):
        return "无法计算"
    if a >= 0.80:
        return "可靠（≥.80，Reliable）"
    if a >= 0.667:
        return "暂定可靠（.667–.80，需谨慎，Tentative）"
    return "不可靠（<.667，Unreliable）"


# ---------------------------------------------------------------------------
# APA-7 格式化
# ---------------------------------------------------------------------------

def _r(x: Any) -> Any:
    if isinstance(x, float):
        if math.isnan(x) or math.isinf(x):
            return x
        return round(x, 6)
    return x


def _p_str(p: float | None) -> str:
    if p is None or not isinstance(p, (int, float)) or not math.isfinite(p):
        return "—"
    if p < 0.001:
        return "< .001"
    return "= " + f"{p:.3f}".lstrip("0")


def _f3(x: Any) -> str:
    if x is None or not isinstance(x, (int, float)) or not math.isfinite(x):
        return "—"
    s = f"{x:.3f}"
    if s.startswith("0."):
        s = s[1:]
    elif s.startswith("-0."):
        s = "-" + s[2:]
    return s


def format_apa_kappa(result: dict[str, Any], method: str = "cohen") -> str:
    """Cohen's / Fleiss' kappa 的 APA-7 Markdown 段落。"""
    if method == "fleiss":
        kappa = result["kappa"]
        z = result.get("z")
        p = result.get("p")
        N = result["n_subjects"]
        n_r = result["n_raters"]
        kc = result["n_categories"]
        lines = ["## Fleiss' kappa（多评分者一致性）", ""]
        lines.append(f"- 被评对象 *N* = {N}，评分者数 = {n_r}，类别数 = {kc}")
        lines.append("")
        lines.append(
            f"{n_r} 名评分者对 {N} 个对象的名义一致性以 Fleiss' κ 评估，"
            f"κ = {_f3(kappa)}，*z* = {_f3(z)}，*p* {_p_str(p)}，"
            f"一致性水平为「{result.get('interpretation', '')}」（Landis & Koch, 1977）。"
        )
        ref = (
            "Fleiss, J. L. (1971). Measuring nominal scale agreement among many "
            "raters. *Psychological Bulletin, 76*(5), 378–382."
        )
    else:
        kappa = result["kappa"]
        se = result.get("se")
        z = result.get("z")
        p = result.get("p")
        ci_lo = result.get("ci_lower")
        ci_hi = result.get("ci_upper")
        n = result["n"]
        w = result.get("weights", "unweighted")
        wlabel = {"unweighted": "名义（未加权）", "linear": "线性加权",
                  "quadratic": "二次加权"}.get(w, w)
        lines = ["## Cohen's kappa（两评分者一致性）", ""]
        lines.append(f"- 配对观测 *N* = {n}，类别数 = {result['n_categories']}，"
                     f"加权方案 = {wlabel}")
        lines.append(f"- 观测一致率 *p*ₒ = {_f3(result.get('p_o'))}，"
                     f"期望一致率 *p*ₑ = {_f3(result.get('p_e'))}")
        lines.append("")
        ci_str = (f"[{_f3(ci_lo)}, {_f3(ci_hi)}]"
                  if ci_lo is not None and math.isfinite(ci_lo) else "—")
        lines.append(
            f"两评分者一致性以 Cohen's κ 评估，κ = {_f3(kappa)}"
            f"（*SE* = {_f3(se)}），*z* = {_f3(z)}，*p* {_p_str(p)}，"
            f"95% CI {ci_str}，一致性水平为「{result.get('interpretation', '')}」"
            f"（Landis & Koch, 1977）。"
        )
        ref = (
            "Cohen, J. (1960). A coefficient of agreement for nominal scales. "
            "*Educational and Psychological Measurement, 20*(1), 37–46."
        )

    lines += ["", "### 参考文献", "", ref,
              "", "Landis, J. R., & Koch, G. G. (1977). The measurement of observer "
              "agreement for categorical data. *Biometrics, 33*(1), 159–174."]
    return "\n".join(lines)


_ICC_LABELS = {
    "icc1_1": "ICC(1,1) 单次·单向随机",
    "icc2_1": "ICC(2,1) 单次·双向随机（绝对一致）",
    "icc3_1": "ICC(3,1) 单次·双向混合（一致性）",
    "icc1_k": "ICC(1,k) 平均·单向随机",
    "icc2_k": "ICC(2,k) 平均·双向随机（绝对一致）",
    "icc3_k": "ICC(3,k) 平均·双向混合（一致性）",
}


def format_apa_icc(result: dict[str, Any]) -> str:
    """ICC 六模型的 APA-7 Markdown 三线表 + 段落。"""
    N = result["n_subjects"]
    k = result["n_raters"]
    lines = [f"## 组内相关系数（ICC，*N* = {N} 个对象 × {k} 名评分者）", ""]
    lines.append("| 模型 | ICC | *F* | *df*₁ | *df*₂ | *p* | 95% CI |")
    lines.append("|------|-----|-----|-------|-------|-----|--------|")
    for key in ("icc1_1", "icc2_1", "icc3_1", "icc1_k", "icc2_k", "icc3_k"):
        m = result[key]
        ci = (f"[{_f3(m['ci_lower'])}, {_f3(m['ci_upper'])}]"
              if m.get("ci_lower") is not None and isinstance(m["ci_lower"], (int, float))
              and math.isfinite(m["ci_lower"]) else "—")
        f_str = _f3(m["f"]) if isinstance(m["f"], (int, float)) and math.isfinite(m["f"]) else "—"
        lines.append(
            f"| {_ICC_LABELS[key]} | {_f3(m['icc'])} | {f_str} | "
            f"{m['df1']} | {_f3(m['df2'])} | {_p_str(m['p'])} | {ci} |"
        )
    # 主报告通常取 ICC(2,1) 或 ICC(3,1)
    main = result["icc3_1"]
    lines += ["", (
        f"评分者间一致性以 ICC(3,1) 报告（双向混合效应，绝对一致性模型；"
        f"若关注绝对一致请改用 ICC(2,1)）：ICC = {_f3(main['icc'])}，"
        f"*F*({main['df1']}, {_f3(main['df2'])}) = {_f3(main['f'])}，"
        f"*p* {_p_str(main['p'])}，一致性水平为「{interpret_icc(main['icc'])}」"
        f"（Koo & Li, 2016）。"
    )]
    lines += ["", "### 参考文献", "",
              "Shrout, P. E., & Fleiss, J. L. (1979). Intraclass correlations: Uses "
              "in assessing rater reliability. *Psychological Bulletin, 86*(2), 420–428.",
              "",
              "Koo, T. K., & Li, M. Y. (2016). A guideline of selecting and reporting "
              "intraclass correlation coefficients for reliability research. *Journal "
              "of Chiropractic Medicine, 15*(2), 155–163."]
    return "\n".join(lines)


_KRIPP_METRIC_LABELS = {
    "nominal": "名义", "ordinal": "有序", "interval": "等距", "ratio": "等比",
}


def format_apa_krippendorff(result: dict[str, Any]) -> str:
    """Krippendorff's alpha 的 APA-7 Markdown 段落。"""
    a = result["alpha"]
    metric = result.get("metric", "nominal")
    mlabel = _KRIPP_METRIC_LABELS.get(metric, metric)
    ci_lo, ci_hi = result.get("ci_lower"), result.get("ci_upper")
    lines = ["## Krippendorff's alpha（评分者间一致性）", ""]
    lines.append(
        f"- 编码单位 *N* = {result['n_units']}"
        f"（可配对 {result['n_units_pairable']}），"
        f"测量层级 = {mlabel}，取值/类别数 = {result['n_categories']}"
    )
    lines.append("")
    has_ci = (isinstance(ci_lo, (int, float)) and math.isfinite(ci_lo)
              and isinstance(ci_hi, (int, float)) and math.isfinite(ci_hi))
    ci_str = (f"，95% CI [{_f3(ci_lo)}, {_f3(ci_hi)}]"
              f"（{result.get('n_boot', 0)} 次自助重抽样）" if has_ci else "")
    lines.append(
        f"以 Krippendorff's α（{mlabel}差异函数）评估编码者间一致性，"
        f"α = {_f3(a)}{ci_str}，一致性水平为「{result.get('interpretation', '')}」。"
        f"Krippendorff (2004) 建议 α ≥ .80 为可靠，.667–.80 仅可作暂定结论。"
    )
    lines += ["", "### 参考文献", "",
              "Krippendorff, K. (2004). *Content analysis: An introduction to its "
              "methodology* (2nd ed.). Sage.",
              "",
              "Hayes, A. F., & Krippendorff, K. (2007). Answering the call for a "
              "standard reliability measure for coding data. *Communication Methods "
              "and Measures, 1*(1), 77–89."]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON sidecar
# ---------------------------------------------------------------------------

def _clean_json(obj: Any) -> Any:
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _clean_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_json(v) for v in obj]
    return obj


def write_irr_report(
    result: dict[str, Any],
    formatted: str,
    out_dir: str | pathlib.Path,
    stem: str = "irr_report",
) -> dict[str, str]:
    """写 MD + JSON sidecar，返回 {md, json} 路径。"""
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    md_path = out / f"{stem}.md"
    json_path = out / f"{stem}.json"
    md_path.write_text(formatted, encoding="utf-8")
    clean = _clean_json({k: v for k, v in result.items() if not k.startswith("_")})
    json_path.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"md": str(md_path), "json": str(json_path)}


# ---------------------------------------------------------------------------
# CSV 主入口
# ---------------------------------------------------------------------------

def _read_csv(csv_path: str) -> list[dict[str, str]]:
    path = pathlib.Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"找不到数据文件: {csv_path}")
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError("CSV 文件为空或无数据行")
    return rows


def _to_float(s: str) -> float:
    return float(s)


def analyze_irr(
    csv_path: str,
    method: str,
    rater_a: str | None = None,
    rater_b: str | None = None,
    raters: list[str] | None = None,
    weights: str | None = None,
    metric: str = "nominal",
    n_boot: int = 2000,
    seed: int = 20240601,
    alpha: float = 0.05,
    out_dir: str = "notes",
    return_json: bool = False,
) -> dict[str, Any]:
    """CSV 主入口：读取数据 → 计算 IRR → 写 sidecar。

    method="kappa"        : 需 rater_a/rater_b 两列
    method="fleiss"       : 需 raters（≥2 列，类别标签）
    method="icc"          : 需 raters（≥2 列，连续评分）
    method="krippendorff" : 需 raters（≥2 列）；metric 决定差异函数
    """
    rows = _read_csv(csv_path)
    header = set(rows[0].keys())

    if method == "kappa":
        if not rater_a or not rater_b:
            raise ValueError("kappa 需要 --rater-a 与 --rater-b")
        for c in (rater_a, rater_b):
            if c not in header:
                raise ValueError(f"CSV 中找不到列: {c}")
        a, b = [], []
        n_excluded = 0
        for row in rows:
            va, vb = row.get(rater_a, ""), row.get(rater_b, "")
            if va == "" or vb == "" or va is None or vb is None:
                n_excluded += 1
                continue
            a.append(va)
            b.append(vb)
        result = cohens_kappa(a, b, weights=weights, alpha=alpha)
        result["n_excluded"] = n_excluded
        result["method"] = "cohen"
        formatted = format_apa_kappa(result, method="cohen")

    elif method == "fleiss":
        if not raters or len(raters) < 2:
            raise ValueError("fleiss 需要 --raters 指定至少 2 列")
        for c in raters:
            if c not in header:
                raise ValueError(f"CSV 中找不到列: {c}")
        table = []
        n_excluded = 0
        for row in rows:
            vals = [row.get(c, "") for c in raters]
            vals = [v if (v != "" and v is not None) else None for v in vals]
            if all(v is None for v in vals):
                n_excluded += 1
                continue
            table.append(vals)
        counts, cats = ratings_to_fleiss_counts(table)
        result = fleiss_kappa(counts, alpha=alpha)
        result["categories"] = [str(c) for c in cats]
        result["n_excluded"] = n_excluded
        result["method"] = "fleiss"
        formatted = format_apa_kappa(result, method="fleiss")

    elif method == "icc":
        if not raters or len(raters) < 2:
            raise ValueError("icc 需要 --raters 指定至少 2 列")
        for c in raters:
            if c not in header:
                raise ValueError(f"CSV 中找不到列: {c}")
        data = []
        n_excluded = 0
        for row in rows:
            try:
                vals = [_to_float(row[c]) for c in raters]
            except (ValueError, KeyError, TypeError):
                n_excluded += 1
                continue
            data.append(vals)
        result = intraclass_correlation(data, alpha=alpha)
        result["n_excluded"] = n_excluded
        result["method"] = "icc"
        formatted = format_apa_icc(result)

    elif method in ("krippendorff", "alpha"):
        if not raters or len(raters) < 2:
            raise ValueError("krippendorff 需要 --raters 指定至少 2 列")
        for c in raters:
            if c not in header:
                raise ValueError(f"CSV 中找不到列: {c}")
        units = []
        n_excluded = 0
        for row in rows:
            vals: list[Any] = []
            for c in raters:
                v = row.get(c, "")
                if v is None or v == "":
                    vals.append(None)
                elif metric == "nominal":
                    vals.append(v)
                else:
                    try:
                        vals.append(_to_float(v))
                    except (ValueError, TypeError):
                        vals.append(None)
            if all(v is None for v in vals):
                n_excluded += 1
                continue
            units.append(vals)
        result = krippendorff_alpha(
            units, metric=metric, n_boot=n_boot, seed=seed, alpha=alpha)
        result["n_excluded"] = n_excluded
        result["method"] = "krippendorff"
        formatted = format_apa_krippendorff(result)

    else:
        raise ValueError(
            f"未知 method: {method!r}（应为 kappa/fleiss/icc/krippendorff）")

    result["raters"] = raters
    paths = write_irr_report(result, formatted, out_dir)
    result["_formatted"] = formatted
    result["_paths"] = paths

    if return_json:
        return _clean_json({k: v for k, v in result.items() if not k.startswith("_")})
    return result


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def irr_cli(argv: list[str]) -> int:
    import argparse
    from psyclaw import ui

    ap = argparse.ArgumentParser(
        prog="psyclaw irr",
        description="评分者间信度（Cohen's / Fleiss' kappa / ICC，APA-7，stdlib only）",
    )
    ap.add_argument("csv", help="输入数据 CSV 路径")
    ap.add_argument("--method", required=True,
                    choices=["kappa", "fleiss", "icc", "krippendorff"],
                    help="kappa(两评分者) | fleiss(多评分者名义) | icc(连续评分) | "
                         "krippendorff(任意评分者/缺失/层级)")
    ap.add_argument("--rater-a", dest="rater_a", help="kappa：评分者 A 列名")
    ap.add_argument("--rater-b", dest="rater_b", help="kappa：评分者 B 列名")
    ap.add_argument("--raters", help="fleiss/icc/krippendorff：评分者列名，逗号分隔（≥2 列）")
    ap.add_argument("--weights", choices=["linear", "quadratic"],
                    help="kappa：有序加权方案（默认名义未加权）")
    ap.add_argument("--metric", choices=["nominal", "ordinal", "interval", "ratio"],
                    default="nominal",
                    help="krippendorff：差异函数/测量层级（默认 nominal）")
    ap.add_argument("--n-boot", dest="n_boot", type=int, default=2000,
                    help="krippendorff：自助法 CI 重抽样次数（默认 2000，0 关闭）")
    ap.add_argument("--alpha", type=float, default=0.05, help="显著性水平（默认 .05）")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    ap.add_argument("--out", default="notes", help="报告输出目录（默认 notes/）")

    args = ap.parse_args(argv)
    raters = [c.strip() for c in args.raters.split(",") if c.strip()] if args.raters else None

    try:
        result = analyze_irr(
            args.csv, args.method,
            rater_a=args.rater_a, rater_b=args.rater_b, raters=raters,
            weights=args.weights, metric=args.metric, n_boot=args.n_boot,
            alpha=args.alpha, out_dir=args.out,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(ui.err(str(exc)))
        return 1

    if args.json:
        clean = _clean_json({k: v for k, v in result.items() if not k.startswith("_")})
        print(json.dumps(clean, ensure_ascii=False, indent=2))
        return 0

    if args.method == "icc":
        print(ui.title("组内相关系数（ICC）"))
        print(ui.rule())
        print(f"  对象 N      : {result['n_subjects']}  |  评分者: {result['n_raters']}"
              f"  |  排除: {result.get('n_excluded', 0)}")
        print()
        for key in ("icc1_1", "icc2_1", "icc3_1", "icc1_k", "icc2_k", "icc3_k"):
            m = result[key]
            icc = m["icc"]
            icc_s = f"{icc:.4f}" if isinstance(icc, (int, float)) and math.isfinite(icc) else "—"
            print(f"  {_ICC_LABELS[key]:<34} {icc_s}  ({interpret_icc(icc) if isinstance(icc,(int,float)) else ''})")
    elif args.method == "krippendorff":
        a = result["alpha"]
        print(ui.title("Krippendorff's alpha"))
        print(ui.rule())
        print(f"  单位 N      : {result['n_units']}  |  可配对: {result['n_units_pairable']}"
              f"  |  层级: {result['metric']}  |  取值: {result['n_categories']}"
              f"  |  排除: {result.get('n_excluded', 0)}")
        print()
        a_s = f"{a:.4f}" if isinstance(a, (int, float)) and math.isfinite(a) else "—"
        print(f"  alpha       : {a_s}  ({result.get('interpretation', '')})")
        ci_lo = result.get("ci_lower")
        if isinstance(ci_lo, (int, float)) and math.isfinite(ci_lo):
            print(f"  95% CI      : [{ci_lo:.4f}, {result['ci_upper']:.4f}]"
                  f"  ({result.get('n_boot', 0)} 次自助)")
    else:
        kappa = result["kappa"]
        title = "Cohen's kappa" if args.method == "kappa" else "Fleiss' kappa"
        print(ui.title(title))
        print(ui.rule())
        if args.method == "kappa":
            print(f"  有效 N      : {result['n']}  |  排除: {result.get('n_excluded', 0)}"
                  f"  |  类别: {result['n_categories']}  |  加权: {result.get('weights')}")
        else:
            print(f"  对象 N      : {result['n_subjects']}  |  评分者: {result['n_raters']}"
                  f"  |  类别: {result['n_categories']}  |  排除: {result.get('n_excluded', 0)}")
        print()
        ks = f"{kappa:.4f}" if isinstance(kappa, (int, float)) and math.isfinite(kappa) else "—"
        print(f"  kappa       : {ks}  ({result.get('interpretation', '')})")
        p_val = result.get("p")
        if isinstance(p_val, (int, float)) and math.isfinite(p_val):
            print(f"  p 值        : {'< .001' if p_val < 0.001 else f'= {p_val:.3f}'}")
        ci_lo = result.get("ci_lower")
        if isinstance(ci_lo, (int, float)) and math.isfinite(ci_lo):
            print(f"  95% CI      : [{ci_lo:.4f}, {result['ci_upper']:.4f}]")

    paths = result.get("_paths", {})
    if paths.get("md"):
        print(ui.dim(f"\n  报告已写入: {paths['md']}"))
    return 0
