# PsyClaw Session Progress Log

## Current State

**Last Updated:** 2026-06-24
**Current Objective:** 按 learn-harness-engineering / learn-hermes-agent 两份指南，把 PsyClaw 补到成熟 harness 水准
**Active Feature:** feat-010 clarify LLM 驱动追问（CLAR-1 已 done；CLAR-2/3/4 待续）

> 状态真源：`feature_list.json`（机器可读）。本文件是人读的"接续上下文"快照。
> 计划真源仍是 `TODO.md`（81 个 ✅，统计纵深细目）。

## Status

### What's Done

- [x] feat-001 统计分析命令族（40+ 命令，APA-7 + 效应量+CI）
- [x] feat-002 成熟统计库迁移（scipy/statsmodels/...；删 ~2000 行手写实现；失败 22→0）
- [x] feat-003 学术门禁 gates（17 条，fail-closed）
- [x] feat-004 三层自进化记忆
- [x] feat-005 ARS 四象限端到端流水线（`psyclaw research`）
- [x] feat-006 审稿模拟 review panel
- [x] feat-007 REPL + 路径注入 + Markdown 渲染（含跨平台引号/~ 修复）
- [x] feat-008 harness 工程化契约（validate-harness 24→100）
- [x] feat-009 端到端集成测试（`tests/test_e2e_analysis.py`，5 例对照 scipy/statsmodels）

### What's In Progress

- [ ] feat-010 clarify LLM 驱动追问
  - Details: CLAR-1（LLM 评估+追问+fail-safe 降级）已 done；剩 CLAR-2（read_line UI/back/进度）、CLAR-3（按研究类型动态裁剪槽位）、CLAR-4（卡片追问痕迹 + preregister/research 衔接）
  - Blockers: 无

### What's Next

1. feat-010 余下 CLAR-2/3/4
2. feat-011 会话持久化 session store（SQLite+FTS5，Hermes s03）
3. feat-012 判断层评估 harness（eval suite，Hermes s23）—— 商业化"可信"护城河

## Blockers / Risks

- [ ] 文档去债：DESIGN.md / TODO.md / 部分 docstring 仍写"纯 stdlib"，迁移后已过时（`analyze.py` 第 1 行本轮已修）
- [ ] **成熟库迁移债（全代码审计，真源 `docs/LIBRARY_MIGRATION_AUDIT.md`）**：6 agent 逐模块复查确认——GLM 四件套(regression/logistic/poisson/hierarchical)已合规委托 statsmodels；但 ANOVA 五族 + negbin/ordinal/multinomial/mlm + efa/cfa/survival + multiple_testing/diagnostics/chisquare/bayes/equivalence/partial_corr/irr/nonparametric 等 ~28 模块仍手写库已覆盖的统计核。关键：factor_analyzer/semopy/lifelines 是硬依赖却零 import。分 Tier1 净胜/Tier2 中风险/Tier3 高风险(mlm 的 ML→REML 须先 decision_request)。一次迁一个，胶水保留、只换核。

## 本轮维护(2)：`research` 合并 + 渐进式披露（应"合并命令/降低观感复杂度"诉求）

- **合并**：`research-loop` 并入 `research --freeform`（同源——pipeline 本就搭在 loop 引擎上）；删 `cmd_loop` 与 `research-loop` 子命令，`loop.run_loop` 引擎与 REPL `/research-loop` 保留。命令面 74→合并后再加 `commands`=74。
- **渐进式披露**：默认 `psyclaw --help` 只列 23 个常用命令（`CORE_COMMANDS`），其余 51 个隐藏但**仍可调用**（只摘 `_choices_actions`，`choices` 分发不动）；新增 `psyclaw commands` 按职能分类打印全部（★标常用）；两个坏死 stub `write`/`init` 一并从帮助隐藏。
- 文档：`docs/COMMANDS.md` 加渐进式披露说明 + `research --freeform`；`README.md` 命令行更新。
- 测试：`tests/test_cli_help.py` +4 例（合并/披露/分发/分类覆盖）；全量 **3162 passed**。
- 未提交。

## 本轮维护(1)：`stat` 双引擎收敛 + 命令地图（应"整理命令/查重合"诉求）

- 盘清 cli.py 全部 ~72 子命令，定位唯一真冗余：`stat`(→analyze→stats_core 手写检验统计量) 与 `ttest`/`anova`(→scipy 直算) 双实现。
- **收敛**：`stats_core.{welch,student,paired}_ttest`+`pearson_r` 的 t/F/p/r 改取自 scipy `ttest_ind/rel/1samp`+`pearsonr`（与专用命令同核），保留 Cohen's d/Fisher-z CI 增量与字典结构；修 `analyze.py` 过时 docstring。
- 新增一致性门禁 `tests/test_stat_engine_consistency.py`（5 例，三方对照 stats_core/专用核/scipy），未来任一侧重新手写即变红。
- 命令地图 `docs/COMMANDS.md`：分组清单 + 选择指南（相关 6 入口/ANOVA 五选一/三种推断框架/stat-vs-专用/回归选型/前置三件套/编排回路）+ 重合速查。
- 验证：`C:\Python314\python -m pytest -q` → **3162 passed**（原 3157 + 5 一致性门禁）。
- 未提交（待用户指示）。

## Decisions Made

- **采用 harness-creator 的 5 子系统作为成熟度评分标尺**
  - Context: 两份指南共同指向"代码提供环境、模型负责思考"，harness 必须有 instructions/state/verification/scope/lifecycle
  - Alternatives considered: 先做 session store / eval harness（更大，留作 feat-011/012）

## Files Modified This Session

- `feature_list.json` - 新增 PsyClaw 能力清单（harness 一等原语）
- `init.sh` - 新增统一验证入口（compile + pytest + gates）
- `progress.md` - 本文件
- `session-handoff.md` - 新增交接模板
- `CLAUDE.md` - 新增 Harness 契约段（Startup/Definition of Done/Scope/End of Session）

## Evidence of Completion

- [x] Tests pass: `C:\Python314\python -m pytest -q` → 3131 passed
- [x] Harness 结构评分: `node .agents/skills/harness-creator/scripts/validate-harness.mjs --target .`
- [ ] Manual verification: REPL 实跑

## Notes for Next Session

harness 工件就位后，下一步选 feat-009 收尾（e2e 测试），再进 feat-010 clarify 重构。
本地测试解释器：`C:\Python314\python`（统计栈齐）；msys 默认 python 无 scipy。
