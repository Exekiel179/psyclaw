# PsyClaw 模式与 ARS（0.29）

上游 ARS：`Imbad0202/academic-research-skills` @ `v3.21.1`（CC BY-NC 4.0）

## 三种模式（Shift+Tab 循环）

| 模式 | 底栏 | 用途 |
| --- | --- | --- |
| `chat` | （空） | 普通 Pi 对话 |
| `analysis` | analysis | 澄清→方案→跑数→分析报告→审查 |
| `academic` | academic | ARS 写作/审稿；消费 `analysis/HANDOFF.md` |

Thinking level：`Ctrl+Shift+Tab`。

## `/init`

只搭建干净仓库（`data/raw|clean`、`analysis/`、`literature/`、`paper/`、`psyclaw.md`、`.psyclaw/`），**不**自动 academic-grill，**不**强制 `/run`。

## 软门禁与核查

- 优先把结果跑出来；缺 `/run` 或未 `/verify` 时警告并继续，关键项标未核实。
- `/verify list` / `/verify <id> verified`：人确认 N、主效应、表文一致等。
- 指纹仅保护 raw 篡改等核心边界，不作学术过关证明。

## ARS

`academic` 模式静默激活 ARS session；`psyclaw_ars_multi_agent` 做进程隔离审稿。PDF 引擎按需 `psyclaw_ensure_pdf_engine`。
