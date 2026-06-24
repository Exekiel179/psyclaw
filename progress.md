# PsyClaw Session Progress Log

## Current State

**Last Updated:** 2026-06-24
**Current Objective:** 按 learn-harness-engineering / learn-hermes-agent 两份指南，把 PsyClaw 补到成熟 harness 水准
**Active Feature:** feat-010 clarify LLM 驱动追问（feat-008/009 已 done，见 `feature_list.json`）

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

- [ ] （空）下一轮选 feat-010

### What's Next

1. feat-010 clarify LLM 驱动追问（CLAR-1..4）—— 流水线前门，最高杠杆
2. feat-011 会话持久化 session store（SQLite+FTS5，Hermes s03）
3. feat-012 判断层评估 harness（eval suite，Hermes s23）—— 商业化"可信"护城河

## Blockers / Risks

- [ ] 文档去债：DESIGN.md / TODO.md / 部分 docstring（如 diagnostics.py 第 1 行）仍写"纯 stdlib"，迁移后已过时
- [ ] 部分迁移残留：negbin/ordinal/multinomial/mlm 仍保留手写估计器（测试钉住内部 helper），未来改用 statsmodels 需同步重写测试

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
