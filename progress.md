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

1. feat-012 会话持久化 session store(SQLite+FTS5)
2. 文档去债收尾:DESIGN.md / TODO.md / README.md 仍大量描述已删的统计命令,待重写

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
