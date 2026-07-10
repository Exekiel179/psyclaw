---
name: verify-feature
description: 跑 PsyClaw 的 Definition-of-Done 验证（init.sh：compile + pytest + gates），把命令与输出作为 evidence 记入 feature_list.json。当用户要验证/收尾一个 feature、宣称完成前、或说 "verify" / "跑验证" / "记 evidence" 时使用。
disable-model-invocation: true
---

# verify-feature — 把 Definition-of-Done 变成一条命令

CLAUDE.md 契约：feature done 的条件 = **全量测试绿** + 把 `command and output` 作为
Verification Evidence 记入该 feature 的 `evidence` 字段。此技能封装这套仪式。

## 步骤

1. **确定目标 feature**：读 `feature_list.json`，找用户指定的 feature；未指定则列出所有
   `status != done` 的 feature 让用户选一个（**一次只验一个**，遵守 one feature at a time）。

2. **跑验证**（本机只有 `python3`，无 `python`；用 python3 覆盖 init.sh 默认解释器）：
   ```bash
   PSYCLAW_PYTHON=python3 ./init.sh
   ```
   若 init.sh 因统计栈缺失在 pytest 段失败，退回单独跑：
   ```bash
   python3 -m compileall -q psyclaw && python3 -m pytest -q && python3 -m psyclaw gates
   ```
   **完整捕获命令与输出**——包括 pass/fail 计数与任何 gates 告警。

3. **判定**：全绿才继续；有失败则**不要**改 status，把失败输出交回让用户/主循环修复。

4. **写 evidence**：全绿时，把 `command and output`（截断到关键行：pytest 汇总行、gates 结果）
   追加到该 feature 的 `evidence` 字段，并把 `status` 置为 `done`。
   - `feature_list.json` 是 harness 状态真源，且受 PreToolUse 保护会弹确认——这是有意的改动，确认放行。
   - 不伪造、不硬编码期望值；evidence 必须是**真实运行**的输出。

5. **收尾**：一句话总结验证结果 + 提示按每轮工作流 `git commit`（本技能不自动提交）。

## 铁律
- 测试没真跑绿，绝不标 done、绝不写编造的 evidence。
- 不因"看起来对"就跳过验证。证据先于断言。
