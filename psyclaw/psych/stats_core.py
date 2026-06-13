"""统计计算核 — 检验 + 效应量 + 置信区间(纯 stdlib)。

复用 diagnostics.py 的 F 分布(betai)。本模块补 t 分布、卡方分布、
正态分位数,并实现心理学常用检验的完整结果(统计量 + p + 效应量 + 95%CI)。

数值对照 scipy 校验(见验证)。所有 CI 默认 95%。
"""

from __future__ import annotations

import math

from psyclaw.psych.diagnostics import betai, describe, _median  # 复用


# ---------------------------------------------------------------------------
# 分布:t 双尾 p、卡方上尾 p、正态分位数
# ---------------------------------------------------------------------------

def t_sf2(t: float, df: float) -> float:
    """学生 t 双尾 p = P(|T| > |t|)。用 I_x(df/2, 1/2)。"""
    if df <= 0:
        return float("nan")
    x = df / (df + t * t)
    return betai(df / 2.0, 0.5, x)


def chi2_sf(x: float, df: float) -> float:
    """卡方上尾 P(X > x) = 1 - 正则化下不完全 Gamma。"""
    if x <= 0:
        return 1.0
    return 1.0 - _gammainc(df / 2.0, x / 2.0)


def _gammainc(a: float, x: float) -> float:
    """正则化下不完全 Gamma P(a,x)(级数 + 连分式,Numerical Recipes)。"""
    if x < 0 or a <= 0:
        return float("nan")
    if x < a + 1.0:
        # 级数
        ap = a
        s = 1.0 / a
        d = s
        for _ in range(200):
            ap += 1
            d *= x / ap
            s += d
            if abs(d) < abs(s) * 1e-14:
                break
        return s * math.exp(-x + a * math.log(x) - math.lgamma(a))
    # 连分式 → Q,再 1-Q
    fpmin = 1e-300
    b = x + 1.0 - a
    c = 1.0 / fpmin
    d = 1.0 / b
    h = d
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
    q = math.exp(-x + a * math.log(x) - math.lgamma(a)) * h
    return 1.0 - q


def norm_ppf(p: float) -> float:
    """标准正态分位数(Acklam 近似)。"""
    if not 0 < p < 1:
        return float("nan")
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def t_ppf(p: float, df: float) -> float:
    """t 分位数(对称,二分求解双尾)。"""
    if df > 1e6:
        return norm_ppf(p)
    target = 2 * (1 - p) if p > 0.5 else 2 * p
    lo, hi = 0.0, 100.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if t_sf2(mid, df) > target:
            lo = mid
        else:
            hi = mid
    val = (lo + hi) / 2
    return val if p > 0.5 else -val


# ---------------------------------------------------------------------------
# 描述
# ---------------------------------------------------------------------------

def _mean_sd(xs: list) -> tuple:
    n = len(xs)
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0
    return m, sd, n


# ---------------------------------------------------------------------------
# 检验 + 效应量 + CI
# ---------------------------------------------------------------------------

def welch_ttest(g1: list, g2: list) -> dict:
    """Welch 独立样本 t(默认推荐)+ Cohen's d(汇合 SD)+ 95%CI。"""
    m1, s1, n1 = _mean_sd(g1)
    m2, s2, n2 = _mean_sd(g2)
    se = math.sqrt(s1**2 / n1 + s2**2 / n2)
    if se == 0:
        return {"error": "零方差"}
    t = (m1 - m2) / se
    df = se**4 / ((s1**2/n1)**2/(n1-1) + (s2**2/n2)**2/(n2-1))
    p = t_sf2(t, df)
    sp = math.sqrt(((n1-1)*s1**2 + (n2-1)*s2**2) / (n1+n2-2))
    d = (m1 - m2) / sp if sp else float("nan")
    se_d = math.sqrt((n1+n2)/(n1*n2) + d**2/(2*(n1+n2)))
    zc = norm_ppf(0.975)
    return {"test": "Welch 独立样本 t", "t": t, "df": df, "p": p,
            "m1": m1, "sd1": s1, "n1": n1, "m2": m2, "sd2": s2, "n2": n2,
            "effect": "Cohen's d", "d": d, "d_ci": (d - zc*se_d, d + zc*se_d)}


def student_ttest(g1: list, g2: list) -> dict:
    m1, s1, n1 = _mean_sd(g1)
    m2, s2, n2 = _mean_sd(g2)
    df = n1 + n2 - 2
    sp = math.sqrt(((n1-1)*s1**2 + (n2-1)*s2**2) / df)
    se = sp * math.sqrt(1/n1 + 1/n2)
    if se == 0:
        return {"error": "零方差"}
    t = (m1 - m2) / se
    p = t_sf2(t, df)
    d = (m1 - m2) / sp
    se_d = math.sqrt((n1+n2)/(n1*n2) + d**2/(2*(n1+n2)))
    zc = norm_ppf(0.975)
    return {"test": "Student 独立样本 t", "t": t, "df": df, "p": p,
            "m1": m1, "sd1": s1, "n1": n1, "m2": m2, "sd2": s2, "n2": n2,
            "effect": "Cohen's d", "d": d, "d_ci": (d - zc*se_d, d + zc*se_d)}


def paired_ttest(x: list, y: list) -> dict:
    diff = [a - b for a, b in zip(x, y)]
    m, s, n = _mean_sd(diff)
    se = s / math.sqrt(n)
    if se == 0:
        return {"error": "差值零方差"}
    t = m / se
    df = n - 1
    p = t_sf2(t, df)
    dz = m / s if s else float("nan")
    se_d = math.sqrt(1/n + dz**2/(2*n))
    zc = norm_ppf(0.975)
    return {"test": "配对样本 t", "t": t, "df": df, "p": p, "n": n,
            "mean_diff": m, "sd_diff": s,
            "effect": "Cohen's dz", "d": dz, "d_ci": (dz - zc*se_d, dz + zc*se_d)}


def pearson_r(x: list, y: list) -> dict:
    n = len(x)
    mx = sum(x)/n
    my = sum(y)/n
    sxy = sum((a-mx)*(b-my) for a, b in zip(x, y))
    sxx = sum((a-mx)**2 for a in x)
    syy = sum((b-my)**2 for b in y)
    if sxx == 0 or syy == 0:
        return {"error": "零方差"}
    r = sxy / math.sqrt(sxx*syy)
    df = n - 2
    t = r * math.sqrt(df / (1 - r**2)) if abs(r) < 1 else float("inf")
    p = t_sf2(t, df)
    # Fisher z CI
    z = 0.5 * math.log((1+r)/(1-r)) if abs(r) < 1 else float("inf")
    se = 1 / math.sqrt(n - 3) if n > 3 else float("nan")
    zc = norm_ppf(0.975)
    lo, hi = math.tanh(z - zc*se), math.tanh(z + zc*se)
    return {"test": "Pearson 相关", "r": r, "df": df, "t": t, "p": p, "n": n,
            "effect": "r", "r_ci": (lo, hi)}


def oneway_anova_full(groups: list) -> dict:
    """复用 diagnostics 经典/Welch F,补 η² 与 ω²。"""
    from psyclaw.psych.diagnostics import oneway_f, welch_f, levene_bf
    cf = oneway_f(groups)
    wf = welch_f(groups)
    lv = levene_bf(groups)
    # ω²(更抗偏)
    k = len(groups)
    N = sum(len(g) for g in groups)
    grand = sum(sum(g) for g in groups) / N
    ss_b = sum(len(g)*((sum(g)/len(g))-grand)**2 for g in groups)
    ss_w = sum(sum((x-sum(g)/len(g))**2 for x in g) for g in groups)
    ms_w = ss_w/(N-k) if N > k else float("nan")
    omega2 = (ss_b - (k-1)*ms_w) / (ss_b + ss_w + ms_w) if (ss_b+ss_w+ms_w) else float("nan")
    return {"test": "单因素 ANOVA", "classic": cf, "welch": wf, "levene": lv,
            "k": k, "N": N, "eta2": cf.get("eta2"), "omega2": omega2,
            "group_desc": [(_mean_sd(g)) for g in groups]}


def mann_whitney(g1: list, g2: list) -> dict:
    """Mann-Whitney U(正态违反时的稳健替代)+ 秩双列效应量 r。"""
    combined = sorted([(v, 0) for v in g1] + [(v, 1) for v in g2])
    # 处理结(平均秩)
    ranks = [0.0]*len(combined)
    i = 0
    while i < len(combined):
        j = i
        while j+1 < len(combined) and combined[j+1][0] == combined[i][0]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j+1):
            ranks[k] = avg
        i = j+1
    r1 = sum(ranks[idx] for idx, (_, grp) in enumerate(combined) if grp == 0)
    n1, n2 = len(g1), len(g2)
    u1 = r1 - n1*(n1+1)/2
    u = min(u1, n1*n2 - u1)
    mu = n1*n2/2
    sigma = math.sqrt(n1*n2*(n1+n2+1)/12)
    z = (u - mu)/sigma if sigma else 0.0
    p = 2*(1 - _norm_cdf(abs(z)))
    r_rb = 1 - 2*u/(n1*n2)  # rank-biserial
    return {"test": "Mann-Whitney U", "U": u, "z": z, "p": p, "n1": n1, "n2": n2,
            "effect": "rank-biserial r", "r": r_rb}


def chisquare_independence(table: list) -> dict:
    """卡方独立性 + Cramér's V。table: 行×列 计数二维列表。"""
    rows = len(table)
    cols = len(table[0])
    rt = [sum(r) for r in table]
    ct = [sum(table[i][j] for i in range(rows)) for j in range(cols)]
    total = sum(rt)
    chi2 = 0.0
    min_exp = float("inf")
    for i in range(rows):
        for j in range(cols):
            exp = rt[i]*ct[j]/total
            min_exp = min(min_exp, exp)
            if exp > 0:
                chi2 += (table[i][j]-exp)**2/exp
    df = (rows-1)*(cols-1)
    p = chi2_sf(chi2, df)
    v = math.sqrt(chi2/(total*min(rows-1, cols-1))) if total else float("nan")
    return {"test": "卡方独立性", "chi2": chi2, "df": df, "p": p,
            "effect": "Cramér's V", "V": v, "min_expected": min_exp, "N": total}


def _norm_cdf(z: float) -> float:
    return 0.5*(1 + math.erf(z/math.sqrt(2)))


# ---------------------------------------------------------------------------
# Bootstrap CI(为无解析 CI 的效应量补 CI:η²、rank-biserial r 等)
# ---------------------------------------------------------------------------

def eta_squared(groups: list) -> float:
    N = sum(len(g) for g in groups)
    if N == 0:
        return float("nan")
    grand = sum(sum(g) for g in groups) / N
    ss_b = sum(len(g) * ((sum(g) / len(g)) - grand) ** 2 for g in groups)
    ss_t = sum(sum((x - grand) ** 2 for x in g) for g in groups)
    return ss_b / ss_t if ss_t else float("nan")


def bootstrap_ci(groups: list, statfn, n_boot: int = 2000,
                 seed: int = 12345, level: float = 0.95) -> tuple:
    """分层(组内)bootstrap 百分位 CI。statfn(groups) → 标量。

    固定种子保证可复现;大样本自动降低重抽次数控制耗时。
    """
    import random
    n_total = sum(len(g) for g in groups)
    if n_total > 2000:
        n_boot = min(n_boot, 500)
    rng = random.Random(seed)
    stats = []
    for _ in range(n_boot):
        resampled = [[g[rng.randrange(len(g))] for _ in range(len(g))]
                     for g in groups]
        v = statfn(resampled)
        if v == v:  # 排除 NaN
            stats.append(v)
    if not stats:
        return float("nan"), float("nan")
    stats.sort()
    alpha = (1 - level) / 2
    lo = stats[max(0, int(alpha * len(stats)))]
    hi = stats[min(len(stats) - 1, int((1 - alpha) * len(stats)))]
    return lo, hi
