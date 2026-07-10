---
name: run-stats-mcp
description: 需要跑统计（t 检验/方差/回归/因子/SEM/生存/EEG…）时，路由到正确的外部 MCP 服务器或 [stats] extra，而不是在 psyclaw 仓内重新实现算法。当任务涉及统计计算、选择统计方法、或有人想在 psyclaw 里写统计代码时使用。
---

# run-stats-mcp — 统计一律外移，psyclaw 只做编排

## 硬约束（CLAUDE.md 铁律）
**禁止在 psyclaw 仓内实现任何统计算法**（分布函数/参数估计/检验/因子/生存…）。
统计已整体外移。psyclaw 只保留编排、知识参考、文献/写作、澄清/预注册、门禁。
需要数值时——交给外部 MCP 服务器，或用户按需装的 `[stats]` extra（pingouin/scipy/statsmodels/
lifelines/factor_analyzer/semopy）。**绝不**为了"省事"在本仓写统计。

## 方法 → 服务器路由（真源：`psyclaw/mcp/registry.yaml`）
| 需求 | MCP 服务器 | provides |
|---|---|---|
| 描述统计 / t 检验 / 方差 / 回归 / 中介 | **pystat**（always） | pingouin, statsmodels |
| CFA/SEM / 多层 / 信度 / semTools（R） | **r-mcp**（检测 Rscript） | lavaan, lme4, psych, semTools |
| CFA/SEM/LGM/Mixture 语法（Mplus） | **mplus-mcp**（检测 Mplus，可选） | *_syntax, mplus_run |
| SPSS 语法 / 信度 / 因子 / ANCOVA | **spss-mcp**（检测 IBM Statistics，可选） | syntax_gen, sav_run |
| EEG/ERP / 聚类统计 | **mne-mcp**（always） | erp_components, cluster_stats |
| 面板 / IV / logistic / 生存 / 泊松（Stata） | **stata-mcp**（检测 Stata，可选） | dofile_gen, panel, iv, survival |

以 `registry.yaml` 为准（可能已扩展）；`origin: optional/user` 的商业软件仅本机检测到才启用，
不纳入强制健康门禁。

## 步骤
1. 明确统计需求（检验类型、设计、变量层级、假设）。
2. 查上表 / `registry.yaml` 选服务器；用 `python3 -m psyclaw config`（或 doctor）确认其可用。
3. 目标服务器不可用时：告知用户装对应软件或 `pip install 'psyclaw[stats]'`，**不要**回落到自写统计。
4. 通过 MCP 提交数据/参数、取回结果。
5. 结果**仍须过门禁**：效应量+CI、假设检查、探索/确证区分——必要时调 `gates-auditor` 子代理。

## 反模式（禁止）
- 在 `psyclaw/` 下新建/恢复任何统计实现文件（历史上的 ttest.py/anova.py/survival.py 已被删除，别复活）。
- 用 stdlib 手搓分布函数/检验来"绕过"缺依赖。缺依赖就报错并提示装栈。
