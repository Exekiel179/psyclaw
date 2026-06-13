"""Pingouin 后端 — 心理学统计的"一次出全"引擎。

Pingouin(Vallat 2018, JOSS)是为心理学设计的 Python 统计库:一个函数同时给出
统计量 + 效应量 + 置信区间 + 统计功效 + 贝叶斯因子。相比 scipy 只给 t/p,
它正好满足 PSYCLAW 的"效应量+CI 必报"门禁。

PsyClaw 默认依赖 pingouin;ARS-Stat 优先用它,缺失时回落纯 stdlib(stats_core)。
本模块把 pingouin 结果统一成 APA7 文本。覆盖心理学高频:
  独立/配对 t、单因素/重复测量/混合/ANCOVA、相关(含偏/稳健)、
  bootstrap 中介、信度(Cronbach α)、功效分析、FDR 多重比较。
"""

from __future__ import annotations


def available() -> bool:
    try:
        import pingouin  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _fmt_p(p) -> str:
    try:
        p = float(p)
    except (TypeError, ValueError):
        return "p = NA"
    return "p < .001" if p < 0.001 else f"p = {p:.3f}".replace("0.", ".")


def _f(v, n=2) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "NA"
    s = f"{v:.{n}f}"
    return s.replace("-0.", "-.").lstrip("0") if abs(v) < 1 else s


# ---------------------------------------------------------------------------
# t 检验(独立 / 配对)—— 一次给 d + CI + 功效 + BF
# ---------------------------------------------------------------------------

def ttest(x, y, paired: bool = False) -> dict:
    import math

    import pingouin as pg
    r = pg.ttest(x, y, paired=paired).round(4).to_dict("records")[0]
    # 注意:pingouin 的 CI95 是【均值差】的 CI,不是 d 的 CI —— 分开标注。
    diff_ci = [float(v) for v in r.get("CI95", [float("nan")] * 2)]
    d = float(r["cohen_d"])
    n1, n2 = len(x), len(y)
    if paired:
        n = min(n1, n2)
        se_d = math.sqrt(1 / n + d ** 2 / (2 * n))
    else:
        se_d = math.sqrt((n1 + n2) / (n1 * n2) + d ** 2 / (2 * (n1 + n2)))
    d_ci = (d - 1.959964 * se_d, d + 1.959964 * se_d)
    eff = "Cohen's dz" if paired else "Cohen's d"
    apa = (f"{'配对' if paired else '独立'}样本 t 检验:t({int(r['dof'])}) = {r['T']:.2f},"
           f"{_fmt_p(r['p_val'])},{eff} = {_f(d)},"
           f"95% CI [{_f(d_ci[0])}, {_f(d_ci[1])}]"
           f"(均值差 95% CI [{_f(diff_ci[0])}, {_f(diff_ci[1])}]),"
           f"统计功效 = {_f(r.get('power'),2)},BF₁₀ = {r.get('BF10')}。"
           f"\n注:BF₁₀>3 为支持备择的中等以上证据;效应量绝对值"
           f"{'小' if abs(d)<.5 else '中' if abs(d)<.8 else '大'}。")
    return {"engine": "pingouin", "raw": r, "apa": apa,
            "d": d, "d_ci": list(d_ci), "diff_ci": diff_ci}


# ---------------------------------------------------------------------------
# 方差分析家族
# ---------------------------------------------------------------------------

def anova(data, dv: str, between, detailed: bool = True) -> dict:
    import pingouin as pg
    aov = pg.anova(data=data, dv=dv, between=between, detailed=detailed).round(4)
    row = aov[aov["Source"] == (between if isinstance(between, str) else between[0])]
    r = row.to_dict("records")[0] if len(row) else aov.to_dict("records")[0]
    np2 = r.get("np2", r.get("n2"))
    apa = (f"单因素方差分析(between={between}):F({int(r['DF'])}, "
           f"{int(aov[aov['Source']=='Within']['DF'].iloc[0]) if 'Within' in aov['Source'].values else '?'}) "
           f"= {r['F']:.2f},{_fmt_p(r.get('p_unc'))},偏 η² = {_f(np2)}。"
           f"\n注:Welch 不齐时用 welch_anova;事后用 pairwise_tukey/Games-Howell。")
    return {"engine": "pingouin", "table": aov.to_dict("records"), "apa": apa}


def rm_anova(data, dv: str, within, subject: str) -> dict:
    """重复测量 ANOVA —— 含球形性与 ε 校正(stdlib 版做不到)。"""
    import pingouin as pg
    aov = pg.rm_anova(data=data, dv=dv, within=within, subject=subject,
                      detailed=True, correction=True).round(4)
    recs = aov.to_dict("records")
    r = recs[0]                      # 效应行
    df_eff = r.get("DF")
    df_err = recs[1].get("DF") if len(recs) > 1 else None
    # rm_anova 自带球形性列 W_spher / p_spher
    wsph, psph = r.get("W_spher"), r.get("p_spher")
    sph = ""
    if psph is not None:
        sph = (f"Mauchly 球形性 W = {_f(wsph)}, {_fmt_p(psph)};"
               f"{'违反,用 Greenhouse-Geisser 校正' if psph < .05 else '满足'}。")
    gg = r.get("p_GG_corr")
    apa = (f"重复测量方差分析(within={within}):{sph} "
           f"F({_f(df_eff,0)}, {_f(df_err,0)}) = {r['F']:.2f},{_fmt_p(r.get('p_unc'))}"
           + (f"(GG 校正 {_fmt_p(gg)})" if gg is not None else "")
           + f",ng² = {_f(r.get('ng2'))},ε = {_f(r.get('eps'))}。"
           f"\n注:ε<.75 用 GG,否则 HF;现代亦可改用混合效应模型。")
    return {"engine": "pingouin", "table": recs, "apa": apa}


def mixed_anova(data, dv: str, within: str, between: str, subject: str) -> dict:
    import pingouin as pg
    aov = pg.mixed_anova(data=data, dv=dv, within=within, between=between,
                         subject=subject).round(4)
    inter = aov[aov["Source"] == "Interaction"].to_dict("records")
    r = inter[0] if inter else aov.to_dict("records")[-1]
    apa = (f"混合设计方差分析(被试间 {between} × 被试内 {within}):"
           f"交互 F({_f(r.get('DF1'),0)}, {_f(r.get('DF2'),0)}) = {r['F']:.2f},"
           f"{_fmt_p(r.get('p_unc'))},偏 η² = {_f(r.get('np2'))}。"
           f"\n注:干预效应=组×时间交互;勿用'一组显著另一组不显著'推断差异。")
    return {"engine": "pingouin", "table": aov.to_dict("records"), "apa": apa}


def ancova(data, dv: str, between: str, covar) -> dict:
    import pingouin as pg
    aov = pg.ancova(data=data, dv=dv, between=between, covar=covar).round(4)
    r = aov[aov["Source"] == between].to_dict("records")[0]
    apa = (f"协方差分析(控制 {covar}):{between} 的 F({int(r['DF'])}, "
           f"{int(aov[aov['Source']=='Residual']['DF'].iloc[0])}) = {r['F']:.2f},"
           f"{_fmt_p(r.get('p_unc'))},偏 η² = {_f(r.get('np2'))}。"
           f"\n注:随机实验中 ANCOVA 提升功效;非随机分组慎用(Lord 悖论);"
           f"先验证回归斜率同质性(组×协变量交互不显著)。")
    return {"engine": "pingouin", "table": aov.to_dict("records"), "apa": apa}


# ---------------------------------------------------------------------------
# 相关(含偏相关 / 稳健)+ 中介
# ---------------------------------------------------------------------------

def corr(x, y, method: str = "pearson") -> dict:
    import pingouin as pg
    r = pg.corr(x, y, method=method).round(4).to_dict("records")[0]
    ci = r.get("CI95", [None, None])
    apa = (f"{method} 相关:r({int(r['n'])-2}) = {_f(r['r'])},{_fmt_p(r['p_val'])},"
           f"95% CI [{_f(ci[0])}, {_f(ci[1])}]"
           + (f",BF₁₀ = {r.get('BF10')}" if r.get('BF10') else "")
           + (f",功效 = {_f(r.get('power'),2)}" if r.get('power') else "") + "。"
           f"\n注:相关不蕴含因果;离群多或非线性时用 method='bicor'(稳健)或 'spearman'。")
    return {"engine": "pingouin", "raw": r, "apa": apa}


def mediation(data, x: str, m: str, y: str, n_boot: int = 5000) -> dict:
    """中介分析 —— bootstrap 间接效应 CI(禁 Sobel)。"""
    import pingouin as pg
    res = pg.mediation_analysis(data=data, x=x, m=m, y=y, n_boot=n_boot, seed=12345).round(4)
    ind = res[res["path"] == "Indirect"].to_dict("records")[0]
    apa = (f"中介分析({x}→{m}→{y},{n_boot} 次 bootstrap):"
           f"间接效应 = {_f(ind['coef'])},95% CI [{_f(ind['CI2.5'])}, "
           f"{_f(ind['CI97.5'])}],{'显著(CI 不含 0)' if ind.get('sig')=='Yes' else '不显著'}。"
           f"\n注:bootstrap CI 优于 Sobel(Preacher & Hayes 2008);"
           f"横断中介只是统计分解,不证因果(Maxwell & Cole 2007)。")
    return {"engine": "pingouin", "table": res.to_dict("records"), "apa": apa}


# ---------------------------------------------------------------------------
# 信度 + 功效
# ---------------------------------------------------------------------------

def reliability(data, items=None) -> dict:
    import pingouin as pg
    sub = data[items] if items else data
    a = pg.cronbach_alpha(data=sub)
    interp = ("优(>.95 注意冗余)" if a[0] >= .9 else "良" if a[0] >= .8 else
              "可接受" if a[0] >= .7 else "勉强" if a[0] >= .6 else "差")
    apa = (f"Cronbach's α = {_f(a[0])},95% CI [{_f(a[1][0])}, {_f(a[1][1])}]({interp})。"
           f"\n注:α 仅 tau 等价下准确;条件允许时加报 McDonald's ω(McNeish 2018)。")
    return {"engine": "pingouin", "alpha": a[0], "ci": list(a[1]), "apa": apa}


def power_ttest(d: float = None, n: int = None, power: float = None,
                alpha: float = 0.05, contrast: str = "two-samples") -> dict:
    import pingouin as pg
    val = pg.power_ttest(d=d, n=n, power=power, alpha=alpha, contrast=contrast)
    if n is None:
        apa = (f"先验功效分析(d={d}, α={alpha}, 功效={power}, {contrast}):"
               f"每组需 N = {val:.0f}。"
               f"\n注:心理学效应量先验建议 d≈.40(Richard 2003);交互效应需更大 N。")
        return {"engine": "pingouin", "required_n": float(val), "apa": apa}
    apa = f"达成功效 = {_f(val,2)}(d={d}, n={n}, α={alpha})。"
    return {"engine": "pingouin", "achieved_power": float(val), "apa": apa}
