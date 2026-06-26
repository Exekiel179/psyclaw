# PsyClaw Session Progress Log

## Current State

**Last Updated:** 2026-06-26
**重大转向:** PsyClaw 从「全流程统计 CLI」重定位为「纯研究编排 harness」——
统计计算整体外移到成熟库/MCP,本仓删除全部手写统计实现。

> 状态真源:`feature_list.json`(机器可读)。本文件是人读的「接续上下文」快照。

## What's Done

- [x] feat-001 **统计层整体外移**:git rm 42 个统计模块 + 41 个测试;cli/loop/pipeline/repl/scales/preregister 去统计纠缠;psyclaw/ 零统计库依赖
- [x] feat-002 研究编排流水线 research(澄清→文献→设计→写作→评审→总验收;--freeform 走通用回路)
- [x] feat-003 审稿模拟 review panel
- [x] feat-004 研究澄清 clarify(LLM 驱动追问)
- [x] feat-005 预注册 preregister + 分析声明 declare-test
- [x] feat-006 知识参考目录(scale/norms/assume/method/design/cite/ethics)+ 量表计分 score
- [x] feat-007 文献检索 lit + 写作输出 export(APA7/心理学报/JARS)
- [x] feat-008 三层自进化记忆
- [x] feat-009 学术规范门禁 gates
- [x] feat-010 REPL + 路径注入 + 渐进式披露
- [x] feat-011 harness 工程化契约

## What's Next

1. 后续增强:各分析步从"生成脚本"升级为可选直连 MCP 统计后端;质性编码升级为专用 skill
2. 文档去债收尾:DESIGN.md / TODO.md / README.md 仍大量描述已删的统计命令,待重写
3. feat-013 会话持久化 session store(SQLite+FTS5)

## 本轮(5):qualitative 质性研究流程 — 四条研究流程齐

- `qualitative <转录稿>`:clarify门禁→载入转录稿→质性设计→主题分析(LLM 辅助)→写 COREQ 报告→评审
- 质性是解释性分析(非统计):L3 实现 = LLM 辅助开放编码+主题分析,**研究者须复核**(HITL);
  产物明确标注"LLM 辅助,逐条复核引文与主题归属"
- 新子功能 `load_transcripts`(单文件/目录,过滤非 .txt/.md,fail-closed);生成式 `step_qual_design`/`step_thematic_analysis`/`step_write_qual`
- 验证:`tests/test_workflows.py` 35 例;全量 **949 passed**
- **四条研究流程齐(feat-012 done)**:review-lit / meta / analysis / qualitative,每类一条顶层命令

## 本轮(4):analysis 实证分析流程(第三条流程,统计外移到 pingouin/scipy)

- `analysis <data.csv>`:clarify门禁→画像数据→研究/分析设计→**推荐分析+生成可复现脚本**→写→评审
- 统计外移:`generate_analysis_script` 据数据画像推荐分析(t检验/ANOVA/相关/回归/描述统计)
  并生成委托 pingouin/scipy 的脚本(outputs/analysis.py,含效应量+CI+前提诊断),仓内不算
- 新子功能(独立纯函数):`profile_data`(逐列判数值/分类+水平)、`recommend_analysis`
  (确定性选检验)、`generate_analysis_script`;生成式 `step_design`(LLM 写设计备忘)
- 验证:t检验/ANOVA/相关三种推荐的生成脚本均经 C:\Python314 实跑 exit 0;
  `tests/test_workflows.py` 28 例;全量 **942 passed**
- 三条研究流程齐:review-lit / meta / analysis(命名按用户要求 empirical→analysis)

## 本轮(3):meta 元分析流程(验证"统计外移"端到端)

- `meta <effects.csv>`:clarify门禁→载入校验效应量表→**生成可复现元分析脚本**→写→评审
- 统计外移落地:`generate_meta_script` 产出委托 statsmodels 的脚本(随机效应 DL + I²/τ²/Q + Egger),
  仓内**不算任何统计**;脚本由用户在 [stats] 环境跑或交 MCP
- 新子功能:`validate_effects`(效应量表校验,自动识别 effect 列 + variance/se/ci 方差来源)、
  `generate_meta_script`——均独立纯函数可单用
- 引擎加 `seed` 参数(把 effects_csv 喂进 ctx.data);`step_review` 泛化用 ctx.data['draft_path']
- 验证:生成脚本经 C:\Python314 实跑 → 合并效应 0.347 / I² 27% / Egger p=.008 / exit 0;
  `tests/test_workflows.py` 20 例;全量 **934 passed**

## 本轮(2):Workflow 层 — 按研究类型路由的可组合流程引擎

愿景:不同研究需求走不同流程(文献综述/实证/元分析/质性…),上层分类简单,
每个子功能可单用/可拆/可拼成 loop;harness 约束 + skill/MCP 实现 + memory 横切。

- 架构:四层(L0 路由→L1 流程→L2 子功能→L3 skill/MCP)+ 两横切(harness/memory),见 `docs/ARCHITECTURE.md`
- 引擎 `psyclaw/workflows/engine.py`:声明式 Step 列表 + gate(fail-closed)+ HITL + 机器可读总验收
- 首条流程 **文献综述**(`review-lit <主题>`):clarify→检索→PRISMA筛选→合成综述→评审;复用 litsearch/synthesize/review
- 新子功能 `screen_papers`(PRISMA 相关性初筛,独立纯函数,可单用;跨语言诚实降级)
- L0 路由形态:**每类研究一条顶层命令**(review-lit 已落地,empirical/meta/qualitative 待续)
- 验证:`tests/test_workflows.py` 12 例;全量 **926 passed**

## 本轮(2026-06-26):统计层整体外移

**删除**(git rm,共 83 文件):
- 42 个统计模块:analyze/anova/anova2/ancova/rm_anova/mixed_anova/chisquare/nonparametric/
  paired_categorical/regression/hierarchical_regression/logistic/poisson/negbin/ordinal/
  multinomial/mlm/efa/cfa/invariance/survival/irr/roc/meta/decision_tree/equivalence/bayes/
  partial_corr/compare_corr/descriptives/diagnostics/careless/missing_data/sensitivity/
  effect_size/multiple_testing/power/reliability/stats_core/pingouin_backend/r_backend/ttest
- 41 个对应测试 test_*.py

**保留 harness**(psych/ 12 模块):clarify, knowledge, scales, ethics, institution,
lit_cli, litsearch, synthesize, zotero_client, analysis_plan, preregister, __init__

**纠缠修复**:
- `cli.py` 2166→~790 行:删 ~41 统计命令注册 + 处理器;CORE_COMMANDS/COMMAND_CATEGORIES 重写
- `loop.py`:删 `_auto_analyze`/`_find_csv`/`_guess_vars`(executor 不再自动跑统计)
- `pipeline.py`:删③统计阶段 + 统计门禁;PHASES 去 stat;流程变 文献→设计→写作→评审→总验收
- `repl.py`:删 /check //screen //sensitivity 斜杠命令
- `scales.py`:删 `compute_subscale_reliability`(信度外移)
- `preregister.py`:删 power.compute 嵌入(样本量依据走澄清卡 power 槽位)
- `pyproject.toml`:8 个统计库从硬依赖降为可选 `[stats]` extra

**保留命令**(33):repl/version/doctor/config/setup/skills/mcp/gates/commands ·
scale/norms/assume/method/design/cite/ethics · score · clarify/declare-test/preregister/jars ·
goal/plan/tasks/research/review · memory/serve/notify/lit/auth/export/figures

**验证**:`C:\Python314\python -m pytest -q` → **944 passed**(原 3165,删 ~2200 统计测试);
`psyclaw --help`/`commands`/`gates` 实跑正常;整包 compileall 通过;psyclaw/ 零统计库 import。

## Blockers / Risks

- [ ] 文档去债:DESIGN.md / TODO.md / README.md 仍描述已删统计命令,需重写(本轮只更新了 CLAUDE.md / feature_list.json / docs/COMMANDS.md / 审计文档)
- [ ] gates 仍含统计类门禁(STAT.meta/equivalence、MEASURE.invariance 等)——统计外移后这些门禁无内置产出可校验,但作为规范规则保留(门禁只增不删)

## Notes for Next Session

本地测试解释器:`C:\Python314\python`。PsyClaw 现为纯研究编排 harness,
**不要再往 psyclaw 里加任何统计计算**——统计交给外部成熟库/MCP(见 CLAUDE.md 铁律)。
