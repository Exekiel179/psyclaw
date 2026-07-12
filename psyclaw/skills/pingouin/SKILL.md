---
name: pingouin
description: Pingouin 心理学统计函数选择指南。当需要做 t 检验、方差分析(单因素/重复测量/混合/ANCOVA)、相关(含偏相关/稳健)、中介分析、信度、功效分析、贝叶斯因子时,用此指南选对函数并按 PSYCLAW 规范报告。Pingouin 一次给出统计量+效应量+CI+功效+BF。
category: tooling
metadata:
  backend: psyclaw.psych.pingouin_backend
  requires: [pingouin, pandas, scipy, statsmodels]
  enforces_gates: [STAT.effect_size, STAT.assumptions, MEASURE.reliability]
---

# Pingouin — 心理学统计"一次出全"

Pingouin(Vallat 2018, JOSS)相比 scipy 的核心优势:`pg.ttest` 一个调用同时返回
**T、df、p、Cohen's d、95% CI、统计功效、贝叶斯因子 BF₁₀**——正好满足 PSYCLAW
"效应量+CI 必报"质量检查。PsyClaw 默认依赖它,`psyclaw stat` 自动优先用。

## 函数选择速查(研究问题 → pingouin 函数)

| 研究问题 | 函数 | 关键输出 | psyclaw 命令 |
|----------|------|----------|--------------|
| 两组均值差(被试间) | `pg.ttest(x, y)` | d + CI + 功效 + BF | `stat --dv y --group g` |
| 配对/前后测 | `pg.ttest(x, y, paired=True)` | dz + CI | `stat --dv post --paired pre` |
| 单因素被试间 | `pg.anova` / `pg.welch_anova` | η² | `stat --dv y --group g` |
| **重复测量** | `pg.rm_anova(correction=True)` | ε + GG 校正 + 球形性 | `stat --rm --within t --subject id` |
| **混合设计** | `pg.mixed_anova` | 交互 F + η² | `stat --mixed --within t --group g --subject id` |
| **协方差** | `pg.ancova` | 控制协变量 + η² | `stat --ancova --group g --covar c` |
| 相关(线性) | `pg.corr(method='pearson')` | r + CI + BF | `stat --dv x --with y` |
| 相关(稳健/离群) | `pg.corr(method='bicor')` | 抗离群 r | — |
| 偏相关 | `pg.partial_corr` | 控制第三变量 | — |
| **中介** | `pg.mediation_analysis(n_boot=5000)` | bootstrap 间接效应 CI | `stat --mediation --x X --m M --y Y` |
| 多重比较 | `pg.pairwise_tests(padjust='fdr_bh')` | FDR 校正 + Hedges g | — |
| 信度 | `pg.cronbach_alpha` | α + CI | `stat --reliability --items a,b,c` |
| 功效/样本量 | `pg.power_ttest` | 所需 N 或达成功效 | `stat --power --d 0.4 --power 0.8` |
| 正态性 | `pg.normality` | Shapiro W | (check 命令已内置) |
| 球形性 | `pg.sphericity` | Mauchly W | (rm_anova 自动) |
| 卡方+效应量 | `pg.chi2_independence` | Cramér's V + 功效 | — |

## 报告纪律(PSYCLAW 质量检查)

- **效应量必报**:pingouin 自带,直接进 APA7 句子(d/η²/r/Cramér's V + CI)
- **Welch 默认**:两组比较 `pg.ttest` 默认 correction='auto';ANOVA 不齐用 `welch_anova`
- **重复测量必报 ε 与校正**:`rm_anova(correction=True)`,ε<.75 用 GG
- **中介禁 Sobel**:用 `mediation_analysis` 的 bootstrap CI(默认 ≥5000 次,seed 固定)
- **横断中介声明局限**:不证因果(Maxwell & Cole 2007)
- **信度**:α 仅 tau 等价下准确,加报 ω(McNeish 2018)

## 回落

pingouin 缺失时,PsyClaw 自动回落纯 stdlib 实现(stats_core,已对照 scipy 校验),
但失去功效/BF/重复测量/中介等高级能力。建议 `psyclaw setup` 装齐核心 stats 组。
