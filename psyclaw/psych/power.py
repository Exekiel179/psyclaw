"""先验功效分析 (a priori power) — 对标 G*Power,纯 stdlib。

覆盖心理学主力检验:
  - t 检验(独立/配对/单样本,单双尾)
  - 单因素 ANOVA(Cohen's f)
  - Pearson 相关(Fisher z 近似)
  - 多元回归 R²(Cohen's f²)
  - SEM 拟合优度(MacCallum, Browne & Sugawara, 1996 的 RMSEA 接近度检验)
  - 简单中介(Monte Carlo 法,Schoemann, Boulton & Short, 2017)

两个方向都给:
  - 给定 N → 求功效
  - 给定目标功效 → 求所需 N(二分搜索)

数值核心:
  - 非中心 t CDF —— 由积分表示 ∫ Φ(t√(v/ν)−δ)·χ²_ν(v) dv 数值求积(Simpson),
    无任何记忆常数,自带"密度积分=1 / df→∞→正态"两道自检。
  - 非中心 F 生存函数 —— Poisson 加权不完全 Beta 混合(精确级数)。
  - 非中心 χ² 生存函数 —— Poisson 加权正则化下不完全 Gamma 混合(精确级数)。
全部复用 diagnostics.betai / stats_core._gammainc,与项目既有统计核同源。

学术诚信:
  - 先验默认效应取保守值(d≈.40 / r≈.20 / f≈.25 / f²≈.15);
  - 任何产出都附"发表偏倚使已发表效应被高估,凭文献点估计算 N 会系统性偏小"的告警;
  - 相关用 Fisher z 近似(明确标注),其余检验用精确非中心分布。
"""

from __future__ import annotations

import math

from psyclaw.psych.diagnostics import betai
from psyclaw.psych.stats_core import _gammainc, _norm_cdf, norm_ppf, t_ppf


# ===========================================================================
# 一、非中心分布
# ===========================================================================

def _chi_scaled_logpdf(s: float, df: float) -> float:
    """s = √(V/ν)(V~χ²_ν)的密度的对数。

    f_s(s) = 2 ν^{ν/2} s^{ν−1} e^{−ν s²/2} / (2^{ν/2} Γ(ν/2))。
    """
    if s <= 0.0:
        return float("-inf")
    return (
        math.log(2.0)
        + (df / 2.0) * math.log(df)
        + (df - 1.0) * math.log(s)
        - df * s * s / 2.0
        - (df / 2.0) * math.log(2.0)
        - math.lgamma(df / 2.0)
    )


def nct_cdf(t: float, df: float, ncp: float, n_panels: int = 2400) -> float:
    """非中心 t 分布 CDF:P(T ≤ t | df, ncp)。

    用积分表示 P(T≤t)=∫_0^∞ Φ(t·s − ncp)·f_s(s) ds(s=√(V/ν)),
    Simpson 复合求积。积分窗口按 χ²_ν 的上下尾自适应。
    """
    if df <= 0:
        return float("nan")
    if ncp == 0.0:
        # 退化为中心 t:复用对称双尾
        from psyclaw.psych.stats_core import t_sf2
        if t == 0.0:
            return 0.5
        p2 = t_sf2(abs(t), df)
        return 1.0 - p2 / 2.0 if t > 0 else p2 / 2.0
    # 积分窗口:由 χ²_ν 的近似上下界换算到 s=√(χ²/ν)
    spread = math.sqrt(2.0 * df)
    chi_lo = max(0.0, df - 8.0 * spread - 4.0)
    chi_hi = df + 10.0 * spread + 30.0
    s_lo = math.sqrt(chi_lo / df)
    s_hi = math.sqrt(chi_hi / df)
    if n_panels % 2:
        n_panels += 1
    h = (s_hi - s_lo) / n_panels
    if h <= 0:
        return float("nan")

    def integrand(s: float) -> float:
        lp = _chi_scaled_logpdf(s, df)
        if lp == float("-inf"):
            return 0.0
        return _norm_cdf(t * s - ncp) * math.exp(lp)

    total = integrand(s_lo) + integrand(s_hi)
    for i in range(1, n_panels):
        s = s_lo + i * h
        total += (4.0 if i % 2 else 2.0) * integrand(s)
    val = total * h / 3.0
    return min(1.0, max(0.0, val))


def _chi_scaled_mass(df: float, n_panels: int = 2400) -> float:
    """∫ f_s(s) ds —— 仅供自检(应≈1)。"""
    spread = math.sqrt(2.0 * df)
    chi_lo = max(0.0, df - 8.0 * spread - 4.0)
    chi_hi = df + 10.0 * spread + 30.0
    s_lo = math.sqrt(chi_lo / df)
    s_hi = math.sqrt(chi_hi / df)
    if n_panels % 2:
        n_panels += 1
    h = (s_hi - s_lo) / n_panels

    def dens(s: float) -> float:
        lp = _chi_scaled_logpdf(s, df)
        return 0.0 if lp == float("-inf") else math.exp(lp)

    total = dens(s_lo) + dens(s_hi)
    for i in range(1, n_panels):
        total += (4.0 if i % 2 else 2.0) * dens(s_lo + i * h)
    return total * h / 3.0


def _f_cdf_central(f: float, df1: float, df2: float) -> float:
    """中心 F 的 CDF = I_x(df1/2, df2/2),x = df1 f/(df1 f + df2)。"""
    if f <= 0:
        return 0.0
    x = df1 * f / (df1 * f + df2)
    return betai(df1 / 2.0, df2 / 2.0, x)


def f_ppf(p: float, df1: float, df2: float) -> float:
    """中心 F 分位数(二分)。"""
    if not 0.0 < p < 1.0:
        return float("nan")
    lo, hi = 0.0, 10.0
    while _f_cdf_central(hi, df1, df2) < p and hi < 1e8:
        hi *= 2.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if _f_cdf_central(mid, df1, df2) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def ncf_sf(f: float, df1: float, df2: float, ncp: float) -> float:
    """非中心 F 生存函数 P(F > f | df1, df2, ncp)。

    CDF = Σ_j Pois(j; ncp/2) · I_x(df1/2 + j, df2/2),x = df1 f/(df1 f + df2)。
    精确收敛级数(Poisson 权在 j≈ncp/2 处取峰,尾权可忽略后停)。
    """
    if f <= 0:
        return 1.0
    if ncp < 0:
        ncp = 0.0
    x = df1 * f / (df1 * f + df2)
    half = ncp / 2.0
    term = math.exp(-half)  # j=0 的 Poisson 权
    wsum = 0.0
    cdf = 0.0
    j = 0
    while j < 10000:
        ib = betai(df1 / 2.0 + j, df2 / 2.0, x)
        cdf += term * ib
        wsum += term
        j += 1
        term *= half / j
        if j > half and (1.0 - wsum) < 1e-13:
            break
    return min(1.0, max(0.0, 1.0 - cdf))


def ncx2_sf(x: float, df: float, ncp: float) -> float:
    """非中心 χ² 生存函数 P(X > x | df, ncp)。

    CDF = Σ_j Pois(j; ncp/2) · P_central_χ²(x | df+2j),
    其中 P_central = 正则化下不完全 Gamma = _gammainc((df+2j)/2, x/2)。
    """
    if x <= 0:
        return 1.0
    if ncp < 0:
        ncp = 0.0
    half = ncp / 2.0
    term = math.exp(-half)
    wsum = 0.0
    cdf = 0.0
    j = 0
    while j < 10000:
        gi = _gammainc((df + 2 * j) / 2.0, x / 2.0)
        cdf += term * gi
        wsum += term
        j += 1
        term *= half / j
        if j > half and (1.0 - wsum) < 1e-13:
            break
    return min(1.0, max(0.0, 1.0 - cdf))


def ncx2_ppf(p: float, df: float, ncp: float) -> float:
    """非中心 χ² 分位数(二分;生存函数单调递减)。"""
    if not 0.0 < p < 1.0:
        return float("nan")
    target = 1.0 - p  # 目标生存概率
    lo, hi = 0.0, df + ncp + 10.0
    while ncx2_sf(hi, df, ncp) > target and hi < 1e9:
        hi *= 2.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if ncx2_sf(mid, df, ncp) > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# ===========================================================================
# 二、效应量量级标签(Cohen 1988)
# ===========================================================================

_BENCH = {
    "d": [(0.2, "小"), (0.5, "中"), (0.8, "大")],
    "r": [(0.1, "小"), (0.3, "中"), (0.5, "大")],
    "f": [(0.10, "小"), (0.25, "中"), (0.40, "大")],
    "f2": [(0.02, "小"), (0.15, "中"), (0.35, "大")],
}


def _label(kind: str, val: float) -> str:
    table = _BENCH.get(kind)
    if not table:
        return ""
    v = abs(val)
    lab = "极小"
    for thr, name in table:
        if v >= thr - 1e-9:
            lab = name
    if v < table[0][0] - 1e-9:
        return "可忽略"
    return lab


_BIAS_NOTE = ("已发表效应量受发表偏倚系统性高估;直接用文献点估计算 N 会让样本偏小、"
              "重复失败风险升高。建议用保守先验(d≈.40 / r≈.20 / f≈.25 / f²≈.15)"
              "或文献效应 CI 下限做敏感性分析。")


# ===========================================================================
# 三、各检验的功效函数(给定参数 → 功效)
# ===========================================================================

def power_ttest(d: float, n1: int, n2: int | None = None, *,
                alpha: float = 0.05, tails: int = 2,
                kind: str = "two-sample") -> float:
    """t 检验功效。

    kind: two-sample(n1,n2 为两组样本量) / paired / one-sample(n1 为总样本量,n2 忽略)。
    用非中心 t 精确计算(单/双尾通用)。
    """
    if kind == "two-sample":
        if n2 is None:
            n2 = n1
        if n1 < 2 or n2 < 2:
            return float("nan")
        df = n1 + n2 - 2
        ncp = d * math.sqrt(n1 * n2 / (n1 + n2))
    else:  # paired / one-sample:n1 为有效样本量(对/人)
        n = n1
        if n < 2:
            return float("nan")
        df = n - 1
        ncp = d * math.sqrt(n)
    return _power_from_nct(ncp, df, alpha, tails)


def _power_from_nct(ncp: float, df: float, alpha: float, tails: int) -> float:
    """由非中心 t 算功效:拒绝域在 |T|>tc(双尾)或 T>tc(单尾,设 ncp≥0)。"""
    if tails == 2:
        tc = t_ppf(1.0 - alpha / 2.0, df)
        # P(T>tc)+P(T<-tc)
        upper = 1.0 - nct_cdf(tc, df, ncp)
        lower = nct_cdf(-tc, df, ncp)
        return min(1.0, max(0.0, upper + lower))
    tc = t_ppf(1.0 - alpha, df)
    if ncp >= 0:
        return min(1.0, max(0.0, 1.0 - nct_cdf(tc, df, ncp)))
    return min(1.0, max(0.0, nct_cdf(-tc, df, ncp)))


def power_anova(f: float, k: int, n_per_group: int, *, alpha: float = 0.05) -> float:
    """单因素被试间 ANOVA 功效。f 为 Cohen's f,各组等样本量 n_per_group。"""
    if k < 2 or n_per_group < 2:
        return float("nan")
    N = k * n_per_group
    df1, df2 = k - 1, N - k
    ncp = f * f * N  # λ = f² · N
    fc = f_ppf(1.0 - alpha, df1, df2)
    return ncf_sf(fc, df1, df2, ncp)


def power_correlation(r: float, n: int, *, alpha: float = 0.05, tails: int = 2) -> float:
    """Pearson 相关功效(Fisher z 近似,Cohen 1988)。"""
    if n < 4 or abs(r) >= 1.0:
        return float("nan")
    zr = math.atanh(r)
    se = 1.0 / math.sqrt(n - 3)
    if tails == 2:
        zc = norm_ppf(1.0 - alpha / 2.0)
        up = _norm_cdf(zr / se - zc)
        lo = _norm_cdf(-zr / se - zc)
        return min(1.0, max(0.0, up + lo))
    zc = norm_ppf(1.0 - alpha)
    return min(1.0, max(0.0, _norm_cdf(abs(zr) / se - zc)))


def power_regression(f2: float, u: int, n: int, *, alpha: float = 0.05) -> float:
    """多元回归 R²(对零偏离)功效。f² 为 Cohen's f²,u 为受检预测元数(分子 df)。"""
    if u < 1 or n < u + 2:
        return float("nan")
    df1 = u
    df2 = n - u - 1
    ncp = f2 * n  # λ = f² · N
    fc = f_ppf(1.0 - alpha, df1, df2)
    return ncf_sf(fc, df1, df2, ncp)


def power_sem_rmsea(df: int, n: int, *, rmsea0: float = 0.05,
                    rmsea1: float = 0.08, alpha: float = 0.05) -> float:
    """SEM 整体拟合的功效:RMSEA 接近度检验(MacCallum, Browne & Sugawara, 1996)。

    H0: RMSEA = rmsea0(如 .05,接近拟合) vs H1: RMSEA = rmsea1(如 .08)。
    检验量 ~ 非中心 χ²(df, λ),λ = (N−1)·df·RMSEA²。
    rmsea1 > rmsea0 → 不接近检验(power-of-rejecting-close);反之为接近检验。
    """
    if df < 1 or n < 2:
        return float("nan")
    lam0 = (n - 1) * df * rmsea0 * rmsea0
    lam1 = (n - 1) * df * rmsea1 * rmsea1
    if rmsea1 > rmsea0:
        # 拒绝域在右尾:大 χ² 说明拟合差于 rmsea0
        crit = ncx2_ppf(1.0 - alpha, df, lam0)
        return ncx2_sf(crit, df, lam1)
    # 接近检验:拒绝域在左尾(χ² 足够小才宣称拟合优于 rmsea0)
    crit = ncx2_ppf(alpha, df, lam0)
    return 1.0 - ncx2_sf(crit, df, lam1)


# ---------------------------------------------------------------------------
# 简单中介 Monte Carlo 功效(Schoemann, Boulton & Short, 2017)
# ---------------------------------------------------------------------------

def _inv(mat: list) -> list | None:
    """小方阵高斯-约当求逆。返回逆矩阵或 None(奇异)。"""
    n = len(mat)
    a = [list(map(float, row)) + [1.0 if i == j else 0.0 for j in range(n)]
         for i, row in enumerate(mat)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[piv][col]) < 1e-12:
            return None
        a[col], a[piv] = a[piv], a[col]
        pv = a[col][col]
        a[col] = [v / pv for v in a[col]]
        for r in range(n):
            if r != col and a[r][col] != 0.0:
                factor = a[r][col]
                a[r] = [v - factor * a[col][k] for k, v in enumerate(a[r])]
    return [row[n:] for row in a]


def _ols(rows: list, y: list) -> dict | None:
    """OLS:rows 为含截距列(首列 1.0)的设计行。返回 beta / se / df。"""
    n = len(rows)
    p = len(rows[0])
    if n <= p:
        return None
    xtx = [[sum(rows[i][a] * rows[i][b] for i in range(n)) for b in range(p)]
           for a in range(p)]
    xty = [sum(rows[i][a] * y[i] for i in range(n)) for a in range(p)]
    inv = _inv(xtx)
    if inv is None:
        return None
    beta = [sum(inv[a][b] * xty[b] for b in range(p)) for a in range(p)]
    rss = 0.0
    for i in range(n):
        pred = sum(beta[a] * rows[i][a] for a in range(p))
        rss += (y[i] - pred) ** 2
    df = n - p
    mse = rss / df if df > 0 else float("nan")
    se = [math.sqrt(mse * inv[a][a]) if mse == mse and inv[a][a] > 0 else float("nan")
          for a in range(p)]
    return {"beta": beta, "se": se, "df": df}


def power_mediation_mc(a: float, b: float, n: int, *, cp: float = 0.0,
                       alpha: float = 0.05, n_sims: int = 1000,
                       mc_reps: int = 1000, seed: int = 20260614) -> float:
    """简单中介 X→M→Y 间接效应 ab 的 Monte Carlo 功效(标准化路径)。

    逐次模拟 N 例标准化数据,拟合 M~X 与 Y~X+M,取 â/b̂ 及其 SE,
    再用 Monte Carlo 法(Preacher & Selig, 2012)对 ab 构造 (1−alpha) 百分位 CI,
    记录 CI 是否排除 0。功效 = 排除 0 的比例。
    """
    import random
    if n < 5:
        return float("nan")
    rng = random.Random(seed)
    se_M = math.sqrt(max(1e-12, 1.0 - a * a))               # M 标准化残差
    var_eY = 1.0 - (cp * cp + b * b + 2.0 * cp * b * a)     # Y 标准化残差方差
    se_Y = math.sqrt(max(1e-12, var_eY))
    zc = norm_ppf(1.0 - alpha / 2.0)
    hits = 0
    valid = 0
    for _ in range(n_sims):
        xs, ms, ys = [], [], []
        for _i in range(n):
            x = rng.gauss(0.0, 1.0)
            m = a * x + rng.gauss(0.0, se_M)
            yv = cp * x + b * m + rng.gauss(0.0, se_Y)
            xs.append(x)
            ms.append(m)
            ys.append(yv)
        fa = _ols([[1.0, x] for x in xs], ms)               # M ~ X
        fb = _ols([[1.0, x, m] for x, m in zip(xs, ms)], ys)  # Y ~ X + M
        if fa is None or fb is None:
            continue
        a_hat, a_se = fa["beta"][1], fa["se"][1]
        b_hat, b_se = fb["beta"][2], fb["se"][2]
        if not (a_se == a_se and b_se == b_se):
            continue
        valid += 1
        draws = sorted((a_hat + a_se * rng.gauss(0.0, 1.0)) *
                       (b_hat + b_se * rng.gauss(0.0, 1.0))
                       for _r in range(mc_reps))
        lo = draws[int((alpha / 2.0) * mc_reps)]
        hi = draws[min(mc_reps - 1, int((1.0 - alpha / 2.0) * mc_reps))]
        if lo > 0.0 or hi < 0.0:
            hits += 1
    if valid == 0:
        return float("nan")
    return hits / valid


# ===========================================================================
# 四、样本量反解(给定目标功效 → 所需 N)
# ===========================================================================

def _solve_n(power_at, target: float, lo: int) -> int | None:
    """求满足 power_at(n) ≥ target 的最小整数 n(power_at 关于 n 单调增)。"""
    hi = max(lo + 1, lo * 2)
    while True:
        pv = power_at(hi)
        if pv == pv and pv >= target:
            break
        hi *= 2
        if hi > 10_000_000:
            return None
    while lo < hi:
        mid = (lo + hi) // 2
        pv = power_at(mid)
        if pv == pv and pv >= target:
            hi = mid
        else:
            lo = mid + 1
    return lo


def n_for_ttest(d: float, *, power: float = 0.80, alpha: float = 0.05,
                tails: int = 2, kind: str = "two-sample") -> int | None:
    """达到目标功效所需样本量(two-sample 返回每组 n;其余返回总 N)。"""
    if kind == "two-sample":
        return _solve_n(lambda n: power_ttest(d, n, n, alpha=alpha, tails=tails,
                                              kind="two-sample"), power, 2)
    return _solve_n(lambda n: power_ttest(d, n, alpha=alpha, tails=tails,
                                          kind=kind), power, 2)


def n_for_anova(f: float, k: int, *, power: float = 0.80,
                alpha: float = 0.05) -> int | None:
    """达到目标功效所需每组样本量。"""
    return _solve_n(lambda n: power_anova(f, k, n, alpha=alpha), power, 2)


def n_for_correlation(r: float, *, power: float = 0.80, alpha: float = 0.05,
                      tails: int = 2) -> int | None:
    return _solve_n(lambda n: power_correlation(r, n, alpha=alpha, tails=tails),
                    power, 4)


def n_for_regression(f2: float, u: int, *, power: float = 0.80,
                     alpha: float = 0.05) -> int | None:
    return _solve_n(lambda n: power_regression(f2, u, n, alpha=alpha), power, u + 2)


def n_for_sem_rmsea(df: int, *, power: float = 0.80, rmsea0: float = 0.05,
                    rmsea1: float = 0.08, alpha: float = 0.05) -> int | None:
    return _solve_n(lambda n: power_sem_rmsea(df, n, rmsea0=rmsea0, rmsea1=rmsea1,
                                              alpha=alpha), power, 5)


# ===========================================================================
# 五、命令行编排
# ===========================================================================

_PRIORS = {"d": 0.40, "r": 0.20, "f": 0.25, "f2": 0.15, "a": 0.30, "b": 0.30}


def compute(test: str, *, d=None, r=None, f=None, f2=None, a=None, b=None,
            cp=0.0, k=None, u=None, n=None, power=None, alpha=0.05, tails=2,
            kind="two-sample", df=None, rmsea0=0.05, rmsea1=0.08,
            sims=1000, seed=20260614) -> dict:
    """统一计算入口。n 与 power 二选一(都缺则默认求 power=.80 的 N)。

    返回结构化 dict(含 analysis / solve / power / n / effect / notes)。
    """
    solve = "power" if n is not None else "n"
    if n is None and power is None:
        power = 0.80
    notes = [_BIAS_NOTE]
    used_prior = []

    def _prior(name, val):
        if val is None:
            used_prior.append(name)
            return _PRIORS[name]
        return val

    res: dict = {"test": test, "solve": solve, "alpha": alpha}

    if test == "ttest":
        d = _prior("d", d)
        res.update({"analysis": f"{_kind_label(kind)} t 检验", "tails": tails,
                    "kind": kind,
                    "effect": {"name": "Cohen's d", "value": d,
                               "magnitude": _label("d", d)}})
        if solve == "power":
            res["n"] = n
            res["n_unit"] = "每组" if kind == "two-sample" else "总"
            res["power"] = power_ttest(d, n, n if kind == "two-sample" else None,
                                       alpha=alpha, tails=tails, kind=kind)
        else:
            req = n_for_ttest(d, power=power, alpha=alpha, tails=tails, kind=kind)
            res["power"] = power
            res["n"] = req
            res["n_unit"] = "每组" if kind == "two-sample" else "总"
            if kind == "two-sample" and req is not None:
                res["n_total"] = req * 2

    elif test == "anova":
        f = _prior("f", f)
        if k is None:
            k = 3
        res.update({"analysis": f"单因素 ANOVA({k} 组)", "k": k,
                    "effect": {"name": "Cohen's f", "value": f,
                               "magnitude": _label("f", f)}})
        if solve == "power":
            res["n"] = n
            res["n_unit"] = "每组"
            res["power"] = power_anova(f, k, n, alpha=alpha)
            if n is not None:
                res["n_total"] = n * k
        else:
            req = n_for_anova(f, k, power=power, alpha=alpha)
            res["power"] = power
            res["n"] = req
            res["n_unit"] = "每组"
            if req is not None:
                res["n_total"] = req * k

    elif test in ("r", "correlation"):
        r = _prior("r", r)
        res.update({"analysis": "Pearson 相关(Fisher z 近似)", "tails": tails,
                    "effect": {"name": "r", "value": r, "magnitude": _label("r", r)}})
        notes.append("相关功效用 Fisher z 变换近似;小样本(n<30)略保守。")
        if solve == "power":
            res["n"] = n
            res["n_unit"] = "总"
            res["power"] = power_correlation(r, n, alpha=alpha, tails=tails)
        else:
            req = n_for_correlation(r, power=power, alpha=alpha, tails=tails)
            res["power"] = power
            res["n"] = req
            res["n_unit"] = "总"

    elif test == "regression":
        f2 = _prior("f2", f2)
        if u is None:
            u = 3
        res.update({"analysis": f"多元回归 R²(对零偏离,{u} 预测元)", "u": u,
                    "effect": {"name": "Cohen's f²", "value": f2,
                               "magnitude": _label("f2", f2)}})
        if solve == "power":
            res["n"] = n
            res["n_unit"] = "总"
            res["power"] = power_regression(f2, u, n, alpha=alpha)
        else:
            req = n_for_regression(f2, u, power=power, alpha=alpha)
            res["power"] = power
            res["n"] = req
            res["n_unit"] = "总"

    elif test == "sem":
        if df is None:
            df = 30
        res.update({"analysis": "SEM 拟合优度(RMSEA 接近度检验)",
                    "df": df, "rmsea0": rmsea0, "rmsea1": rmsea1,
                    "effect": {"name": "RMSEA", "value": rmsea1,
                               "magnitude": "—"}})
        notes.append("RMSEA 接近度检验(MacCallum, Browne & Sugawara, 1996);"
                     "df 越大同等 N 功效越高,故复杂模型可在较小 N 下检出失拟。")
        if solve == "power":
            res["n"] = n
            res["n_unit"] = "总"
            res["power"] = power_sem_rmsea(df, n, rmsea0=rmsea0, rmsea1=rmsea1,
                                           alpha=alpha)
        else:
            req = n_for_sem_rmsea(df, power=power, rmsea0=rmsea0, rmsea1=rmsea1,
                                  alpha=alpha)
            res["power"] = power
            res["n"] = req
            res["n_unit"] = "总"

    elif test == "mediation":
        a = _prior("a", a)
        b = _prior("b", b)
        res.update({"analysis": "简单中介 X→M→Y(间接效应 ab,Monte Carlo)",
                    "a": a, "b": b, "cp": cp,
                    "effect": {"name": "ab(标准化)", "value": a * b,
                               "magnitude": "—"}})
        notes.append("Monte Carlo 中介功效(Schoemann et al., 2017);"
                     "随机模拟,固定种子可复现;a/b 为标准化路径系数。")
        if solve == "power":
            res["n"] = n
            res["n_unit"] = "总"
            res["power"] = power_mediation_mc(a, b, n, cp=cp, alpha=alpha,
                                              n_sims=sims, seed=seed)
        else:
            req = _solve_n(lambda nn: power_mediation_mc(a, b, nn, cp=cp,
                           alpha=alpha, n_sims=max(300, sims // 2), seed=seed),
                           power, 10)
            res["power"] = power
            res["n"] = req
            res["n_unit"] = "总"
    else:
        return {"error": f"未知检验:{test}"}

    if used_prior:
        notes.insert(0, "未给定效应量,已套用保守先验:"
                     + "、".join(f"{k_}={_PRIORS[k_]}" for k_ in used_prior))
    res["notes"] = notes
    return res


def _kind_label(kind: str) -> str:
    return {"two-sample": "独立样本", "paired": "配对样本",
            "one-sample": "单样本"}.get(kind, kind)


def render(res: dict) -> str:
    """把 compute() 结果渲染为终端报告。"""
    from psyclaw import ui
    if "error" in res:
        return ui.err(res["error"])
    lines = [ui.title(f"先验功效分析 · {res['analysis']}"), ui.rule()]
    eff = res.get("effect", {})
    if eff:
        mag = f"({eff['magnitude']})" if eff.get("magnitude") not in ("", "—") else ""
        lines.append(f"  效应量    {eff['name']} = {eff['value']:.3g} {mag}")
    lines.append(f"  α         {res['alpha']:.3g}"
                 + (f"   尾   {res['tails']}" if "tails" in res else ""))
    extras = []
    for key, lab in (("k", "组数"), ("u", "预测元"), ("df", "模型 df"),
                     ("rmsea0", "RMSEA₀"), ("rmsea1", "RMSEA₁"),
                     ("a", "a 路径"), ("b", "b 路径")):
        if key in res:
            extras.append(f"{lab}={res[key]}")
    if extras:
        lines.append("  设定      " + "  ".join(extras))
    lines.append(ui.rule())
    n = res.get("n")
    unit = res.get("n_unit", "")
    if res["solve"] == "power":
        pw = res.get("power")
        pw_s = f"{pw:.4f}" if isinstance(pw, float) and pw == pw else "N/A"
        flag = ui.ok("✓ 充分") if (isinstance(pw, float) and pw >= 0.80) \
            else ui.warn("⚠ 不足(<.80)")
        lines.append(f"  给定 N({unit})= {n}  →  功效 = {ui.accent(pw_s)}  {flag}")
        if "n_total" in res:
            lines.append(ui.dim(f"            (总样本 N = {res['n_total']})"))
    else:
        tgt = res.get("power")
        if n is None:
            lines.append(ui.err(f"  目标功效 {tgt:.2f}:效应过小,所需 N 超出上限(>1e7),"
                                "请复核效应量假设。"))
        else:
            lines.append(f"  目标功效 = {tgt:.2f}  →  所需 N({unit})= {ui.accent(str(n))}")
            if "n_total" in res:
                lines.append(ui.dim(f"            (总样本 N = {res['n_total']})"))
    lines.append(ui.rule())
    for note in res.get("notes", []):
        lines.append(ui.dim(f"  ⚠ {note}"))
    return "\n".join(lines)


def run_power(test: str, **kw) -> int:
    """CLI 入口:计算并打印(可选 JSON)。"""
    as_json = kw.pop("as_json", False)
    res = compute(test, **kw)
    if as_json:
        import json
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(render(res))
    return 0 if "error" not in res else 1
