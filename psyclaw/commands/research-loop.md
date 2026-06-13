---
name: research-loop
description: HITL 科研主回路 — planner → executor → critic，带审批门与紧急停止。
---
按以下顺序执行 Human-in-the-loop（HITL）心理学研究流程：

1. **初始化**：读 PSYCLAW.md、notes/goal.md、data/ 结构，确认数据可用。

2. **规划**：planner agent → notes/plan.md（任务/依赖/审批节点/停止条件）。
   等用户确认计划后再继续。

3. **执行**：executor agent 按 plan 逐步。
   - 脚本写 scripts/，结果写 outputs/，图写 figures/，每步更新 logs/run_log.md
   - 需数据排除/重编码 → 写 notes/decision_request.md 并停止

4. **审查**：critic agent 审 outputs/ 与 scripts/（跑 gates check）→ notes/review.md
   （Blocking / Warning / Approved）。

5. **修复循环**：有 Blocking → 只修 Blocking → 重交 critic → 重复至零 Blocking。

6. **人工审批门**：任何需人工批准处 → notes/decision_request.md（理由/影响/替代方案）
   → 停止等待用户"批准"或修改意见，不擅自继续。

7. **交付**：审查通过后产出
   - outputs/report.md（只引用 outputs/ 中已存在的表图）
   - notes/repro_manifest.md（复现清单：环境、依赖、运行顺序、数据指纹）

## 紧急停止条件（任一触发立即停并通知用户）
- 原始数据缺必要字段
- 需删除/重编码但无人工批准
- critic 发现无法自动修复的 blocking
- 脚本超时或内存不足
