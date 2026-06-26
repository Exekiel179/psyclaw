# 成熟库迁移审计（"现有库能实现的就别手写"全代码复查）

> 日期：2026-06-26。方法：6 个并行审计 agent 逐模块读真实计算代码，按"核心算法是手写还是委托库"判定。
> 铁律依据：CLAUDE.md「成熟库优先，禁止手写已被 scipy/pingouin/statsmodels/lifelines/factor_analyzer/semopy 覆盖的统计算法」。
> 本文件是迁移真源；每迁完一个模块在此打勾并记 evidence。

## 三个最扎眼的发现

1. **付费却不用**：`factor_analyzer`、`semopy`、`lifelines` 在 `pyproject.toml` 是硬依赖，但**全仓零 import**——`efa.py`/`cfa.py`/`survival.py` 整条手写它们覆盖的算法。最该还的债。
2. **GLM 四件套已合规**：`regression`/`hierarchical_regression`/`logistic`/`poisson` 已真正 `sm.OLS/Logit/GLM().fit()`，是正面样板（但 logistic/poisson 的 docstring 仍谎称"手写 IRLS"，文档债）。
3. **手写核普遍只借 scipy 当"分布函数表"**：大量模块 import scipy 仅用于取 `.sf/.ppf` 尾概率，统计量/估计器全手写——这仍是债。

## 判定汇总

- **该迁（核心手写 + 库已覆盖）**：anova, anova2, ancova, rm_anova, mixed_anova, negbin, ordinal, multinomial, mlm, efa, cfa, survival, bayes, equivalence, multiple_testing, paired_categorical, nonparametric, diagnostics(F/Welch/Levene), reliability, partial_corr(偏相关), irr(ICC+κ), decision_tree(中介), descriptives(相关矩阵), chisquare(χ²), power(主体), meta(Egger OLS), stats_core(MWU/χ²残留), careless(求逆/临界值)
- **保留（库无覆盖 / 合理胶水 / 已委托）**：regression, hierarchical_regression, logistic, poisson, pingouin_backend, compare_corr, effect_size, invariance, missing_data(Little MCAR 主框架), 以及各模块的 APA-7/报告/CLI 胶水、半偏相关、Krippendorff α、Johnson-Neyman、power_sem_rmsea/power_mediation_mc

---

## Tier 1 — 净胜（明确债 + 低风险 + 测试不深度耦合）。建议先做

| 模块 | 手写核(行号) | 换成 | 风险 | done |
|---|---|---|---|---|
| `multiple_testing.py` | bonferroni/holm/BH 排序校正(37-197) | `statsmodels.stats.multitest.multipletests` | 低（已实测口径一致；保留 dict/APA 胶水） | [x] 委托 multipletests，reject 按原口径自算；全量 3165 绿 |
| `diagnostics.py` | levene_bf(122-126)/oneway_f(92-99)/welch_f(102-119) | `scipy.stats.levene(center='median')` / `f_oneway` / `pingouin.welch_anova` | 低-中（签名保留则测试可过；levene 一行替换最干净） | [ ] |
| `chisquare.py` | GoF/独立性 χ²+期望频数(76,135-148) | `scipy.stats.chisquare` / `chi2_contingency`（Fisher 已委托✅） | 低（测试不钉内部 helper） | [ ] |
| `careless.py` | `_mat_inv` Gauss-Jordan(98-116) / `chi2_critical` Wilson-Hilferty(164-172) | `numpy.linalg.inv` + `scipy.spatial.distance.mahalanobis` / `scipy.stats.chi2.ppf` | 低（测试仅序关系/区间断言）。longstring/IRV/psychsyn 保留 | [ ] |
| `survival.py` | KM+Greenwood+log-log CI + logrank χ² + 手写求逆(57-276) | `lifelines.KaplanMeierFitter` + `lifelines.statistics.multivariate_logrank_test` | 低（lifelines 硬依赖却零 import；默认口径一致） | [ ] |
| `anova.py` | SS/F/eta²/omega²(57-87) | `pingouin.anova` + `pg.pairwise_tests`（`pingouin_backend` 已封装） | 低（无内部 helper 被钉死） | [ ] |
| `reliability.py` | cronbach_alpha(18-29) | `pingouin.cronbach_alpha`（`pingouin_backend.reliability` 已在用→此文件冗余） | 低（α 同公式数值一致）。alpha_if_deleted 保留 | [ ] |
| `meta.py` | `_ols_simple` Egger 手写 OLS(50-68) | `statsmodels.api.OLS`（DL 主体可暂留） | 低（仅 Egger 一处） | [ ] |
| `decision_tree.py` | `bootstrap_mediation` 手写 OLS+5000 重抽(202-241) | 复用 `pingouin_backend.mediation()`（已委托 `pg.mediation_analysis`） | 中（与 backend 重复造轮子）。JN/调节保留 | [ ] |
| `stats_core.py` | `mann_whitney`(177-201)/`chisquare_independence`(204-223) 残留 | `scipy.stats.mannwhitneyu` / `chi2_contingency`（t 族已委托✅） | 中（先查调用方） | [ ] |

## Tier 2 — 中风险（数值会变，金标准测试需重算）

| 模块 | 手写核 | 换成 | 关键风险 | done |
|---|---|---|---|---|
| `equivalence.py` | 三套 TOST + 手写 Welch df | `pingouin.tost` | 等价区间单位 d vs 原始差，须对齐否则结论变 | [ ] |
| `bayes.py` | JZS 被积函数 + 手写中点积分 | `pingouin.bayesfactor_ttest` / `bayesfactor_pearson` | BF 值会变（更准），测试基准重订 | [ ] |
| `partial_corr.py` | OLS 残差+Fisher-z CI(81-155)+矩阵 | `pingouin.partial_corr` / `pcorr`（半偏保留） | CI 用 Olkin-Finn n-k-3 校正，pingouin 不校正→CI 变 | [ ] |
| `descriptives.py` | 相关矩阵 r/p(202-219) | `scipy.stats.pearsonr` / `pingouin.pairwise_corr`（M/SD/skew/kurt/CI 已合规✅） | 中（多 helper 被 import） | [ ] |
| `multinomial.py` | softmax+Newton 块信息阵(98-308) | `statsmodels.api.MNLogit` | J=2 退化金标准可移植；内部 helper 测试重写 | [ ] |
| `anova2.py` | 边际均值法 SS(79-162) | `statsmodels ols+anova_lm(typ=3)` / `pg.anova` | 顺带修"伪 Type-I"非均衡 bug；数值变 | [ ] |
| `power.py` | t/ANOVA/相关/回归功效+反解 N(163-403) | `statsmodels.stats.power.*`（sem_rmsea/mediation_mc 保留） | ncp 参数化与 N 反解口径对齐；清死代码 `_chi_scaled_*` | [ ] |
| `paired_categorical.py` | McNemar/Cochran Q(106-230) | `statsmodels.stats.contingency_tables.mcnemar` / `cochrans_q` | 测试深度钉死手算金标准 | [ ] |
| `roc.py` | AUC(Mann-Whitney)/曲线/Youden(82-344) | `sklearn.metrics.roc_auc_score` / `roc_curve` | **sklearn 未列依赖，须先加**；HM-CI/PPV/NPV 保留 | [ ] |
| `irr.py` | ICC 六模型双向 ANOVA MS(578-712) + κ | `pingouin.intraclass_corr` + `statsmodels...fleiss_kappa`（Krippendorff 保留） | 测试用 textbook 数值钉 ICC/κ；CI/键名变 | [ ] |

## Tier 3 — 高风险（大块手写/自写优化器/测试深度耦合/口径变更需决策）

| 模块 | 手写核 | 换成 | 关键风险 | done |
|---|---|---|---|---|
| `efa.py` | 整条 PAF+Varimax+SMC(72-246) | `factor_analyzer.FactorAnalyzer`（+KMO/Bartlett） | 硬依赖零 import；载荷符号/数值变；test 钉死 helper；顺带补缺失的 KMO/Bartlett | [ ] |
| `cfa.py` | 整条 ULS + **自写 Adam 优化器**(203-376) + 拟合指数 | `semopy.Model.fit` + `semopy.calc_stats` | 硬依赖零 import；自写优化器收敛性/χ²标度可疑→数值显著变更可信；语法 `F1:x1,x2`→lavaan（r_backend 有先例） | [ ] |
| `ordinal.py` | 解析梯度+差分 Hessian+阻尼牛顿(103-291) | `statsmodels.miscmodels.ordinal_model.OrderedModel` | β 符号方向对齐；test 钉死 `_ll_grad`/`_observed_information` | [ ] |
| `negbin.py` | Fisher scoring+黄金分割 θ+信息阵(160-345) | `statsmodels...NegativeBinomial`(nb2) | test 钉死 `_fit_beta`/`_fit_theta`/`_eval_mu`；θ 的 SE 取法异 | [ ] |
| `ancova.py` | 手搭 GLM+Type-III SS+EMM(93-393) | `pingouin.ancova` / `statsmodels` | EMM/CI 数值变；报告取数键重写 | [ ] |
| `mixed_anova.py` | split-plot 五项 SS 分解(264-434) | `pingouin.mixed_anova`（backend 已封装） | 非均衡 Type-I；EMM 变 | [ ] |
| `rm_anova.py` | Helmert+Mauchly+GG/HF ε+SS(59-234) | `pingouin.rm_anova(correction=True)`（backend 已封装） | test 直接钉死 `_epsilon_gg`/`_epsilon_hf`/`_helmert_contrast`/`_mauchly_test`/`_cov_matrix` | [ ] |
| `nonparametric.py` | 822 行手写秩/U/H/χ²/Spearman | `scipy.stats.mannwhitneyu/wilcoxon/kruskal/friedmanchisquare/spearmanr`（Conover/Dunn→`scikit_posthocs`） | scipy 默认 ties/连续性校正→p 值变；金标准重算成本最高 | [ ] |
| `mlm.py` | 手写 EM + GLS + 边际 LL(140-295) | `statsmodels...MixedLM` | **ML→REML 口径变更=测量口径变，按 CLAUDE.md 须先写 `notes/decision_request.md`**；test 39+ 处钉死 | [ ] |

## 附带文档债（随迁移一并清）

- `logistic.py`/`poisson.py` docstring 谎称"手写 IRLS/Newton-Raphson"，实际已委托 statsmodels。
- `diagnostics.py` docstring 称"自实现连分式 Beta(Numerical Recipes)"，实际已走 `scipy.special.betainc`。
- 多处 `纯 stdlib / stdlib only` 标注：已迁 scipy 的是债，真手写的（cfa/efa/careless 等）是事实，逐个甄别。

## 迁移纪律（每个模块通用）

1. 一次一个模块（CLAUDE.md「One feature at a time」「改动外科手术化」）。
2. 委托库后，**报告/APA-7/CLI 胶水保留**，只换统计核。
3. 测试若钉死内部 helper → 改为对照公库结果断言；数值口径变化在 commit 信息写清。
4. 触及"测量口径变更"（mlm 的 ML→REML、cfa 的优化器换核致 χ² 标度变）→ 先 `notes/decision_request.md`，不自作主张。
5. 每个模块迁完跑全量测试 + 数值对照库，绿了在本文件打勾记 evidence。
