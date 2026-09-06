# PsyClaw 模式与 ARS（0.29）

上游 ARS：`Imbad0202/academic-research-skills` @ `v3.21.1`（CC BY-NC 4.0）

## 三种模式（Shift+Tab 循环）

| 模式 | 底栏 | 用途 |
| --- | --- | --- |
| `chat` | （空） | 普通 Pi 对话 |
| `analysis` | analysis | 澄清→`/plan` 方案→跑数→分析报告→审查→HANDOFF |
| `academic` | academic | ARS 写作/审稿；消费 `analysis/HANDOFF.md`，不重选主检验 |

Thinking level：`Ctrl+Shift+Tab`。

## Analysis 软路由（统计方案）

analysis 模式下，清晰的数据分析 / 统计意图会 soft-takeover 到核心 Skill `analysis-plan`（无需手打 `/skill:`）。

阶段：澄清 + 轻量 EDA → 结构化提案 → `/plan confirm` 软确认 → `/plan review` → `/plan run`（立即）或 `/plan defer`（稍后）。

- 默认执行：在 `analysis/scripts/` 写本地可复现脚本（成熟库）。
- MCP：仅特殊后端（SPSS/Mplus/MNE/Stata）或用户明确要求。
- 状态落在 `analysis/plans/`；与 ARS 方案硬分离，交接靠 `analysis/HANDOFF.md`。

## Academic 软路由（allowlist）

academic 模式下，下列内置 Skill **无需**用户手打 `/skill:`，自然语言会软路由过去：

- ARS：`deep-research`、`academic-paper`、`academic-paper-reviewer`、`academic-pipeline`
- Compose：`academic-paper-strategist`、`academic-paper-composer`
- Nature 查漏：`nature-figure`、`nature-ref-verifier`、`nature-polishing`

其余 Skill 必须显式 `/skill:<name>`。用户已输入的 `/skill:` 或 `/ars-*` 优先于软路由。

多步请求（如「先大纲再成稿」）按文中**最先出现的意图**选 primary，其余 allowlist 命中进入 follow-up。评测：`pnpm eval:academic-route`。

## `/init`

只搭建干净仓库（`data/raw|clean`、`analysis/`、`literature/`、`paper/`、`psyclaw.md`、`.psyclaw/`），**不**自动 academic-grill。没有单独的 `/run` 命令；建仓后即可在 analysis / academic 模式推进。

## 软门禁与核查

- 优先把结果跑出来；未 `/verify` 时警告并继续，关键项标未核实。
- `/verify list` / `/verify <id> verified`：人确认 N、主效应、表文一致等。
- `/plan`：分析方案状态机（soft confirm ≠ ARS checkpoint ≠ awaiting-human）。
- 指纹仅保护 raw 篡改等核心边界，不作学术过关证明。

## ARS

`academic` 模式静默激活 ARS session；`psyclaw_ars_multi_agent` 做进程隔离审稿。PDF 引擎按需 `psyclaw_ensure_pdf_engine`。
