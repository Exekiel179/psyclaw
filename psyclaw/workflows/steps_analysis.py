"""实证分析流程(analysis)的 Step 与子功能。

统计外移:`analysis` **不在仓内算**——`generate_analysis_script` 据数据结构推荐分析,
生成委托 pingouin/scipy 的可复现脚本(outputs/analysis.py),由用户在 [stats] 环境跑或交 MCP。
PsyClaw 只做:画像数据 → 生成设计/分析计划 → 推荐分析 + 出脚本 → 写作 → 评审。

`profile_data` / `recommend_analysis` / `generate_analysis_script` 都是独立纯函数(可单测/单用)。
"""

from __future__ import annotations

import csv
import re
from pathlib import Path


def _is_float(v: str) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


# 因变量语义选择(feat-100):结局语义优先,基线/人口学列绝不当 DV——
# 第二轮对抗评估实测「拿第一个数值列」把基线 pre_score 当结局变量,静默产出无意义统计。
_DV_PREFER = re.compile(r"post|后测|outcome|结局|follow|final|t2\b", re.IGNORECASE)
_DV_AVOID = re.compile(r"pre|baseline|前测|基线|age|年龄|gender|性别|sex"
                       r"|id$|编号|序号|时间戳", re.IGNORECASE)


def _pick_dv(numeric: list[str]) -> str:
    """从数值列挑因变量:post/outcome 语义 > 非基线非人口学 > 兜底第一列。"""
    prefer = [c for c in numeric if _DV_PREFER.search(c)]
    if prefer:
        return prefer[0]
    neutral = [c for c in numeric if not _DV_AVOID.search(c)]
    if neutral:
        return neutral[0]
    return numeric[0]


# 常见缺失码(feat-100):99/-999 等混进数值列会静默污染统计
_MISSING_CODES = (99.0, -99.0, 999.0, -999.0, 9999.0, -9999.0)
_ID_COL = re.compile(r"subject|participant|被试|编号|受试|^id$|_id$", re.IGNORECASE)


def data_quality_flags(csv_path: str, profile: dict) -> list[dict]:
    """三类数据质量信号(纯函数,feat-100):重复被试 id / 疑似缺失码 / 微型组。

    第二轮对抗评估实测三类全部零检测:S01 整行重复、99/-999 混入 post_score、
    等待组 n=2 均被静默送进 ANOVA。只警示不修数据——处理决策留给研究者,
    但绝不静默。返回 [{kind, column, detail}]。
    """
    p = Path(csv_path)
    with p.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    flags: list[dict] = []

    for col in profile.get("categorical", []):
        if not _ID_COL.search(col):
            continue
        vals = [(r.get(col) or "").strip() for r in rows if (r.get(col) or "").strip()]
        dups = sorted({v for v in vals if vals.count(v) > 1})
        if dups:
            flags.append({"kind": "duplicate_id", "column": col,
                          "detail": f"被试标识列 {col} 存在重复值(非独立观测风险):"
                                    f"{', '.join(dups[:5])}"})

    for col in profile.get("numeric", []):
        nums = []
        for r in rows:
            v = (r.get(col) or "").strip()
            if v and _is_float(v):
                nums.append(float(v))
        codes = sorted({v for v in nums if v in _MISSING_CODES})
        others = [v for v in nums if v not in _MISSING_CODES]
        if not codes or not others:
            continue
        mean = sum(others) / len(others)
        sd = (sum((x - mean) ** 2 for x in others) / len(others)) ** 0.5
        suspicious = [c for c in codes
                      if (sd and abs(c - mean) > 3 * sd)
                      or (not sd and c != mean)
                      or (c < 0 and min(others) >= 0)]
        if suspicious:
            flags.append({"kind": "missing_code", "column": col,
                          "detail": f"数值列 {col} 出现疑似缺失码取值 "
                                    f"{', '.join(f'{c:g}' for c in suspicious)}"
                                    "(远离其余分布)——请核对编码表,勿当真实分数混入"})

    for c in profile.get("columns", []):
        if c["kind"] != "categorical" or not (2 <= c.get("n_levels", 0) <= 12) \
                or _ID_COL.search(c["name"]):
            continue
        counts: dict[str, int] = {}
        for r in rows:
            v = (r.get(c["name"]) or "").strip()
            if v:
                counts[v] = counts.get(v, 0) + 1
        tiny = {k: n for k, n in counts.items() if n < 5}
        if tiny:
            flags.append({"kind": "tiny_group", "column": c["name"],
                          "detail": f"分组列 {c['name']} 存在微型组(n<5):"
                                    + ", ".join(f"{k}(n={n})" for k, n in tiny.items())
                                    + "——组间比较对其极不稳定"})
    return flags


def profile_data(csv_path: str) -> dict:
    """画像数据:逐列判数值/分类(含水平数)。fail-closed:文件不存在/空 抛 ValueError。"""
    p = Path(csv_path)
    if not p.exists():
        raise ValueError(f"数据文件不存在:{csv_path}")
    with p.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError("数据 CSV 为空")

    columns, numeric, categorical = [], [], []
    for c in rows[0].keys():
        vals = [(r.get(c) or "").strip() for r in rows]
        vals = [v for v in vals if v != ""]
        n_valid = len(vals)
        n_num = sum(1 for v in vals if _is_float(v))
        if n_valid and n_num / n_valid >= 0.8:
            numeric.append(c)
            columns.append({"name": c, "kind": "numeric", "n_valid": n_valid})
        else:
            levels = sorted(set(vals))
            categorical.append(c)
            columns.append({"name": c, "kind": "categorical", "n_valid": n_valid,
                            "n_levels": len(levels), "levels": levels[:12]})
    return {"n": len(rows), "columns": columns,
            "numeric": numeric, "categorical": categorical}


def recommend_analysis(profile: dict) -> dict:
    """据数据结构确定性推荐分析(选检验,不算)。返回 {analysis, rationale, ...角色列}。"""
    numeric = profile["numeric"]
    cats = [c for c in profile["columns"] if c["kind"] == "categorical"]
    two = [c for c in cats if c["n_levels"] == 2]
    multi = [c for c in cats if 3 <= c["n_levels"] <= 12]

    dv = _pick_dv(numeric) if numeric else None    # feat-100:结局语义优先,不拿基线当 DV
    if two and numeric:
        return {"analysis": "ttest", "group": two[0]["name"], "dv": dv,
                "rationale": f"二分类 {two[0]['name']} + 连续因变量 {dv} → 独立样本 t 检验"}
    if multi and numeric:
        return {"analysis": "anova", "group": multi[0]["name"], "dv": dv,
                "rationale": f"{multi[0]['n_levels']} 组的分类 {multi[0]['name']} + "
                             f"连续因变量 {dv} → 单因素 ANOVA"}
    if len(numeric) >= 3:
        ivs = [c for c in numeric if c != dv]
        return {"analysis": "regression", "dv": dv, "iv": ivs,
                "rationale": f"多个连续变量 → 以 {dv} 为因变量的多元回归"}
    if len(numeric) >= 2:
        return {"analysis": "correlation", "x": numeric[0], "y": numeric[1],
                "rationale": f"两个连续变量 {numeric[0]}、{numeric[1]} → Pearson 相关"}
    return {"analysis": "descriptives",
            "rationale": "无明确组别/双变量结构 → 描述统计 + 相关矩阵"}


_HEADER = '''#!/usr/bin/env python
"""可复现实证分析(委托 pingouin/scipy;由 `psyclaw analysis` 生成)。

统计计算外移:运行前装统计栈 —— pip install "psyclaw[stats]"。
推荐分析:{analysis} —— {rationale}
效应量 + 95% CI 由 pingouin 一并给出;前提诊断(正态/方差齐性)随报。
"""
import pandas as pd
import pingouin as pg

df = pd.read_csv(r"{csv}")
'''


def _clean_prelude(dv: str, group: str | None) -> str:
    """脚本内嵌行清洗段(feat-100,与 meta 的 feat-094 同口径):
    因变量 coerce 解析、剔除逐行呈报、疑似缺失码警示、微型组警示。"""
    lines = [
        f'dv_s = pd.to_numeric(df["{dv}"], errors="coerce")',
        'ok = dv_s.notna()',
        'dropped = df.loc[~ok]',
        'if len(dropped):',
        '    print(f"⚠ 剔除 {len(dropped)} 行(因变量缺失/不可解析)——稿件方法须如实报告:")',
        '    for _i in dropped.index:',
        f'        print(f"  ✂ 行 {{_i + 2}}: {dv}={{df.loc[_i, \'{dv}\']!r}}")',
        f'df = df.loc[ok].assign(**{{"{dv}": dv_s[ok]}})',
        'codes = df.loc[df["%s"].isin([99, -99, 999, -999, 9999, -9999])]' % dv,
        'if len(codes):',
        '    print(f"⚠ 因变量存在疑似缺失码取值(99/-999 等)共 {len(codes)} 行——'
        '请核对编码表,勿当真实分数混入")',
    ]
    if group:
        lines += [
            f'sizes = df.groupby("{group}")["{dv}"].size()',
            'print("组样本量:", dict(sizes))',
            'if (sizes < 5).any():',
            '    print("⚠ 存在 n<5 的微型组,组间比较对其极不稳定——考虑合并/剔除并如实报告")',
        ]
    return "\n".join(lines) + "\n"


def generate_analysis_script(csv_path: str, rec: dict) -> str:
    """据推荐分析生成委托 pingouin 的可复现脚本(本函数不算任何统计)。"""
    head = _HEADER.format(csv=csv_path, analysis=rec["analysis"],
                          rationale=rec["rationale"])
    a = rec["analysis"]
    if a == "ttest":
        g, dv = rec["group"], rec["dv"]
        body = _clean_prelude(dv, g) + f'''g, dv = "{g}", "{dv}"
levels = list(pd.Series(df[g]).dropna().unique())[:2]
a = df[df[g] == levels[0]][dv].dropna()
b = df[df[g] == levels[1]][dv].dropna()
print("正态性:"); print(pg.normality(df, dv=dv, group=g))
print("\\n方差齐性:"); print(pg.homoscedasticity(df, dv=dv, group=g))
print(f"\\n独立样本 t 检验({{levels[0]}} vs {{levels[1]}}):")
print(pg.ttest(a, b))   # T / dof / p_val / CI95 / cohen_d
'''
    elif a == "anova":
        g, dv = rec["group"], rec["dv"]
        body = _clean_prelude(dv, g) + f'''g, dv = "{g}", "{dv}"
print("正态性:"); print(pg.normality(df, dv=dv, group=g))
print("\\n方差齐性:"); print(pg.homoscedasticity(df, dv=dv, group=g))
print("\\n单因素 ANOVA:")
print(pg.anova(data=df, dv=dv, between=g, detailed=True))   # F / p_unc / np2
print("\\n事后(Tukey HSD):")
print(pg.pairwise_tukey(data=df, dv=dv, between=g))
'''
    elif a == "regression":
        dv, iv = rec["dv"], rec["iv"]
        ivs = ", ".join(f'"{c}"' for c in iv)
        body = _clean_prelude(dv, None) + f'''dv, iv = "{dv}", [{ivs}]
sub = df[[dv] + iv].apply(pd.to_numeric, errors="coerce").dropna()
if len(sub) < len(df):
    print(f"⚠ 回归剔除 {{len(df) - len(sub)}} 行(自变量缺失/不可解析)——须如实报告")
print("多元 OLS 回归:")
print(pg.linear_regression(sub[iv], sub[dv]))   # coef / se / T / pval / r2 / CI
'''
    elif a == "correlation":
        x, y = rec["x"], rec["y"]
        body = f'''sub = df[["{x}", "{y}"]].apply(pd.to_numeric, errors="coerce").dropna()
if len(sub) < len(df):
    print(f"⚠ 剔除 {{len(df) - len(sub)}} 行(缺失/不可解析)——须如实报告")
print("Pearson 相关:")
print(pg.corr(sub["{x}"], sub["{y}"]))   # r / CI95 / p_val
'''
    else:  # descriptives
        body = '''num = df.select_dtypes("number")
print("描述统计:"); print(num.describe().T)
print("\\n相关矩阵:"); print(num.rcorr(method="pearson"))
'''
    return head + "\n" + body


# ---------------------------------------------------------------------------
# Step(薄壳)
# ---------------------------------------------------------------------------


def step_inspect_data(ctx) -> dict:
    """画像数据(列类型/水平),供设计与分析推荐用。fail-closed。"""
    from psyclaw import ui
    csv_path = ctx.data.get("data_csv")
    if not csv_path:
        raise ValueError("未提供数据 CSV:用 `psyclaw analysis <data.csv>`。")
    prof = profile_data(csv_path)
    ctx.data["profile"] = prof
    ctx.artifacts["inspect_data"] = csv_path
    print(ui.dim(f"  {prof['n']} 行 · 数值列 {len(prof['numeric'])} · "
                 f"分类列 {len(prof['categorical'])}"))
    flags = data_quality_flags(csv_path, prof)     # feat-100:画像即体检,不静默
    ctx.data["quality_flags"] = flags
    for fl in flags:
        print(ui.warn(f"  ⚠ {fl['detail']}"))
    if flags:
        print(ui.dim("    (数据质量警示须在稿件方法部分如实处理与报告)"))
    return {"n": prof["n"], "numeric": prof["numeric"],
            "categorical": prof["categorical"], "quality_flags": len(flags)}


def step_design(ctx) -> dict:
    """生成研究/分析设计备忘(假设·变量角色·设计类型·分析计划)。复用 loop._gen。"""
    from psyclaw import ui
    from psyclaw.loop import _gen
    prof = ctx.data.get("profile", {})
    cols = ", ".join(f"{c['name']}({c['kind']})" for c in prof.get("columns", []))
    task = ("据研究主题、研究准备清单与数据列,写一份简洁的研究/分析设计备忘:"
            "①研究假设(确证/探索区分)②变量角色(自变量/因变量/协变量)"
            "③设计类型(被试间/内/相关等)④分析计划(拟用的检验与理由,效应量+CI 必报)。"
            "只依据给定信息,不杜撰数据或结果。")
    memo = _gen(ctx.provider, "planner", task,
                f"# 主题\n{ctx.topic}\n\n# 数据列\n{cols}\n\n# 研究准备清单\n{ctx.clar}")
    (ctx.project / "notes" / "design.md").write_text(memo or "(设计备忘待补)",
                                                     encoding="utf-8")
    ctx.artifacts["design"] = "notes/design.md"
    print(ui.dim("  研究/分析设计备忘 → notes/design.md"))
    return {}


def step_analysis(ctx) -> dict:
    """据数据结构推荐分析并生成可复现脚本 → outputs/analysis.py(统计外移)。"""
    from psyclaw import ui
    prof = ctx.data["profile"]
    rec = recommend_analysis(prof)
    ctx.data["analysis_rec"] = rec
    script = generate_analysis_script(ctx.data["data_csv"], rec)
    out = ctx.project / "outputs" / "analysis.py"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(script, encoding="utf-8")
    ctx.artifacts["analysis"] = "outputs/analysis.py"
    try:                                   # 生成脚本随手打复现溯源包(否则 check 恒 ✗)
        from psyclaw.provenance import write_provenance
        write_provenance(str(out), project_dir=str(ctx.project),
                         data_path=ctx.data.get("data_csv"))
    except Exception:  # noqa: BLE001  # 溯源失败不阻断流程,check 会如实报缺
        pass
    print(ui.dim(f"  推荐分析:{rec['analysis']} —— {rec['rationale']}"))
    print(ui.dim("  可复现分析脚本 → outputs/analysis.py"
                 "(在装了 [stats] 的环境跑:python outputs/analysis.py)"))
    # v0.10 feat-053:best-effort 经 pystat MCP 直接出结果(闭环);失败仍有脚本兜底
    ran = False
    try:
        from psyclaw.workflows.pystat_bridge import run_via_pystat
        result = run_via_pystat(rec, ctx.data["data_csv"])
        if result:
            res_path = ctx.project / "outputs" / "analysis_result.txt"
            res_path.write_text(result, encoding="utf-8")
            ctx.artifacts["analysis_result"] = "outputs/analysis_result.txt"
            ctx.data["analysis_result"] = result
            ran = True
            print(ui.ok("  ✓ 已经 pystat MCP 运行 → outputs/analysis_result.txt"))
    except Exception:  # noqa: BLE001 — pystat 直跑是增强,失败不阻断
        pass
    return {"analysis": rec["analysis"], "ran_via_pystat": ran}


def step_write_analysis(ctx) -> dict:
    """据设计 + 分析计划写实证稿骨架(APA-JARS)。复用 writing_backend.write_paper。"""
    from psyclaw import ui
    from psyclaw.output.writing_backend import write_paper
    rec = ctx.data.get("analysis_rec", {})
    design = (ctx.project / "notes" / "design.md")
    design_txt = design.read_text(encoding="utf-8") if design.exists() else ""
    context = (
        f"# 研究设计\n{design_txt}\n\n"
        f"# 分析计划\n推荐分析:{rec.get('analysis')} —— {rec.get('rationale')}。"
        "统计由 outputs/analysis.py 在外部 pingouin/scipy 环境运行,"
        "结果回填本稿(只引用脚本实际产出,不杜撰数值;效应量+CI 必报)。\n\n"
        f"# 研究准备清单\n{ctx.clar}")
    q = ctx.data.get("quality_flags") or []
    if q:                                  # feat-100:数据质量警示进稿件上下文,如实报告
        context += ("\n\n# 数据质量警示(方法/结果部分**必须如实处理并报告**,不得静默)\n"
                    + "\n".join(f"- {fl['detail']}" for fl in q))
    # v0.12 feat-072:pystat 真跑出的结果注入写作上下文——结果节引用真实数值,不再是空骨架
    result = ctx.data.get("analysis_result")
    if result:
        context += ("\n\n# 实际分析结果(pystat MCP 已运行;结果节**只引用以下真实数值**,"
                    "效应量+95% CI 必报,不杜撰、不外推)\n" + str(result)[:4000])
    draft, _meta = write_paper(ctx.topic, context, ctx.provider, ctx.project)
    if not draft.strip():
        raise ValueError("写作阶段未产出稿(provider 返回空)")
    ctx.artifacts["write"] = "outputs/report.md"
    ctx.data["draft_path"] = str(ctx.project / "outputs" / "report.md")
    print(ui.dim("  实证稿骨架 → outputs/report.md"))
    return {}
