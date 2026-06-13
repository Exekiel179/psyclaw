"""ARS-Stat — 自动统计分析引擎(纯 stdlib,可选 pingouin)。

把 assume 决策树变成可执行流程:
  数据形态 + 用户指定角色(dv/group/with)→ 自动选检验族
  → 跑假设诊断(正态/方差齐性)→ 违反则切稳健替代(透明记录)
  → 算统计量 + 效应量 + 95%CI → APA7 结果段 → 可复现 .py 脚本 + 数据指纹

机制(v0.2 收紧):
1. 产出三件套:result_*.md(人读)+ result_*.json(机器读 sidecar)
   + repro_*.py(独立复现,含数据指纹 + 统计量容差断言)。
2. **门禁不自证**:本模块不打印"门禁满足",而是在产出后调用
   gates.checker.check_artifact() 独立校验 sidecar,blocking 则退出码 1。
3. 无解析 CI 的效应量(η²、rank-biserial r)用分层 bootstrap 补 CI(种子 12345)。
4. 相关/配对一律 pairwise 完整观测(修正旧版按列独立删失再截断的错位)。
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime
from pathlib import Path

from psyclaw.psych import stats_core as sc
from psyclaw.psych.diagnostics import describe, levene_bf

BOOT_SEED = 12345


# ---------------------------------------------------------------------------
# 数据读取
# ---------------------------------------------------------------------------

def _read_csv(path: Path):
    rawbytes = path.read_bytes()
    fingerprint = hashlib.sha256(rawbytes).hexdigest()[:16]   # 对原始字节哈希,与复现脚本一致
    raw = rawbytes.decode("utf-8", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(raw[:4096], delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(raw), dialect=dialect)
    rows = list(reader)
    return reader.fieldnames or [], rows, fingerprint, dialect.delimiter


def _numcol(rows, col):
    out = []
    for r in rows:
        v = (r.get(col) or "").strip()
        try:
            out.append(float(v))
        except ValueError:
            pass
    return out


def _paircols(rows, c1, c2):
    """pairwise 完整观测:两列同时可解析的行才纳入(修正列向独立删失)。"""
    xs, ys = [], []
    for r in rows:
        try:
            a = float((r.get(c1) or "").strip())
            b = float((r.get(c2) or "").strip())
        except ValueError:
            continue
        xs.append(a)
        ys.append(b)
    return xs, ys


def _groups(rows, dv, group):
    g = {}
    for r in rows:
        v = (r.get(dv) or "").strip()
        k = (r.get(group) or "").strip()
        try:
            g.setdefault(k, []).append(float(v))
        except ValueError:
            pass
    return {k: v for k, v in g.items() if len(v) >= 2}


def _ranks(xs: list) -> list:
    """平均秩(结按均值处理)。"""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


# ---------------------------------------------------------------------------
# APA7 格式化
# ---------------------------------------------------------------------------

def _p(p):
    if p != p:
        return "p = NA"
    return "p < .001" if p < 0.001 else f"p = {p:.3f}".replace("0.", ".")


def _f(v, n=2):
    return f"{v:.{n}f}".replace("-0.", "-.").lstrip("0") if abs(v) < 1 and v == v else f"{v:.{n}f}"


def apa_two_groups(res: dict, dv: str, levene: dict) -> str:
    t, df, p = res["t"], res["df"], res["p"]
    d, (lo, hi) = res["d"], res["d_ci"]
    lev = (f"Levene 检验{'提示方差不齐' if levene['p'] < .05 else '未见方差不齐'}"
           f"(p {_p(levene['p']).split('= ')[-1] if '=' in _p(levene['p']) else '< .001'}),"
           f"故采用 {'Welch 校正' if 'Welch' in res['test'] else 'Student'} t 检验。")
    sig = "显著" if p < .05 else "不显著"
    return (f"针对 {dv} 的{res['test']}结果如下。{lev} "
            f"两组差异{sig},t({df:.1f}) = {t:.2f},{_p(p)},"
            f"Cohen's d = {_f(d)},95% CI [{_f(lo)}, {_f(hi)}]。"
            f"({'组1' } M = {res['m1']:.2f}, SD = {res['sd1']:.2f}, n = {res['n1']};"
            f"组2 M = {res['m2']:.2f}, SD = {res['sd2']:.2f}, n = {res['n2']})。"
            f"\n注:效应量 d 的绝对值"
            f"{'小' if abs(d)<.5 else '中' if abs(d)<.8 else '大'}(Cohen 经验标准);"
            f"统计显著不等同实际重要,请结合 CI 与领域意义解读。")


def apa_paired(res: dict, dv: str) -> str:
    return (f"配对样本 t 检验:t({res['df']}) = {res['t']:.2f},{_p(res['p'])},"
            f"Cohen's dz = {_f(res['d'])},95% CI [{_f(res['d_ci'][0])}, {_f(res['d_ci'][1])}]。"
            f"均值差 = {res['mean_diff']:.2f}(SD = {res['sd_diff']:.2f}, n = {res['n']})。")


def apa_corr(res: dict, x: str, y: str) -> str:
    return (f"{x} 与 {y} 的 Pearson 相关:r({res['df']}) = {_f(res['r'])},"
            f"{_p(res['p'])},95% CI [{_f(res['r_ci'][0])}, {_f(res['r_ci'][1])}]。"
            f"\n注:相关不蕴含因果;非实验设计下仅为统计关联。"
            f"效应量 r 属{'小' if abs(res['r'])<.3 else '中' if abs(res['r'])<.5 else '大'}。")


def apa_anova(res: dict, dv: str, group: str, eta_ci: tuple | None = None) -> str:
    cf, wf, lv = res["classic"], res["welch"], res["levene"]
    use_welch = lv["p"] < .05
    chosen = wf if use_welch else cf
    ci_txt = (f",95% bootstrap CI [{_f(eta_ci[0])}, {_f(eta_ci[1])}]"
              if eta_ci and eta_ci[0] == eta_ci[0] else "")
    return (f"针对 {dv} 按 {group} 的单因素方差分析。"
            f"Levene 检验{'提示方差不齐,采用 Welch ANOVA' if use_welch else '未见方差不齐,采用经典 F'}。"
            f"F({chosen['df1']}, {chosen['df2']:.1f}) = {chosen['F']:.2f},{_p(chosen['p'])},"
            f"η² = {_f(res['eta2'])}{ci_txt},ω² = {_f(res['omega2'])}。"
            f"\n注:大样本下 F 易显著,请以 η²/ω² 与组均值差的实际意义为准;"
            f"事后比较建议 Games-Howell(方差不齐)。")


def apa_chi(res: dict, dv: str, group: str) -> str:
    warn = ("(警告:存在期望频次 < 5 的单元格,建议 Fisher 精确检验)"
            if res["min_expected"] < 5 else "")
    return (f"{dv} 与 {group} 的卡方独立性检验:"
            f"χ²({res['df']}, N = {res['N']}) = {res['chi2']:.2f},{_p(res['p'])},"
            f"Cramér's V = {_f(res['V'])}。{warn}")


# ---------------------------------------------------------------------------
# 复现脚本生成(数据指纹 + 统计量容差断言,失败退出码 1)
# ---------------------------------------------------------------------------

REPRO_TOL = 0.02   # |统计量| 复现容差


def _repro_script(path: str, kind: str, dv: str, second: str,
                  fingerprint: str, expected: dict, delim: str = ",") -> str:
    """expected: {标签: 期望值}。比较取绝对值(组序无关)。"""
    exp_abs = {k: round(abs(float(v)), 4) for k, v in expected.items() if v == v}
    delim_lit = delim.replace("\t", "\\t")
    head = (
        f'"""PsyClaw 复现脚本 — {kind}\n'
        f'数据指纹(SHA-256 前16): {fingerprint}\n'
        f'生成时间: {datetime.now().isoformat(timespec="seconds")}\n'
        f'运行: python this_script.py ;指纹或统计量不符则退出码 1\n'
        f'"""\n'
        'import hashlib, json, sys\n'
        'import numpy as np\n'
        'import pandas as pd\n'
        'import scipy.stats as ss\n\n'
        f'DATA = r"{path}"\n'
        f"EXPECTED = json.loads('{json.dumps(exp_abs)}')  # 绝对值比较\n"
        f'TOL = {REPRO_TOL}\n\n'
        f'df = pd.read_csv(DATA, sep="{delim_lit}")\n'
        'fp = hashlib.sha256(open(DATA, "rb").read()).hexdigest()[:16]\n'
        f'if fp != "{fingerprint}":\n'
        f'    print(f"✗ 数据指纹不符(期望 {fingerprint},实得 {{fp}}),复现中止")\n'
        '    sys.exit(1)\n\n'
    )
    tail = (
        '\nprint("复现值:", {k: round(abs(v), 4) for k, v in got.items()})\n'
        'bad = {k: {"期望": v, "实得": round(abs(got[k]), 4)}\n'
        '       for k, v in EXPECTED.items()\n'
        '       if k not in got or abs(abs(got[k]) - v) > TOL}\n'
        'if bad:\n'
        '    print("✗ 统计量未在容差内复现:", bad)\n'
        '    sys.exit(1)\n'
        f'print("✓ 数据指纹与统计量均复现一致(容差 ±{REPRO_TOL})")\n'
    )
    return head + _repro_body(kind, dv, second) + tail


def _repro_body(kind: str, dv: str, second: str) -> str:
    if kind == "两组比较":
        return (
            f'sub = df[["{dv}", "{second}"]].copy()\n'
            f'sub["{dv}"] = pd.to_numeric(sub["{dv}"], errors="coerce")\n'
            'sub = sub.dropna()\n'
            f'gs = [g["{dv}"].to_numpy() for _, g in sub.groupby("{second}") if len(g) >= 2]\n'
            'a, b = gs[0], gs[1]\n'
            't, p = ss.ttest_ind(a, b, equal_var=False)  # Welch 默认\n'
            'n1, n2 = len(a), len(b)\n'
            'sp = np.sqrt(((n1-1)*a.var(ddof=1) + (n2-1)*b.var(ddof=1)) / (n1+n2-2))\n'
            'd = (a.mean() - b.mean()) / sp\n'
            'print(f"Welch t={t:.3f}, p={p:.4f}, Cohen d={d:.3f}")\n'
            'got = {"t": float(t), "d": float(d)}\n')
    if kind == "两组比较(Mann-Whitney)":
        return (
            f'sub = df[["{dv}", "{second}"]].copy()\n'
            f'sub["{dv}"] = pd.to_numeric(sub["{dv}"], errors="coerce")\n'
            'sub = sub.dropna()\n'
            f'gs = [g["{dv}"].to_numpy() for _, g in sub.groupby("{second}") if len(g) >= 2]\n'
            'a, b = gs[0], gs[1]\n'
            'u1, p = ss.mannwhitneyu(a, b, alternative="two-sided")\n'
            'U = min(float(u1), len(a)*len(b) - float(u1))  # 组序无关\n'
            'print(f"Mann-Whitney U={U:.1f}, p={p:.4f}")\n'
            'got = {"U": U}\n')
    if kind == "配对比较":
        return (
            f'sub = df[["{dv}", "{second}"]].apply(pd.to_numeric, errors="coerce").dropna()\n'
            f'x, y = sub["{dv}"], sub["{second}"]\n'
            't, p = ss.ttest_rel(x, y)\n'
            'diff = x - y\n'
            'dz = diff.mean() / diff.std(ddof=1)\n'
            'print(f"paired t={t:.3f}, p={p:.4f}, dz={dz:.3f}")\n'
            'got = {"t": float(t), "dz": float(dz)}\n')
    if kind == "相关":
        return (
            f'sub = df[["{dv}", "{second}"]].apply(pd.to_numeric, errors="coerce").dropna()\n'
            f'r, p = ss.pearsonr(sub["{dv}"], sub["{second}"])  # pairwise 完整观测\n'
            'print(f"r={r:.3f}, p={p:.4f}")\n'
            'got = {"r": float(r)}\n')
    if kind == "方差分析":
        return (
            f'sub = df[["{dv}", "{second}"]].copy()\n'
            f'sub["{dv}"] = pd.to_numeric(sub["{dv}"], errors="coerce")\n'
            'sub = sub.dropna()\n'
            f'gs = [g["{dv}"].to_numpy() for _, g in sub.groupby("{second}") if len(g) >= 2]\n'
            'F, p = ss.f_oneway(*gs)\n'
            'allv = np.concatenate(gs)\n'
            'ss_b = sum(len(g)*(g.mean()-allv.mean())**2 for g in gs)\n'
            'eta2 = ss_b / ((allv-allv.mean())**2).sum()\n'
            '# 方差不齐稳健对照:Alexander-Govern(注意并非 Welch ANOVA;\n'
            '# Welch ANOVA 可用 pingouin.welch_anova)\n'
            'print(f"classic F={F:.3f}, p={p:.4f}, eta2={eta2:.4f}")\n'
            'got = {"F": float(F), "eta2": float(eta2)}\n')
    return '# (该检验类型的复现脚本模板待补)\ngot = {}\n'


# ---------------------------------------------------------------------------
# 决策树主入口
# ---------------------------------------------------------------------------

def analyze(path: str, dv: str, group: str | None = None,
            with_var: str | None = None, paired_with: str | None = None,
            project_dir: str = ".", cluster: str | None = None) -> int:
    from psyclaw import ui
    fp = Path(path)
    if not fp.exists():
        print(f"文件不存在:{path}")
        return 1
    fields, rows, fingerprint, delim = _read_csv(fp)
    print(ui.title(f"ARS-Stat 自动分析 — {fp.name}"))
    print(ui.rule())
    print(ui.dim(f"数据指纹 {fingerprint} · {len(rows)} 行 · 列: {', '.join(fields)[:80]}"))

    # —— 澄清卡状态(standalone stat 仅警告;/research 与 loop 阻断)——
    clar_resolved = None
    try:
        from psyclaw.psych.clarify import check_card
        card = check_card(project_dir)
        clar_resolved = card["exists"] and not card["unresolved"]
        if not clar_resolved:
            print(ui.warn(f"  ⚠ 澄清卡未完成({card['resolved']}/{card['total']})。"
                          "standalone 分析仅警告;/research 会被 CLARIFY.complete 阻断。"))
    except Exception:  # noqa: BLE001
        pass

    apa = ""
    kind = ""
    second = ""
    # 结构化 sidecar(机器读;门禁独立校验的对象)
    meta: dict = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "data_file": str(fp.resolve()),
        "n_rows": len(rows),
        "data_fingerprint": fingerprint,
        "clarification_resolved": clar_resolved,
        "assumptions_checked": [],
        "robustness": [],
    }

    def _assume(name, method, **kw):
        meta["assumptions_checked"].append({"name": name, "method": method, **kw})

    # 引擎:pingouin(默认核心,效应量+CI+功效+BF 一次出全)优先,缺失回落 stdlib
    try:
        from psyclaw.psych import pingouin_backend as pgb
        use_pg = pgb.available()
    except Exception:  # noqa: BLE001
        pgb, use_pg = None, False
    meta["engine"] = "pingouin" if use_pg else "stdlib"
    print(ui.dim("引擎:pingouin(功效+BF 一次出全)" if use_pg
                 else "引擎:内置 stdlib(对照 scipy;装 pingouin 得功效+BF)"))

    # —— A-1 特判:Likert 单题检测 ——
    from psyclaw.psych.decision_tree import (
        detect_likert, large_sample_effect_language, compute_icc)
    dv_vals = _numcol(rows, dv)
    if dv_vals:
        lik = detect_likert(dv_vals)
        if lik.get("is_likert"):
            print(ui.warn(f"\n⚠ Likert 单题: {dv} — {lik['recommendation']}"))
            meta["likert_detected"] = lik

    # —— A-1 特判:嵌套数据 ICC ——
    if cluster:
        icc_res = compute_icc(rows, dv, cluster)
        meta["icc"] = icc_res
        print(ui.accent(f"\n嵌套数据 ICC(1) — cluster: {cluster}"))
        if "error" not in icc_res:
            print(f"  ICC(1) = {icc_res['icc']:.4f}  ({icc_res['interpretation']})")
            print(f"  k = {icc_res['k_clusters']} clusters, N = {icc_res['N']}")
            if icc_res["icc"] >= 0.05:
                print(ui.warn(
                    "  ⚠ ICC ≥ .05:建议改用多层线性模型(MLM/lme4)处理非独立性;"
                    "忽视聚类会使 SE 偏小、I 类错误膨胀。"))
        else:
            print(ui.warn(f"  ICC 计算失败:{icc_res.get('error')}"))

    # —— 决策树 ——
    if with_var:  # 相关
        kind, second = "相关", with_var
        x, y = _paircols(rows, dv, with_var)   # pairwise 完整观测
        if len(x) < 4:
            print(ui.err("  有效配对观测 < 4,无法做相关"))
            return 1
        print(ui.accent("\n① 检验选择:两连续变量 → Pearson 相关"))
        dx, dy = describe(x), describe(y)
        print(f"  {dv}: 偏度 {dx.get('skew',0):.2f} · {with_var}: 偏度 {dy.get('skew',0):.2f}"
              f" · pairwise n = {len(x)}")
        _assume("normality", "skewness",
                detail=f"{dv} skew={dx.get('skew',0):.2f}; {with_var} skew={dy.get('skew',0):.2f}")
        _assume("homogeneity", "not_applicable", detail="相关分析无组间方差齐性前提")
        _assume("independence", "declared", detail="横断独立观测假设,未检验")
        res = sc.pearson_r(x, y)
        if abs(dx.get("skew", 0)) > 2 or abs(dy.get("skew", 0)) > 2:
            print(ui.warn("  ⚠ 偏度大,Pearson 可能失真;已加跑 Spearman 稳健对照"))
        # 稳健对照:Spearman(秩上的 Pearson)
        rho = sc.pearson_r(_ranks(x), _ranks(y))
        if "r" in rho:
            meta["robustness"].append(
                f"Spearman ρ = {rho['r']:.3f}({_p(rho['p'])})— 秩稳健对照")
        if use_pg:
            rr = pgb.corr(x, y)
            raw = rr["raw"]
            ci = [float(v) for v in raw.get("CI95", [float('nan')]*2)]
            apa = rr["apa"]
            meta["statistics"] = {"r": float(raw["r"]), "p": float(raw["p_val"]),
                                  "n": int(raw["n"])}
            meta["effect_size"] = {"name": "r", "value": float(raw["r"]), "ci": ci}
        else:
            apa = apa_corr(res, dv, with_var)
            meta["statistics"] = {"r": res["r"], "t": res["t"],
                                  "df": res["df"], "p": res["p"]}
            meta["effect_size"] = {"name": "r", "value": res["r"],
                                   "ci": list(res["r_ci"])}
        expected = {"r": meta["statistics"]["r"]}

    elif paired_with:  # 配对
        kind, second = "配对比较", paired_with
        x, y = _paircols(rows, dv, paired_with)   # pairwise 完整观测
        if len(x) < 3:
            print(ui.err("  有效配对观测 < 3,无法做配对比较"))
            return 1
        print(ui.accent("\n① 检验选择:配对设计 → 配对样本 t"))
        diff = [a - b for a, b in zip(x, y)]
        dd = describe(diff)
        print(f"  差值偏度 {dd.get('skew',0):.2f},峰度 {dd.get('kurt',0):.2f}"
              f" · pairwise n = {len(x)}")
        _assume("normality", "skewness(差值)", detail=f"skew={dd.get('skew',0):.2f}")
        _assume("homogeneity", "not_applicable", detail="配对设计无组间方差齐性前提")
        _assume("independence", "declared", detail="配对内相依由设计处理;对子间独立假设")
        if abs(dd.get("skew", 0)) > 2:
            print(ui.warn("  ⚠ 差值偏态,建议 Wilcoxon 符号秩(稳健替代)"))
            meta["robustness"].append("差值偏态告警:建议 Wilcoxon 符号秩复核")
        res = sc.paired_ttest(x, y)
        if use_pg:
            rr = pgb.ttest(x, y, paired=True)
            apa = rr["apa"]
            meta["statistics"] = {"t": float(rr["raw"]["T"]),
                                  "df": float(rr["raw"]["dof"]),
                                  "p": float(rr["raw"]["p_val"])}
            meta["effect_size"] = {"name": "Cohen's dz", "value": rr["d"],
                                   "ci": rr["d_ci"]}
        else:
            apa = apa_paired(res, dv)
            meta["statistics"] = {"t": res["t"], "df": res["df"], "p": res["p"]}
            meta["effect_size"] = {"name": "Cohen's dz", "value": res["d"],
                                   "ci": list(res["d_ci"])}
        expected = {"t": meta["statistics"]["t"],
                    "dz": meta["effect_size"]["value"]}

    elif group:
        gd = _groups(rows, dv, group)
        ng = len(gd)
        if ng < 2:
            print(ui.err(f"  分组列 {group} 有效组 < 2,无法比较"))
            return 1
        glist = list(gd.values())
        if ng == 2:  # 两组
            kind, second = "两组比较", group
            print(ui.accent("\n① 检验选择:两组 → 独立样本 t"))
            print(ui.accent("② 假设诊断"))
            lev = levene_bf(glist)
            skews = {}
            for name, xs in gd.items():
                d = describe(xs)
                skews[name] = d.get("skew", 0)
                flag = " ⚠偏态" if abs(d.get("skew", 0)) > 2 else ""
                print(f"  [{name}] n={d['n']} M={d['mean']:.2f} SD={d['sd']:.2f} 偏度{d.get('skew',0):.2f}{flag}")
            print(f"  Levene 方差齐性 p = {lev['p']:.3f}")
            _assume("homogeneity", "Levene(BF)", p=lev["p"])
            _assume("normality", "skewness",
                    detail="; ".join(f"{k} skew={v:.2f}" for k, v in skews.items()))
            _assume("independence", "declared", detail="组间独立观测假设,未检验")
            sev = any(abs(v) > 2 for v in skews.values())
            if sev:
                print(ui.warn("③ 正态严重违反 → 自动切换稳健替代:Mann-Whitney U"))
                kind = "两组比较(Mann-Whitney)"
                res = sc.mann_whitney(*glist)
                r_ci = sc.bootstrap_ci(
                    glist, lambda gs: sc.mann_whitney(gs[0], gs[1])["r"],
                    seed=BOOT_SEED)
                apa = (f"因正态假设严重违反,采用 Mann-Whitney U 检验:"
                       f"U = {res['U']:.1f},z = {res['z']:.2f},{_p(res['p'])},"
                       f"rank-biserial r = {_f(res['r'])},"
                       f"95% bootstrap CI [{_f(r_ci[0])}, {_f(r_ci[1])}]。")
                meta["statistics"] = {"U": res["U"], "z": res["z"], "p": res["p"]}
                meta["effect_size"] = {"name": "rank-biserial r",
                                       "value": res["r"], "ci": list(r_ci)}
                # 稳健对照:Welch t(透明交叉验证)
                wt = sc.welch_ttest(*glist)
                if "error" not in wt:
                    meta["robustness"].append(
                        f"Welch t 对照:t({wt['df']:.1f})={wt['t']:.2f},{_p(wt['p'])}")
                meta["robustness"].append("主分析本身为稳健检验(正态违反触发)")
                expected = {"U": res["U"]}
            else:
                print(ui.accent("③ 默认 Welch t(无论方差齐否,现代规范)"))
                res = sc.welch_ttest(*glist)
                if use_pg:
                    a, b = glist
                    rr = pgb.ttest(a, b, paired=False)
                    apa = rr["apa"]
                    meta["statistics"] = {"t": float(rr["raw"]["T"]),
                                          "df": float(rr["raw"]["dof"]),
                                          "p": float(rr["raw"]["p_val"])}
                    meta["effect_size"] = {"name": "Cohen's d", "value": rr["d"],
                                           "ci": rr["d_ci"]}
                else:
                    apa = apa_two_groups(res, dv, lev)
                    meta["statistics"] = {"t": res["t"], "df": res["df"], "p": res["p"]}
                    meta["effect_size"] = {"name": "Cohen's d", "value": res["d"],
                                           "ci": list(res["d_ci"])}
                # 稳健对照:Mann-Whitney(透明交叉验证)
                mw = sc.mann_whitney(*glist)
                meta["robustness"].append(
                    f"Mann-Whitney 对照:U={mw['U']:.1f},{_p(mw['p'])},r={mw['r']:.2f}")
                expected = {"t": meta["statistics"]["t"],
                            "d": meta["effect_size"]["value"]}
        else:  # 多组
            kind, second = "方差分析", group
            print(ui.accent(f"\n① 检验选择:{ng} 组 → 单因素 ANOVA"))
            print(ui.accent("② 假设诊断 + Welch 自适应"))
            res = sc.oneway_anova_full(glist)
            print(f"  Levene p = {res['levene']['p']:.3f} → "
                  f"{'Welch ANOVA' if res['levene']['p']<.05 else '经典 F'}")
            _assume("homogeneity", "Levene(BF)", p=res["levene"]["p"])
            _assume("normality", "skewness",
                    detail="; ".join(f"组{i+1} skew={describe(g).get('skew',0):.2f}"
                                     for i, g in enumerate(glist)))
            _assume("independence", "declared", detail="组间独立观测假设,未检验")
            eta_ci = sc.bootstrap_ci(glist, sc.eta_squared, seed=BOOT_SEED)
            apa = apa_anova(res, dv, group, eta_ci=eta_ci)
            use_welch = res["levene"]["p"] < .05
            chosen = res["welch"] if use_welch else res["classic"]
            meta["statistics"] = {"F": chosen["F"], "df1": chosen["df1"],
                                  "df2": chosen["df2"], "p": chosen["p"],
                                  "variant": "Welch" if use_welch else "classic"}
            meta["effect_size"] = {"name": "eta^2", "value": res["eta2"],
                                   "ci": list(eta_ci)}
            meta["robustness"].append(
                f"经典 F={res['classic']['F']:.2f} vs Welch F={res['welch']['F']:.2f}"
                "(双轨对照)")
            expected = {"F": res["classic"]["F"], "eta2": res["eta2"]}
    else:
        print(ui.err("  需指定 --group(分组比较)、--with(相关)或 --paired(配对)之一"))
        return 1

    meta["test"] = kind

    # —— A-1 特判:大样本效应量语言 ——
    es = meta.get("effect_size", {})
    stat = meta.get("statistics", {})
    if es and "value" in es and "p" in stat:
        n_for_ls = (
            stat.get("n") or                          # 相关
            (res.get("n") if "n" in dir(res) else None) or   # 配对
            len(rows)                                 # fallback
        )
        ls = large_sample_effect_language(
            int(n_for_ls or len(rows)),
            es.get("name", ""),
            float(es.get("value", float("nan"))),
            float(stat.get("p", 1.0)),
        )
        if ls["message"]:
            print(ui.warn(f"\n{ls['message']}"))
            meta["large_sample_warning"] = ls
            if ls["trivial"]:
                apa = apa + f"\n{ls['message']}"

    # —— 输出 APA7 段 ——
    print(ui.accent("\n④ APA7 结果段"))
    print(ui.panel("结果(可直接入论文)", apa))

    # —— 复现脚本 + sidecar 落盘 ——
    out_dir = Path(project_dir) / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    script = _repro_script(str(fp.resolve()), kind, dv, second, fingerprint,
                           expected, delim=delim)
    safe_kind = kind.replace("(", "_").replace(")", "")
    sp = out_dir / f"repro_{safe_kind}_{dv}.py"
    sp.write_text(script, encoding="utf-8")
    rp = out_dir / f"result_{safe_kind}_{dv}.md"
    rp.write_text(f"# ARS-Stat 结果\n\n数据指纹: {fingerprint}\n\n{apa}\n", encoding="utf-8")
    meta["repro_script"] = sp.name
    jp = out_dir / f"result_{safe_kind}_{dv}.json"
    jp.write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=float),
                  encoding="utf-8")
    print(ui.ok("\n⑤ 已落盘:"))
    print(f"    {rp}")
    print(f"    {jp}  ← 结构化 sidecar(门禁校验对象)")
    print(f"    {sp}  ← 可独立运行复现,含数据指纹 + 统计量容差断言")

    # —— 门禁:独立校验(checker 解析 sidecar,不靠产出方自证)——
    from psyclaw.gates.checker import check_artifact, format_report
    gate = check_artifact(str(jp), "stat")
    print(ui.accent("\n⑥ 门禁独立校验(gates.checker)"))
    for line in format_report(gate).splitlines():
        print(f"  {line}")
    if not gate["passed"]:
        print(ui.err("  产出未过门禁,退出码 1(修复后重跑)"))
        return 1
    return 0


def analyze_advanced(path: str, method: str, **kw) -> int:
    """高级方法走 R 后端(SEM/CFA/MLM/omega)。"""
    from psyclaw import ui
    from psyclaw.psych import r_backend as rb
    print(ui.title(f"ARS-Stat 高级方法 — {method}"))
    print(ui.rule())
    if not rb.r_available():
        print(ui.warn("未检测到 Rscript。将输出可运行 R 脚本骨架(装 R 后可跑)。"))
    m = method.lower()
    if m in ("cfa", "sem"):
        model = kw.get("model") or "F1 =~ q1 + q2 + q3"
        out = rb.cfa(path, model, ordered=kw.get("ordered", False)) if m == "cfa" \
            else rb.sem(path, model)
    elif m == "mlm":
        out = rb.mlm(path, kw.get("formula", "y ~ x + (1 | cluster)"), kw.get("group", "cluster"))
    elif m == "omega":
        items = kw.get("items") or []
        out = rb.omega(path, items)
    elif m == "invariance":
        out = rb.invariance(path, kw.get("model", "F1 =~ q1 + q2 + q3"), kw.get("group", "group"))
    else:
        print(ui.err(f"未知方法 {method}。支持:cfa/sem/mlm/omega/invariance"))
        return 1
    print(out)
    return 0


def analyze_cli(argv: list) -> int:
    if not argv:
        print("用法:psyclaw stat <data.csv> --dv <列> [--group <列> | --with <列> | --paired <列>]")
        return 1
    path = argv[0]
    dv = group = with_var = paired = None
    if "--dv" in argv:
        dv = argv[argv.index("--dv")+1]
    if "--group" in argv:
        group = argv[argv.index("--group")+1]
    if "--with" in argv:
        with_var = argv[argv.index("--with")+1]
    if "--paired" in argv:
        paired = argv[argv.index("--paired")+1]
    if not dv:
        print("必须指定 --dv")
        return 1
    return analyze(path, dv, group, with_var, paired)
