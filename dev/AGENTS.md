# AGENTS.md — PsyClaw 项目工作准则（保持精简，每个词都在烧 token）

PsyClaw 是心理学研究**编排** Agent CLI，纯 Python、纯 stdlib 核（无第三方硬依赖）。
负责文献→设计→写作→评审→质量检查的研究流程编排 + 知识参考 + 澄清/预注册；
**统计计算已整体外移到成熟库/MCP——psyclaw 自身不内置、不 import 任何统计库**。
入口 `python -m psyclaw`，包根 `psyclaw/`，测试 `C:\Python314\python -m pytest -q`。
架构细节见 `DESIGN.md`，计划真源是 `TODO.md`，过夜任务说明见 `PROMPT.md`。

## 自主运行决策规则（永不卡住、永不等人）

- **永远不要提问**。做出最佳判断然后继续。
- 技术方案不确定 → 选**传统/成熟**方案。
- 两种可行实现 → 选**更简单**的那个。
- 需求模糊 → 应用最合理的理解，把假设记进提交信息或 `notes/mission.md`。
- 同一错误尝试 **3 次**仍无进展 → 记录到 `notes/blocked.md`，**切换到下一个任务**，
  不要在一个坑里无限循环。
- 需要不可逆操作（删数据、改测量口径、改质量检查判据）→ 不自作主张，写
  `notes/decision_request.md`（理由/影响/替代）后**跳过**该任务。

## 上下文管理（防止压缩后失忆）

- 上下文变大时，先把当前状态写入 `notes/mission.md`，包含：**已完成 / 下一步 /
  被阻塞 / 未解决的问题**，以及**完整的已修改文件列表**。
- 里程碑后主动 `/compact`，不要干等自动压缩。
- 每个任务用全新一轮循环迭代（Ralph 模式天然给你干净上下文）——不要把多个任务堆在一轮。

## 项目铁律（违反即视为失败）

- **通用修复，不打临时补丁**：不写 `# TODO 以后再改`、不 mock 真实逻辑、不为过测试硬编码期望值。
- **不在 psyclaw 内做统计计算**：统计已整体外移到成熟库/MCP。禁止在本仓重新实现任何统计算法
  （分布函数/参数估计/检验/因子/生存…）——需要统计时交给外部 scipy/pingouin/statsmodels/lifelines
  或 MCP 服务器。psyclaw 只保留研究编排、知识参考、文献/写作、澄清/预注册、质量检查等 harness 层。
- **不破坏既有契约**：保留命令（research/review/clarify/lit/export/score/scale/preregister/jars… ）行为不回归；质量检查只增不偷偷删。
- **学术诚信不可妥协**：效应量+CI 必报、相关≠因果、区分探索/确证、不 p-hacking——
  写作产出与质量检查判据都要符合 `gates/PSYCLAW.md`（统计虽外移，规范检查仍在）。
- **不碰真实数据/密钥**：不读写用户原始 `data/`，不在代码或提交里写入任何 API key。
- **改动外科手术化**：只动当前任务相关文件，不顺手重构无关代码。

## 每轮工作流（一轮一任务一提交）

1. 读 `TODO.md` + `git log --oneline -15`，选一个未完成、依赖就绪的最高优先级任务。
2. 动手前先读相关现有文件，别假设结构。正确性 > 速度。
3. 实现 + 完善错误处理。
4. 加/改 `tests/test_*.py`，跑全绿（本机 `C:\Python314\python -m pytest -q`）。
5. 改了 `gates/` 或产出逻辑就跑 `python -m psyclaw gates` 自检。
6. 在 `TODO.md` 把该任务标 ✅ 并注明实现文件。
7. `git add -A && git commit -m "<描述性消息：做了什么 + 在哪个文件>"`。

## Harness 契约（machine-checkable，learn-harness-engineering 5 子系统）

状态真源 = `feature_list.json`（features[].status/dependencies/evidence）；计划真源 = `TODO.md`；
人读快照 = `progress.md`；交接 = `session-handoff.md`。结构分见
`node .agents/skills/harness-creator/scripts/validate-harness.mjs --target .`。

- **Startup Workflow（Before writing code）**：先 `PSYCLAW_PYTHON=C:/Python314/python ./init.sh`
  跑 Verification Commands（compile + pytest + gates），再读 `feature_list.json` + `progress.md` 接续上下文。
- **One feature at a time**：每轮只推进 ONE 个 `status != done` 的 feature；**Stay in scope**，
  不顺手动无关代码（与「改动外科手术化」一致）。
- **Definition of Done**：done only when —— 全量测试绿 + 把 `command and output` 作为
  Verification Evidence 记入该 feature 的 `evidence` 字段。质量检查只增不删。
- **End of Session（Before ending）**：更新 `progress.md`（Current State/What/Next）与
  `session-handoff.md`（Blockers/Files/Next Session/Recommended Next Step），留下 clean、restartable 的状态。

## 危险命令（绝不执行）

`rm -rf`、`git reset --hard`、`git push --force`、推送到 `master`/`main`、`DROP TABLE`、
覆盖 `data/` 原始数据。受保护分支：master、main。

## Imported Claude Cowork project instructions
