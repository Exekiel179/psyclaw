"""元分析流程的 Step 与子功能。

设计纪律(统计外移):元分析的"分析"**不在仓内算**——`generate_meta_script` 生成一份
委托 statsmodels 的**可复现脚本**(outputs/meta_analysis.py),由用户在装了 [stats] 的
环境跑(或交 MCP 统计后端)。PsyClaw 只做:校验效应量表 → 生成脚本 → 写作 → 评审。

`validate_effects` / `generate_meta_script` 都是独立纯函数(可单测、可被任意流程/命令直接调用)。
"""

from __future__ import annotations

import csv
from pathlib import Path

# 列名候选(小写匹配)——效应量 / 方差 / 标准误 / CI 上下界 / 研究标签
_EFFECT = ("yi", "effect", "effect_size", "effectsize", "es", "smd", "d",
           "cohen_d", "cohens_d", "hedges_g", "hedges", "g", "r", "z",
           "lnor", "logor", "log_or", "beta")
_VAR = ("vi", "var", "variance", "v")
_SE = ("se", "sei", "std", "stderr", "standard_error", "se_effect", "se_d", "se_g")
_CILOW = ("ci_low", "ci_lower", "cilow", "lower", "lci", "ll", "ci_l")
_CIHIGH = ("ci_high", "ci_upper", "cihigh", "upper", "uci", "ul", "ci_u")
_STUDY = ("study", "author", "authors", "label", "name", "id", "citation")


def _pick(cols_lower: dict, candidates) -> str | None:
    """在列名(小写→原名 映射)里挑第一个命中候选的列;先精确后子串。"""
    for c in candidates:
        if c in cols_lower:
            return cols_lower[c]
    for cand in candidates:
        for low, orig in cols_lower.items():
            if cand in low:
                return orig
    return None


def validate_effects(csv_path: str) -> dict:
    """校验效应量 CSV,定位效应量列 + 方差来源(variance/se/ci),返回元信息。

    返回 {n_studies, study_col, effect_col, variance_kind, variance_cols, columns}。
    致命问题(找不到效应量列 / 有效研究 < 2 / 无方差来源)抛 ValueError(fail-closed)。
    """
    p = Path(csv_path)
    if not p.exists():
        raise ValueError(f"效应量文件不存在:{csv_path}")
    with p.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError("效应量 CSV 为空")

    cols = list(rows[0].keys())
    cols_lower = {c.lower().strip(): c for c in cols}

    effect_col = _pick(cols_lower, _EFFECT)
    if not effect_col:
        raise ValueError(
            f"找不到效应量列(期望 yi/effect/d/g/r/smd…);现有列:{cols}")

    var_col = _pick(cols_lower, _VAR)
    se_col = _pick(cols_lower, _SE)
    ci_low = _pick(cols_lower, _CILOW)
    ci_high = _pick(cols_lower, _CIHIGH)
    if var_col:
        kind, vcols = "variance", [var_col]
    elif se_col:
        kind, vcols = "se", [se_col]
    elif ci_low and ci_high:
        kind, vcols = "ci", [ci_low, ci_high]
    else:
        raise ValueError(
            "找不到方差来源(需 variance/vi,或 se,或 ci_lower+ci_upper 之一)")

    # 数有效研究(效应量 + 方差来源都可解析为数)
    n_valid = 0
    for r in rows:
        try:
            float(r[effect_col])
            if kind == "ci":
                float(r[vcols[0]]); float(r[vcols[1]])
            else:
                float(r[vcols[0]])
            n_valid += 1
        except (ValueError, TypeError, KeyError):
            continue
    if n_valid < 2:
        raise ValueError(f"有效研究数 < 2(仅 {n_valid});元分析至少需 2 项研究")

    study_col = _pick(cols_lower, _STUDY)
    return {
        "n_studies": n_valid,
        "study_col": study_col,
        "effect_col": effect_col,
        "variance_kind": kind,
        "variance_cols": vcols,
        "columns": cols,
    }


def generate_meta_script(csv_path: str, info: dict) -> str:
    """生成委托 statsmodels 的可复现随机效应元分析脚本(DerSimonian-Laird + I²/τ²/Q + Egger)。

    统计在外部库跑——本函数只产代码字符串,不计算任何统计量。
    """
    kind = info["variance_kind"]
    vcols = info["variance_cols"]
    if kind == "variance":
        vi_expr = f'vi = df["{vcols[0]}"].astype(float).to_numpy()'
    elif kind == "se":
        vi_expr = f'vi = df["{vcols[0]}"].astype(float).to_numpy() ** 2'
    else:  # ci → vi = ((upper-lower)/(2*1.96))**2
        vi_expr = (f'se = (df["{vcols[1]}"].astype(float) - df["{vcols[0]}"].astype(float)) '
                   f'/ (2 * 1.959963985)\n    vi = (se.astype(float).to_numpy()) ** 2')
    label_expr = (f'labels = df["{info["study_col"]}"].astype(str).tolist()'
                  if info.get("study_col")
                  else 'labels = [f"study{i+1}" for i in range(len(df))]')

    return f'''#!/usr/bin/env python
"""可复现随机效应元分析(委托 statsmodels;由 `psyclaw meta` 生成)。

统计计算外移:运行前装统计栈 —— pip install "psyclaw[stats]"(或 statsmodels pandas numpy)。
方法:DerSimonian-Laird 随机效应 + I²/τ²/Q 异质性 + Egger 回归(发表偏倚)。
"""
import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.meta_analysis import combine_effects

df = pd.read_csv(r"{csv_path}")
yi = df["{info['effect_col']}"].astype(float).to_numpy()
{vi_expr}
{label_expr}

res = combine_effects(yi, vi, method_re="dl", row_names=labels, use_t=False)
print(res.summary_frame())

i2 = max(0.0, res.i2)
print("\\n随机效应(DerSimonian-Laird):")
print(f"  合并效应 = {{res.mean_effect_re:.4f}}")
print(f"  tau^2 = {{res.tau2:.4f}}   I^2 = {{i2*100:.1f}}%   Q = {{res.q:.2f}}   k = {{res.k}}")

# Egger 回归(发表偏倚):标准正态离差 ~ 精度;截距显著 → 漏斗图不对称
se = np.sqrt(vi)
snd = yi / se
X = sm.add_constant(1.0 / se)
egger = sm.OLS(snd, X).fit()
print(f"\\nEgger 检验:截距 = {{egger.params[0]:.3f}}, p = {{egger.pvalues[0]:.3f}}"
      f"  ({{'提示不对称/可能发表偏倚' if egger.pvalues[0] < 0.05 else '未见显著不对称'}})")

# 森林图(可选)
try:
    fig = res.plot_forest()
    fig.savefig("forest.png", dpi=150, bbox_inches="tight")
    print("\\n森林图 → forest.png")
except Exception as exc:  # noqa: BLE001
    print(f"\\n(森林图跳过:{{exc}})")
'''


# ---------------------------------------------------------------------------
# Step(薄壳)
# ---------------------------------------------------------------------------


def step_load_effects(ctx) -> dict:
    """载入并校验效应量 CSV(fail-closed:无文件/列缺失/研究<2 抛错)。"""
    from psyclaw import ui
    csv_path = ctx.data.get("effects_csv")
    if not csv_path:
        raise ValueError("未提供效应量 CSV:用 `psyclaw meta <effects.csv>`。")
    info = validate_effects(csv_path)
    ctx.data["effects_info"] = info
    ctx.artifacts["load_effects"] = csv_path
    print(ui.dim(f"  {info['n_studies']} 项研究 · 效应量列 {info['effect_col']} · "
                 f"方差来源 {info['variance_kind']}"))
    return {"n_studies": info["n_studies"], "effect_col": info["effect_col"]}


def step_meta_script(ctx) -> dict:
    """生成委托 statsmodels 的可复现元分析脚本 → outputs/meta_analysis.py(统计外移)。"""
    from psyclaw import ui
    info = ctx.data["effects_info"]
    script = generate_meta_script(ctx.data["effects_csv"], info)
    out = ctx.project / "outputs" / "meta_analysis.py"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(script, encoding="utf-8")
    ctx.artifacts["meta_script"] = "outputs/meta_analysis.py"
    print(ui.dim("  可复现元分析脚本 → outputs/meta_analysis.py"
                 "(在装了 [stats] 的环境跑:python outputs/meta_analysis.py)"))
    return {"script": "outputs/meta_analysis.py"}


def step_write_meta(ctx) -> dict:
    """据效应量摘要 + 分析计划写元分析稿骨架。复用 writing_backend.write_paper。"""
    from psyclaw import ui
    from psyclaw.output.writing_backend import write_paper
    info = ctx.data["effects_info"]
    context = (
        f"# 元分析对象\n效应量表:{ctx.data['effects_csv']}\n"
        f"研究数 k = {info['n_studies']};效应量列 = {info['effect_col']};"
        f"方差来源 = {info['variance_kind']}。\n\n"
        "# 分析计划\n随机效应模型(DerSimonian-Laird),报告合并效应+95% CI、"
        "I²/τ²/Q 异质性、Egger 发表偏倚检验。统计由 outputs/meta_analysis.py "
        "在外部 statsmodels 环境运行,结果回填本稿(只引用脚本实际产出,不杜撰数值)。\n"
        f"\n# 澄清卡\n{ctx.clar}")
    draft, _meta = write_paper(ctx.topic, context, ctx.provider, ctx.project)
    if not draft.strip():
        raise ValueError("写作阶段未产出稿(provider 返回空)")
    ctx.artifacts["write"] = "outputs/report.md"
    ctx.data["draft_path"] = str(ctx.project / "outputs" / "report.md")
    print(ui.dim("  元分析稿骨架 → outputs/report.md"))
    return {}
