"""心理学检验决策树特判 — A-1 专项扩展 (stdlib only)。

六类心理学特判:
1. Likert 单题检测  — 离散整数范围窄,提示有序处理 + Spearman 稳健对照
2. 大样本效应量语言 — N≥500 且效应可忽略时自动改用效应量解读语言
3. 嵌套数据 ICC(1) — 检测到 cluster 列时计算 ICC 并提示 MLM
4. 中介 bootstrap CI(5000) — 拒绝 Sobel,直接/间接/总效应三路
5. 调节简单斜率 + Johnson-Neyman — 精确 JN 区间(二次方程解析解)
6. (SEM 全拟合指数 — 调用 analyze_advanced / r_backend,见 analyze.py)
"""
from __future__ import annotations

import csv
import io
import math
import random
from pathlib import Path


# ---------------------------------------------------------------------------
# 1. Likert 单题检测
# ---------------------------------------------------------------------------

def detect_likert(values: list) -> dict:
    """检测变量是否为 Likert 单题(离散整数,范围 ≤ 11)。

    返回 is_likert, unique_values, range, recommendation。
    """
    if not values:
        return {"is_likert": False}
    int_vals = [int(v) for v in values if math.isfinite(v) and v == int(v)]
    ratio = len(int_vals) / len(values)
    if ratio < 0.95 or len(int_vals) < 3:
        return {"is_likert": False, "ratio": ratio}
    unique = sorted(set(int_vals))
    nu = len(unique)
    mn, mx = unique[0], unique[-1]
    span = mx - mn + 1
    # 典型 Likert: 1-5, 1-7, 0-10 等(span ≤ 11, 取值 0-11)
    is_likert = nu <= 11 and mn >= 0 and mx <= 11 and span <= 11
    rec = (
        f"检测到 Likert 单题({mn}–{mx},{nu} 类)。建议:"
        "① 报 Spearman ρ 作稳健对照(已自动补充);"
        "② 若为有序类别,考虑多项式有序 logit;"
        "③ Pearson r 在 5+ 级量表时通常可接受,但请在论文中注明。"
    ) if is_likert else ""
    return {
        "is_likert": is_likert,
        "unique_values": nu,
        "range": (mn, mx),
        "recommendation": rec,
    }


# ---------------------------------------------------------------------------
# 2. 大样本效应量语言重构
# ---------------------------------------------------------------------------

_TRIVIAL = {
    "Cohen's d": 0.20, "d": 0.20, "dz": 0.20,
    "r": 0.10, "Pearson r": 0.10, "rank-biserial r": 0.10,
    "eta^2": 0.01, "η²": 0.01, "omega^2": 0.01, "ω²": 0.01,
    "Cramér's V": 0.10,
    "indirect": 0.05,
}


def large_sample_effect_language(N: int, effect_name: str,
                                  effect_value: float, p: float) -> dict:
    """检测大样本下「统计显著但效应可忽略」情况,返回解读建议。"""
    threshold = _TRIVIAL.get(effect_name, 0.20)
    is_large = N >= 500
    trivial = (is_large and p < 0.05
               and math.isfinite(effect_value) and abs(effect_value) < threshold)
    if trivial:
        msg = (
            f"⚠ 大样本警示(N = {N}):统计显著(p = {p:.3f})但效应量"
            f"|{effect_name}| = {abs(effect_value):.3f} 低于微小效应阈值({threshold})。"
            "建议以效应量与 95% CI 描述实际意义,而非以 p 值显著性为准。"
        )
    elif is_large:
        msg = (
            f"大样本(N = {N}):统计功效充足;请以效应量 {effect_name} = "
            f"{effect_value:.3f} 及其 CI 判断实际重要性,不以 p 值为准。"
        )
    else:
        msg = ""
    return {
        "large_sample": is_large,
        "trivial": trivial,
        "threshold": threshold,
        "message": msg,
    }


# ---------------------------------------------------------------------------
# 3. 嵌套数据 ICC(1)
# ---------------------------------------------------------------------------

def compute_icc(rows: list, dv: str, cluster: str) -> dict:
    """计算 ICC(1):组间相关系数(单项评分者 / 嵌套设计)。

    使用 MS-between / MS-within 公式:
      ICC(1) = (MSB - MSW) / (MSB + (n_harm - 1) * MSW)
    """
    groups: dict = {}
    for r in rows:
        raw_val = r.get(dv)
        raw_key = r.get(cluster)
        if raw_key is None:
            continue
        key = str(raw_key).strip() if not isinstance(raw_key, str) else raw_key.strip()
        if not key:
            continue
        if isinstance(raw_val, (int, float)):
            if math.isfinite(raw_val):
                groups.setdefault(key, []).append(float(raw_val))
        else:
            try:
                groups.setdefault(key, []).append(float(str(raw_val or "").strip()))
            except (ValueError, TypeError):
                pass
    groups = {k: v for k, v in groups.items() if len(v) >= 2}
    k = len(groups)
    if k < 2:
        return {"icc": float("nan"), "error": f"有效 cluster < 2(实得 {k})", "k": k}
    glist = list(groups.values())
    N = sum(len(g) for g in glist)
    grand = sum(sum(g) for g in glist) / N
    ss_b = sum(len(g) * ((sum(g) / len(g)) - grand) ** 2 for g in glist)
    ss_w = sum(sum((x - sum(g) / len(g)) ** 2 for x in g) for g in glist)
    ms_b = ss_b / (k - 1)
    ms_w = ss_w / (N - k) if N > k else float("nan")
    # 调和平均组大小(更精确)
    n_harm = (N - sum(len(g) ** 2 for g in glist) / N) / (k - 1) if k > 1 else N
    denom = ms_b + (n_harm - 1) * ms_w
    icc = max(0.0, (ms_b - ms_w) / denom) if denom and math.isfinite(denom) else 0.0
    if icc < 0.05:
        interp = "可忽略(< .05);MLM 收益小,独立假设勉强成立"
    elif icc < 0.15:
        interp = "中等(.05–.15);建议 MLM/GEE 控制聚类效应"
    else:
        interp = "大(≥ .15);强烈建议 MLM(lme4/nlme)或 GEE 处理非独立性"
    return {
        "icc": icc,
        "k_clusters": k,
        "N": N,
        "ms_b": ms_b,
        "ms_w": ms_w,
        "n_harm_mean": n_harm,
        "interpretation": interp,
    }


# ---------------------------------------------------------------------------
# 4. 中介分析 — bootstrap CI(5000),拒 Sobel
# ---------------------------------------------------------------------------

def _ols2(xs: list, ys: list) -> tuple:
    """简单 OLS y = a + b*x → (intercept, slope)。"""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((xi - mx) * (yi - my) for xi, yi in zip(xs, ys))
    sxx = sum((xi - mx) ** 2 for xi in xs)
    if sxx == 0:
        return (my, 0.0)
    b = sxy / sxx
    return (my - b * mx, b)


def _partial_slopes(xs: list, ms: list, ys: list) -> tuple:
    """Y ~ X + M 偏回归:返回 (b_m, c_prime)。

    b_m     = M 对 Y 的偏斜率(path b)
    c_prime = X 对 Y 的直接效应(排除 M)

    正规方程 [[sxx, sxm],[sxm,smm]] * [c', b] = [sxy, smy]
    Cramer 法则:c' = (smm*sxy - sxm*smy)/D, b = (sxx*smy - sxm*sxy)/D
    代数恒等: c' + a*b = c(可验证 c = c' + ab 恒成立)
    """
    n = len(xs)
    mxv, mmv, myv = sum(xs) / n, sum(ms) / n, sum(ys) / n
    sxx = sum((xi - mxv) ** 2 for xi in xs)
    smm = sum((mi - mmv) ** 2 for mi in ms)
    sxm = sum((xi - mxv) * (mi - mmv) for xi, mi in zip(xs, ms))
    sxy = sum((xi - mxv) * (yi - myv) for xi, yi in zip(xs, ys))
    smy = sum((mi - mmv) * (yi - myv) for mi, yi in zip(ms, ys))
    denom = sxx * smm - sxm ** 2
    if abs(denom) < 1e-14:
        return (float("nan"), float("nan"))
    b = (sxx * smy - sxm * sxy) / denom        # path b: M→Y|X
    c_prime = (smm * sxy - sxm * smy) / denom  # direct: X→Y|M
    return (b, c_prime)


def _indirect(xs: list, ms: list, ys: list) -> float:
    _, a = _ols2(xs, ms)
    b, _ = _partial_slopes(xs, ms, ys)
    return float("nan") if math.isnan(b) else a * b


def bootstrap_mediation(x: list, m: list, y: list,
                         n_boot: int = 5000, seed: int = 12345) -> dict:
    """Preacher & Hayes bootstrap 中介分析(拒绝 Sobel)。

    Returns: a, b, c, c_prime, indirect, ci_95, significant, n, n_boot。
    """
    n = len(x)
    if n < 10:
        return {"error": f"n = {n} < 10,中介分析样本量不足"}
    _, a = _ols2(x, m)
    b, c_prime = _partial_slopes(x, m, y)
    _, c = _ols2(x, y)
    indirect = _indirect(x, m, y)
    rng = random.Random(seed)
    boot = []
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        xi = [x[i] for i in idx]
        mi = [m[i] for i in idx]
        yi = [y[i] for i in idx]
        v = _indirect(xi, mi, yi)
        if math.isfinite(v):
            boot.append(v)
    boot.sort()
    nb = len(boot)
    lo = boot[max(0, int(0.025 * nb))]
    hi = boot[min(nb - 1, int(0.975 * nb))]
    sig = not (lo <= 0 <= hi)
    # κ² 近似(Preacher & Kelley 2011):间接效应 / 最大可能间接效应
    var_y = sum((yi - sum(y) / n) ** 2 for yi in y) / (n - 1) if n > 1 else float("nan")
    kappa2 = (indirect / math.sqrt(var_y)
              if math.isfinite(var_y) and var_y > 0 else float("nan"))
    return {
        "a": a, "b": b, "c": c, "c_prime": c_prime,
        "indirect": indirect, "kappa2_approx": kappa2,
        "ci": [lo, hi], "significant": sig,
        "n": n, "n_boot": nb,
        "note": ("Preacher & Hayes bootstrap(百分位 CI);"
                 "Sobel 法低估 CI 宽度 — 已拒用。"),
    }


# ---------------------------------------------------------------------------
# 5. 调节分析 — 简单斜率 + Johnson-Neyman(精确协方差矩阵)
# ---------------------------------------------------------------------------

def _ols4(X_design: list, y: list) -> tuple:
    """4 变量 OLS via Gauss-Jordan。

    返回 (coeffs[4], XtX_inv[4×4], mse, df_res)。
    """
    p = 4
    n_obs = len(y)
    XtX = [
        [sum(X_design[i][a] * X_design[i][b] for i in range(n_obs)) for b in range(p)]
        for a in range(p)
    ]
    Xty = [sum(X_design[i][a] * y[i] for i in range(n_obs)) for a in range(p)]
    # 增广矩阵 [XtX | I] → Gauss-Jordan → [I | XtX_inv]
    aug = [XtX[i][:] + [1.0 if i == j else 0.0 for j in range(p)] for i in range(p)]
    for col in range(p):
        pr = max(range(col, p), key=lambda r: abs(aug[r][col]))
        aug[col], aug[pr] = aug[pr], aug[col]
        piv = aug[col][col]
        if abs(piv) < 1e-12:
            raise ValueError("设计矩阵近奇异,无法求逆(可能存在完全多重共线性)")
        for j in range(2 * p):
            aug[col][j] /= piv
        for row in range(p):
            if row != col:
                fac = aug[row][col]
                for j in range(2 * p):
                    aug[row][j] -= fac * aug[col][j]
    XtX_inv = [[aug[i][p + j] for j in range(p)] for i in range(p)]
    coeffs = [sum(XtX_inv[i][j] * Xty[j] for j in range(p)) for i in range(p)]
    yhat = [sum(coeffs[a] * X_design[i][a] for a in range(p)) for i in range(n_obs)]
    sse = sum((y[i] - yhat[i]) ** 2 for i in range(n_obs))
    df_res = n_obs - p
    mse = sse / df_res if df_res > 0 else float("nan")
    return coeffs, XtX_inv, mse, df_res


def _t_sf2(t: float, df: float) -> float:
    try:
        from psyclaw.psych.stats_core import t_sf2
        return t_sf2(t, df)
    except Exception:
        from psyclaw.psych.diagnostics import betai
        x = df / (df + t * t)
        return betai(df / 2, 0.5, x)


def _t_ppf(p: float, df: float) -> float:
    try:
        from psyclaw.psych.stats_core import t_ppf
        return t_ppf(p, df)
    except Exception:
        return 1.96


def moderation_analysis(x: list, w: list, y: list, alpha: float = 0.05) -> dict:
    """调节分析:X*W 交互 + 简单斜率(W±1SD, W均值) + Johnson-Neyman 区间。

    设计矩阵: [1, X, Wc, X*Wc]  (W 中心化 → Wc = W - mean(W))
    b1 = X 主效应(在 W = mean(W) 处)
    b3 = 交互项系数

    JN 区间:解 [b1 + b3*Wc]² = t²_crit * MSE * (v11 + 2*Wc*v13 + Wc²*v33)
    → 二次方程 A*Wc² + B*Wc + C = 0 的实数根即为显著性转变点。
    """
    n = len(x)
    if n < 20:
        return {"error": f"n = {n} < 20,调节分析样本量不足"}
    mw = sum(w) / n
    sdw = math.sqrt(sum((wi - mw) ** 2 for wi in w) / (n - 1)) if n > 1 else 0.0
    if sdw == 0:
        return {"error": "调节变量 W 方差为 0"}
    wc = [wi - mw for wi in w]
    xwc = [xi * wci for xi, wci in zip(x, wc)]
    X_design = [[1.0, x[i], wc[i], xwc[i]] for i in range(n)]
    try:
        coeffs, XtX_inv, mse, df_res = _ols4(X_design, y)
    except ValueError as e:
        return {"error": str(e)}
    b0, b1, b2, b3 = coeffs
    v11 = XtX_inv[1][1]   # Var(b1)
    v13 = XtX_inv[1][3]   # Cov(b1, b3)
    v33 = XtX_inv[3][3]   # Var(b3)

    def _ss(wc_val: float) -> float:
        return b1 + b3 * wc_val

    def _se_ss(wc_val: float) -> float:
        var = mse * (v11 + 2 * wc_val * v13 + wc_val ** 2 * v33)
        return math.sqrt(max(0.0, var))

    t_crit = _t_ppf(1 - alpha / 2, df_res)

    # 简单斜率表
    wc_levels = [
        (-sdw, f"W = mean−1SD ({mw - sdw:.3f})"),
        (0.0,  f"W = mean    ({mw:.3f})"),
        (sdw,  f"W = mean+1SD ({mw + sdw:.3f})"),
    ]
    simple_slopes = []
    for wc_val, label in wc_levels:
        slope = _ss(wc_val)
        se_v = _se_ss(wc_val)
        t_v = slope / se_v if se_v > 0 else float("nan")
        p_v = _t_sf2(abs(t_v), df_res) if se_v > 0 else float("nan")
        simple_slopes.append({
            "label": label,
            "w_value": mw + wc_val,
            "slope": slope,
            "se": se_v,
            "t": t_v,
            "p": p_v,
            "significant": p_v < alpha if math.isfinite(p_v) else False,
        })

    # Johnson-Neyman:二次方程求根
    # (b1 + b3*wc)^2 = t²_crit * MSE * (v11 + 2*wc*v13 + wc²*v33)
    tc2 = t_crit ** 2
    A = b3 ** 2 - tc2 * mse * v33
    B = 2.0 * (b1 * b3 - tc2 * mse * v13)
    C = b1 ** 2 - tc2 * mse * v11
    jn_roots_wc: list = []
    if abs(A) < 1e-14:
        if abs(B) > 1e-14:
            jn_roots_wc = [-C / B]
    else:
        disc = B ** 2 - 4 * A * C
        if disc >= 0:
            sd = math.sqrt(disc)
            jn_roots_wc = sorted([(-B - sd) / (2 * A), (-B + sd) / (2 * A)])
    jn_roots = [r + mw for r in jn_roots_wc]   # 还原到原始 W 尺度

    w_range = (min(w), max(w))
    jn_interp = _jn_interpretation(jn_roots, w_range, b3)

    return {
        "b0": b0, "b1": b1, "b2": b2, "b3": b3,
        "mw": mw, "sdw": sdw,
        "simple_slopes": simple_slopes,
        "jn_roots": jn_roots,
        "jn_interpretation": jn_interp,
        "mse": mse, "df_res": df_res, "n": n,
        "note": ("简单斜率 & JN 区间由精确 OLS 协方差矩阵(析出二次方程)计算;"
                 "无需 PROCESS/SPSS 宏。"),
    }


def _jn_interpretation(roots: list, w_range: tuple, b3: float) -> str:
    if not roots:
        return "简单斜率在 W 全范围内恒显著(或恒不显著),无显著性转变点。"
    wmin, wmax = w_range
    in_range = [r for r in roots if wmin <= r <= wmax]
    if not in_range:
        return (f"JN 转变点 [{', '.join(f'{r:.3f}' for r in roots)}] 均不在 W 实际范围"
                f"[{wmin:.3f}, {wmax:.3f}]内;简单斜率在观测范围内恒显著或恒不显著。")
    pts = " 和 ".join(f"{r:.3f}" for r in in_range)
    return (
        f"JN 转变点:W = {pts}  (α = .05)。"
        f"调节项 b3 = {b3:.4f}:"
        f"{'b3>0 → W 越大,X 效应越强' if b3 > 0 else 'b3<0 → W 越大,X 效应越弱'}。"
        "请检视转变点两侧样本比例以判断实际意义。"
    )


# ---------------------------------------------------------------------------
# CSV 辅助(内部复用,避免重复 import)
# ---------------------------------------------------------------------------

def _load_csv3(path_s: str, col1: str, col2: str, col3: str) -> tuple:
    """读 CSV,提取三列的 pairwise 完整观测。"""
    fp = Path(path_s)
    if not fp.exists():
        return None, f"文件不存在:{path_s}"
    raw = fp.read_bytes().decode("utf-8", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(raw[:4096], delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.DictReader(io.StringIO(raw), dialect=dialect))
    v1, v2, v3 = [], [], []
    for r in rows:
        try:
            v1.append(float((r.get(col1) or "").strip()))
            v2.append(float((r.get(col2) or "").strip()))
            v3.append(float((r.get(col3) or "").strip()))
        except ValueError:
            pass
    return (v1, v2, v3, len(rows)), None


# ---------------------------------------------------------------------------
# CLI 入口 — 中介分析
# ---------------------------------------------------------------------------

def analyze_mediation_cli(argv: list) -> int:
    """psyclaw mediation <file> --x X --m M --y Y [--nboot 5000]"""
    from psyclaw import ui
    if not argv:
        print("用法:psyclaw mediation <file.csv> --x X --m M --y Y [--nboot 5000]")
        return 1
    path_s = argv[0]
    x_col = m_col = y_col = None
    n_boot = 5000
    i = 1
    while i < len(argv):
        if argv[i] in ("--x",) and i + 1 < len(argv):
            x_col = argv[i + 1]; i += 2
        elif argv[i] in ("--m",) and i + 1 < len(argv):
            m_col = argv[i + 1]; i += 2
        elif argv[i] in ("--y",) and i + 1 < len(argv):
            y_col = argv[i + 1]; i += 2
        elif argv[i] in ("--nboot",) and i + 1 < len(argv):
            n_boot = int(argv[i + 1]); i += 2
        else:
            i += 1
    if not (x_col and m_col and y_col):
        print("必须指定 --x --m --y")
        return 1
    result_cols, err = _load_csv3(path_s, x_col, m_col, y_col)
    if err:
        print(ui.err(err))
        return 1
    xv, mv, yv, n_total = result_cols
    if len(xv) < 10:
        print(ui.err(f"有效三元组观测 < 10(实得 {len(xv)})"))
        return 1
    print(ui.title(f"中介分析 — {Path(path_s).name}"))
    print(ui.dim(f"  {x_col} → {m_col} → {y_col}  |  n = {len(xv)}  |  bootstrap = {n_boot}"))
    res = bootstrap_mediation(xv, mv, yv, n_boot=n_boot)
    if "error" in res:
        print(ui.err(res["error"]))
        return 1
    a, b = res["a"], res["b"]
    c, cp = res["c"], res["c_prime"]
    ind = res["indirect"]
    lo, hi = res["ci"]
    sig = res["significant"]
    print(ui.accent("\n路径系数:"))
    print(f"  a  ({x_col} → {m_col})         = {a:+.4f}")
    print(f"  b  ({m_col} → {y_col} | {x_col}) = {b:+.4f}")
    print(f"  c  总效应                        = {c:+.4f}")
    print(f"  c′ 直接效应                      = {cp:+.4f}")
    print(f"  ab 间接效应                      = {ind:+.4f}")
    print(ui.accent("\nBootstrap 95% CI:"))
    sig_txt = "✓ 显著(CI 不含 0)" if sig else "✗ 不显著(CI 含 0)"
    print(f"  [{lo:.4f}, {hi:.4f}]  {sig_txt}  (n_boot = {res['n_boot']})")
    if math.isfinite(res.get("kappa2_approx", float("nan"))):
        print(f"\n  κ² ≈ {res['kappa2_approx']:.4f}(间接效应相对量,Preacher & Kelley 2011)")
    print(f"\n  {res['note']}")
    print(ui.warn("注:相关/回归数据的中介推断因果性受限;建议纵向或实验数据。"))
    return 0


# ---------------------------------------------------------------------------
# CLI 入口 — 调节分析
# ---------------------------------------------------------------------------

def analyze_moderation_cli(argv: list) -> int:
    """psyclaw moderation <file> --x X --w W --y Y"""
    from psyclaw import ui
    if not argv:
        print("用法:psyclaw moderation <file.csv> --x X --w W --y Y")
        return 1
    path_s = argv[0]
    x_col = w_col = y_col = None
    i = 1
    while i < len(argv):
        if argv[i] == "--x" and i + 1 < len(argv):
            x_col = argv[i + 1]; i += 2
        elif argv[i] == "--w" and i + 1 < len(argv):
            w_col = argv[i + 1]; i += 2
        elif argv[i] == "--y" and i + 1 < len(argv):
            y_col = argv[i + 1]; i += 2
        else:
            i += 1
    if not (x_col and w_col and y_col):
        print("必须指定 --x --w --y")
        return 1
    result_cols, err = _load_csv3(path_s, x_col, w_col, y_col)
    if err:
        print(ui.err(err))
        return 1
    xv, wv, yv, _ = result_cols
    if len(xv) < 20:
        print(ui.err(f"有效三元组观测 < 20(实得 {len(xv)})"))
        return 1
    print(ui.title(f"调节分析 — {Path(path_s).name}"))
    print(ui.dim(f"  {x_col} × {w_col} → {y_col}  |  n = {len(xv)}"))
    res = moderation_analysis(xv, wv, yv)
    if "error" in res:
        print(ui.err(res["error"]))
        return 1
    b0, b1, b2, b3 = res["b0"], res["b1"], res["b2"], res["b3"]
    print(ui.accent("\n回归系数:"))
    print(f"  b0 截距              = {b0:+.4f}")
    print(f"  b1 {x_col:<12}  = {b1:+.4f}  (W=mean 时 X 的效应)")
    print(f"  b2 {w_col:<12}  = {b2:+.4f}")
    print(f"  b3 {x_col}×{w_col:<8}  = {b3:+.4f}  ← 调节效应")
    print(ui.accent("\n简单斜率(X 对 Y):"))
    for ss in res["simple_slopes"]:
        mk = "✓" if ss["significant"] else "·"
        pstr = f"p = {ss['p']:.3f}" if math.isfinite(ss["p"]) else "p = NA"
        print(f"  {mk} {ss['label']:<32}  slope = {ss['slope']:+.4f}"
              f"  t({res['df_res']}) = {ss['t']:.2f}  {pstr}")
    print(ui.accent("\nJohnson-Neyman 区间:"))
    print(f"  {res['jn_interpretation']}")
    if res["jn_roots"]:
        pts = ", ".join(f"{r:.3f}" for r in res["jn_roots"])
        print(f"  转变点(原始 W 尺度): {pts}")
    print(f"\n  {res['note']}")
    return 0
