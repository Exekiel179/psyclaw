# PsyClaw 代办文档（TODO / Roadmap）

> 本文档汇总散落在 `README.md`、`DESIGN.md`、`docs/PSYCH_OPTIMIZATIONS.md` 中的代办项，统一为单一真源。
> 状态约定：✅ 已落地 · 🚧 进行中/部分 · 📋 已设计待实现 · ❓ 开放问题（需先决策）
> 最后整理：2026-06-14

---

## 0. 当前总览

四象限（文献 · 设计 · 统计 · 写作）主干**已全部打通**，门禁累计 **14 条**。本文档只列**尚未完成**或**需决策**的工作。

进度链：~~M1~~ → ~~M2a~~ → ~~M2c~~ → ~~M3~~ → ~~M2b~~ → ~~M4~~ → ~~M5~~ ✅

剩余工作按优先级分为三档：**P0 收尾主干** · **P1 心理学专业纵深** · **P2 工程化与生态**。

---

## P0 · 收尾主干（README「下一步」三件事）

| # | 任务 | 说明 | 验收 | 关联 |
|---|------|------|------|------|
| ✅ P0-1 | 审稿模拟接入 | 多视角同行评审（EIC + R1/R2/R3 + Devil's Advocate），保守 fail-closed 编辑决定 | **已落地** `psyclaw/review.py` + `agents/reviewer.md`；`psyclaw review <draft> [--revise]`（REPL `/review`）产出 `notes/review_panel.{md,json}` 可解析意见 + `response_letter.md`，`--revise` 回灌 executor 修订并复审闭合「写作→评审→修复」。测试 `tests/test_review.py`（20 例） | README §下一步 |
| ✅ P0-2 | ARS 一句话编排 | 把文献→设计→统计→写作全链编排成一句「研究 X」 | **已落地** `psyclaw/pipeline.py`:`psyclaw research <topic>`(REPL `/research`)按四象限端到端跑(澄清门禁→①文献→②设计→③ARS-Stat→④APA-JARS 写作→⑤同行评审→⑥门禁汇总),机器可读总验收落 `notes/pipeline_summary.json`(`pipeline_verdict` fail-closed:未评审/评审非 ACCEPT\|MINOR/有 BLOCKING/统计门禁阻断 均不算过门禁)。`research-loop` 仍为通用 HITL 回路。测试 `tests/test_pipeline.py`(11 例) | DESIGN §10 M5 |
| ✅ P0-3 | knowledge 抽取入综述 | 文献 knowledge 抽取自动汇入综述段落 | **已落地** `psyclaw/psych/synthesize.py`:检索命中→知识抽取(高频构念 DF)→证据图谱(构念×可回溯引用键)→**有据叙事综述**(provider 只准引用真实题录,缺失则确定性骨架)。`psyclaw lit <式> --synthesize`(REPL `/lit -s`)一键产出 `notes/lit_review.md` + `evidence_map.json`,并缓存 `notes/lit_search.json`;`psyclaw research` ① 文献阶段据该缓存合成有据综述(无缓存回落占位)。测试 `tests/test_synthesize.py`(13 例)+ `tests/test_pipeline.py` 新增 grounded 用例 | README §下一步 |

---

## P1 · 心理学专业纵深（📋 待实现）

### 1. 测量层（`psyclaw/psych/`）

| # | 任务 | 说明 | 关联门禁/文件 |
|---|------|------|--------------|
| ✅ M-1 | 量表自动计分 | ARS-Stat 据 `scales.yaml` 自动计分，含反向题翻转、子量表分 | **已落地** `psyclaw/psych/scales.py`：`score_participant`/`score_datafile`/`write_scored_csv`；`psyclaw score <data.csv> --scale <id> [--prefix Q] [--suffix A] [--method sum\|mean] [--out out.csv] [--json]`；PHQ-9 条目 9 伦理警告、DASS-42 版本歧义提示、`write_scored_csv` 追加子量表/总分列至 CSV。测试 `tests/test_scale_score.py`（28 例） |
| ✅ M-2 | 子量表自动信度 | 计分后自动跑各子量表信度（α / ω） | **已落地** `psyclaw/psych/scales.py`：`compute_subscale_reliability`(完整观测 Cronbach's α + 逐题删除后 α)；集成入 `score_datafile` 返回值 `reliability` 键；`cmd_score` 显示各维度 α + 解释文字 + 拖后腿条目提示。ω 需 R/lavaan，留 `analyze_advanced` 接口（`psyclaw stat --method omega`）。测试复用 `tests/test_scale_score.py`（37 例） |
| ✅ M-3 | 测量不变性序列 | 跨组比较前强制 configural → metric → scalar 不变性检验；不成立则阻止潜均值比较，建议部分不变性 | **已落地** `psyclaw/psych/invariance.py`：`compute_verdict`(Cheung & Rensvold 2002 ΔCFI≤−.010 AND ΔRMSEA≤.015)、`format_report`、`write_sidecar`、`_parse_r_fits`(R semTools 输出解析)；R 可用时自动执行，R 不可用时支持 `--cfi-*/--rmsea-*` 手动录入或打印脚本骨架；`psyclaw invariance <data.csv> --group <col> [--model '...']`；`MEASURE.invariance` 门禁(block，trigger: latent_mean_comparison)：scalar 不成立→阻断潜均值比较；门禁升至 17 条。测试 `tests/test_invariance.py`（31 例） |
| ✅ M-4 | 自定义量表 | 用户量表 YAML 放 `.psyclaw/scales/`，与内置库合并 | **已落地** `psyclaw/psych/scales.py`：`_user_scales_dir`/`_load_user_scales`；`list_scales`/`get_scale`/`print_scale`/`score_datafile` 均接受 `project_dir` 参数；用户同 id 优先覆盖内置；来源标签 `_source` 字段；列表视图显示 `[用户:文件名]`；损坏文件 warning 跳过不中断；内置量表标记 `built-in`。测试 `tests/test_custom_scales.py`（22 例） |
| ✅ M-5 | 草率作答扩展指标 | psychsyn/psychant 语义一致性、Mahalanobis D、作答时间（Q{N}E）、假词法（infrequency items） | **已落地** `psyclaw/psych/careless.py`：`psychsyn_score`(同/反义题对一致性)、`mahalanobis_d`+`chi2_critical`(纯 stdlib Gauss-Jordan 矩阵求逆,Tabachnick & Fidell 阈值)、`response_time_flag`(Q{N}E 列速度标记)、`infrequency_score`(陷阱词项偏离计数)；`flag_respondent` 整合四类新指标；`screen_csv` 自动检测时间列并跑全局 Mahalanobis D²；CLI `--no-mahal` 可关闭。测试 `tests/test_careless.py`（44 例） |

### 2. 设计层

| # | 任务 | 说明 | 关联门禁 |
|---|------|------|----------|
| ✅ D-1 | 功效分析预设 | 对标 G*Power：t / ANOVA / 相关回归 / 中介（Monte Carlo）/ SEM（MacCallum RMSEA）；先验默认 r≈.20 / d≈.40，提示发表偏倚高估 | **已落地** `psyclaw/psych/power.py`：纯 stdlib 非中心 t（积分）/F/χ²（Poisson 级数）核 + 六类检验功效与样本量反解（双向）；`psyclaw power <ttest\|anova\|r\|regression\|sem\|mediation> [-n N \| --power .80] [--json]`，保守先验默认 + 发表偏倚告警。无 scipy 环境下用闭式自检 + G*Power/Cohen 锚点 + 双路径互证验证。测试 `tests/test_power.py`（31 例） | `DESIGN.power` |
| ✅ D-2 | 预注册模板 | `/preregister` 生成 OSF / AsPredicted 双格式，自动抽取假设（确证/探索）、IV/DV/协变量、剔除规则、样本量依据、分析计划 | **已落地** `psyclaw/psych/preregister.py`：读 `notes/clarification.md`（17 槽位）→ OSF 6 节标准模板 + AsPredicted 标准 8 问双文稿（`notes/preregistration_{osf,aspredicted}.md`）。假设按确证/探索自动归类，未标注 **fail-closed 按探索性**并告警（防 HARKing）；关键槽位缺失渲染 `[待补充]` 占位+告警，不替用户编造；`--test` 复用 D-1 `power.compute` 嵌入确定性样本量依据（保留发表偏倚告警）。`psyclaw preregister [--osf\|--aspredicted] [--test … 功效参数]`（REPL `/preregister`）。测试 `tests/test_preregister.py`（21 例） |
| ✅ D-3 | 伦理提示 | 敏感测量（如 PHQ-9 条目 9 自伤意念）触发 IRB / 危机转介提示，量表库 `notes` 为触发源 | **已落地** `psyclaw/psych/ethics.py`：`check_scale_ethics`(notes 关键词检测)、`check_item_level_ethics`(数据感知，PHQ-9 条目 9 计数)、`ethics_summary`/`format_ethics_report`；`score_datafile` 集成（替换硬编码 PHQ-9 检查，通用化到 notes 驱动）；`MEASURE.ethics` 软门禁（warn, `scale_score_used`, `ethics_reviewed` 自动校验）入 `rules.yaml`+`checker.py`；新命令 `psyclaw ethics <id>`。测试 `tests/test_ethics.py`（32 例），门禁升至 16 条。 |

### 3. 分析层

| # | 任务 | 说明 | 关联门禁 |
|---|------|------|----------|
| ✅ A-1 | 心理学检验决策树特判 | 嵌套数据强制 MLM + 报 ICC；Likert 单题默认有序处理；大样本「显著但效应可忽略」自动改用效应量语言；中介默认 bootstrap CI(5000)，拒 Sobel；调节报简单斜率 + Johnson-Neyman；SEM 全拟合指数 | **已落地** `psyclaw/psych/decision_tree.py`：`detect_likert` / `large_sample_effect_language` / `compute_icc` / `bootstrap_mediation` / `moderation_analysis`；集成到 `analyze.py` (Likert/ICC/大样本自动检测)；新命令 `psyclaw mediation` / `psyclaw moderation`，`psyclaw stat --cluster`。测试 `tests/test_decision_tree.py`（35 例） |
| ✅ A-2 | 多重比较 / 研究者自由度 | 分析前声明计划写入 `notes/plan.md`；偏离即触发审计记录；探索性分析强制标注 + 建议 split-half 验证 | **已落地** `psyclaw/psych/analysis_plan.py`：`declare/check/log_deviation`；`psyclaw declare-test --dv … --test … --hypothesis confirmatory\|exploratory`；`analyze.py` 集成 plan_check——确证性/探索性/未声明三态 + 偏离时写 `notes/audit_deviations.md` + APA 段前缀标注 + 探索性 split-half 建议。测试 `tests/test_analysis_plan.py`（20 例） |

### 4. 写作层（`psyclaw/output/`）

| # | 任务 | 说明 |
|---|------|------|
| ✅ W-1 | JARS 检查单 | 按研究类型挂 JARS-Quant / Qual / Mixed；缺项（缺失数据处理、剔除人数与理由）阻断 | **已落地** `psyclaw/output/jars.py`：`check_draft`(quant/qual/mixed 三路径)、`format_report`、sidecar IO；`psyclaw jars <draft.md> [--type quant\|qual\|mixed] [--json]`；阻断项(缺失数据处理+剔除信息)exit-code 1；写 `notes/jars_check.json`；`WRITE.jars` 门禁集成(`rules.yaml` + `checker.py` + `KIND_TRIGGERS["jars"]`)，自动校验(`jars_missing_data`/`jars_exclusions`)。门禁升至 15 条。测试 `tests/test_jars.py`（40 例） |
| ✅ W-2 | 统计结果 APA7 格式器深化 | 斜体统计量、两位小数、`p < .001` 规则、效应量符号、三线表；扩展现有 `apa7.py` | **已落地** `psyclaw/output/apa7.py`：`format_apa_stat_md`(斜体 *t*/*F*/*r*/*p*/*d*/*η*²/*ω*²)、`format_apa_p`(APA7 p 格式)、`format_apa_stat`(两位小数 + 前导零移除)、`_split_for_italic`、`_table_three_line`(OOXML 三线表)、`APA7Document.add_stat_table`、`_p_stat`(段落斜体 run)。测试 `tests/test_apa7_stat.py`（30 例） |
| ✅ W-3 | 中文心理学语境 | 中文版量表常模进量表库扩展字段；《心理学报》/《心理科学》格式 vs APA 切换；中英双语模板 | **已落地** `psyclaw/psych/cn_norms.json`（7 个内置量表中文常模/截断值）；`psyclaw/psych/scales.py`：`get_cn_norms`/`format_cn_norms_text`/`print_cn_norms`；`psyclaw/output/cn_journal.py`：`JOURNALS` 三格式规格 + `format_bilingual_abstract` + `format_cn_reference`(GB/T 7714) + `convert_to_cn_format`（节标题/参考文献转换）+ `CnJournalDocument`；CLI：`psyclaw norms <id>` + `psyclaw export --journal {xinlixuebao,xinlikexue,apa7}`。测试 `tests/test_cn_journal.py`（64 例） |

---

## P2 · 工程化与生态

| # | 任务 | 说明 |
|---|------|------|
| ✅ E-1 | 图表主题层 | **已落地** `psyclaw/figures.py`：`apply_style(name)` contextmanager(matplotlib rcParams；无 matplotlib 时静默降级)、`honesty_check(spec)` FIG.honest 三项自动核查(axis_from_zero_or_flagged/error_bar_meaning/colorblind_safe)、`write_figure_sidecar` 写 sidecar JSON、`okabe_ito_palette(n)` 色盲友好调色板、`list_styles/theme_spec` 读取 figure_style.yaml；`REQUIREMENT_CHECKS` 注册 FIG.honest 三项(checker.py)；`psyclaw figures [--list-styles\|--style\|--check spec.json\|--palette N]`；测试 `tests/test_figures.py`（51 例）；门禁自动化升至 20 项。 |
| ✅ E-2 | 商业统计软件 MCP | **已落地** `psyclaw/mcp/servers/mplus_server.py`：Mplus CFA/SEM/LGM/Mixture 语法生成 + 批处理执行（mplus_syntax/mplus_run）；`psyclaw/mcp/servers/stata_server.py`：Stata do-file 生成 + 批处理执行（stata_dofile/stata_run，涵盖 regression/panel/iv/logistic/survival/poisson）；两服务器均已注册为 registry.yaml 内置 MCP（enable_when: always）并入 CLI `psyclaw mcp --serve mplus|stata`。测试 `tests/test_mcp_servers.py`（44 例）。 |
| ✅ E-3 | MCP registry 完善 | **已落地** `psyclaw/mcp/manager.py`：`health_check`(模块 find_spec 探测)/`list_mcp_catalog_with_health`/`probe_capabilities`(能力聚合)；`psyclaw/config.py`：向导改为 registry 驱动——`_configure_mcp_servers` 遍历所有服务器，always 标为始终启用，detect: 自动检测二进制，env: 逐项询问并写入 .env；`psyclaw doctor` 升级为健康检查面板（✓/·/✗）+ 能力探测列表 + MCP 失败纳入总体 exit-code。测试 `tests/test_mcp_registry.py`（41 例）。 |

---

## P3 · 自我扩展（E-3 完成后新增）

| # | 任务 | 说明 | 验收 |
|---|------|------|------|
| ✅ P3-1 | 元分析工具 | **已落地** `psyclaw/psych/meta.py`：DerSimonian-Laird 随机效应模型、Q/I²/τ²/τ 异质性、Egger's 偏倚检验(k≥10)、固定效应对比、ASCII 森林图、APA-7 中文段落；stdlib only（无scipy降级可用）；`STAT.meta` 门禁（meta_heterogeneity_reported + meta_effect_ci_reported，block）注册入 `rules.yaml`+`checker.py`；`psyclaw meta <data.csv> [--json] [--out dir] [--no-forest]`；四种 SE 推导（se/ci/n1n2/r+n Fisher z）；门禁升至 21 项。测试 `tests/test_meta.py`（48 例，全绿）。 | `tests/test_meta.py` ≥30例，无scipy降级可用 |
| 📋 P3-2 | 缺失数据报告 | `psyclaw missing <data.csv>` — 缺失模式矩阵、Little's MCAR 检验、MAR 预测(分组缺失比较)、推荐插补策略、APA-7 缺失报告段落。`psyclaw/psych/missing_data.py`。 | `tests/test_missing_data.py` ≥25例 |
| 📋 P3-3 | 敏感性分析框架 | `psyclaw sensitivity <plan.md>` — 据 `notes/plan.md` 中分析决策分叉点产出多种合理分析规格(Multiverse分析框架)、汇报规格曲线(effect size分布)。 | `tests/test_sensitivity.py` ≥20例 |

---

## ✅ 已决策（2026-06-14，原 DESIGN §8 开放问题）

1. **REPL 库选型 → `prompt_toolkit`（功能全）**。落地为 R-1，**保留 stdlib 降级**（零依赖铁律不破）。
2. **ARS 子技能组织 → 维持现状**：独立子技能 SKILL.md + ARS 总编排，不改。
3. **复用 academic-research-skills 插件作为 writing 子技能后端 → 采纳**。落地为 R-2。
4. **商业统计软件 MCP 归属 → 定位为「可选便捷集成」**：`spss-mcp` 为用户（你）自研；Mplus/Stata/SPSS 等 MCP 仅在用户本机检测到对应软件时启用（`enable_when: detect`），用户自愿使用，非核心路径。E-2/E-3 已实现该可选模型，仅需补全归属标注（R-3）。

## P4 · 决策落地任务（优先于 P3 自我扩展）

| # | 任务 | 说明 | 验收 |
|---|------|------|------|
| 📋 R-1 | prompt_toolkit REPL 后端 | `repl.py` 接入 prompt_toolkit（命令补全/历史/多行/键位），**装了才用、未装回落现有 stdlib msvcrt/termios 双实现**（零依赖铁律不破）；`full` 选装组已含 prompt_toolkit | `tests/test_repl_ptk.py`；无 prompt_toolkit 环境 REPL 仍可跑、现有命令不回归 |
| 📋 R-2 | writing 后端复用 academic-research-skills | `skills/ars` writing 子技能后端对接 academic-research-skills 插件（academic-paper 写作 + reviewer、APA-JARS/双语摘要能力），**插件缺失时回落现有内置写作**；与 P0-1 评审保持单一契约不重复造轮子 | `tests/test_writing_backend.py`；插件缺失降级可用 |
| 📋 R-3 | 商业统计 MCP 归属标注 | `registry.yaml`/`manager.py` 标注 `spss-mcp` 为用户自研、Mplus/Stata 为可选便捷集成（`enable_when: detect`，本机有软件才启用）；`doctor` 文案体现「可选」 | 现有 MCP 测试不回归 + 标注校验 |
| ✅ R-4 | REPL 输出框 Markdown 渲染（**用户实测痛点，优先**） | **已落地** `psyclaw/md_render.py`：`render_md`/`_render`/`_inline`/`_paint`；支持 **bold**/*italic*/`code`/# H1–H3/有序+无序列表/---水平线/> 引用/``` 代码块；`enabled` 参数独立于 `ui._ENABLED`（可在非 TTY 测试环境中验证 ANSI 输出）；`NO_COLOR`/非 TTY 降级为去标记纯文本；`ui.StreamBlock` 改为缓冲整块内容，`close()` 时 Markdown 渲染 + ANSI 光标覆盖生成指示符。`tests/test_ui_markdown.py`（62 例）。 | `tests/test_ui_markdown.py` ≥25例，NO_COLOR 无 ANSI 且无残留标记符 |

---

## 里程碑对照（DESIGN §10 原始路线图）

| 里程碑 | 内容 | 状态 |
|--------|------|------|
| M0–M5 | 骨架 → REPL → ARS-Stat → Gates → MCP → 全流水线 | ✅ 主干完成 |
| 后续 | 审稿模拟 · 一句话编排 · 综述自动化 · 心理学纵深 · 工程化 | 📋 即本文档 P0–P2 |

---

## 建议的下一步执行顺序

1. ~~**P0-1 审稿模拟**~~ ✅ 已闭合「写作 → 评审 → 修复」回路（`psyclaw/review.py`）。
2. ~~**P0-2 一句话编排**~~ ✅ 四象限端到端流水线（`psyclaw/pipeline.py`,`psyclaw research`）。
3. ~~**P0-3 knowledge 抽取入综述**~~ ✅ `/lit --synthesize` 一键综述 + 流水线 ① 据 `/lit` 缓存合成有据综述（`psyclaw/psych/synthesize.py`）。
4. ~~**D-1 功效分析**~~ ✅ G*Power 对标的先验功效分析（`psyclaw power`，`psyclaw/psych/power.py`）。
5. ~~**D-2 预注册模板**~~ ✅ `/preregister` 据澄清卡产 OSF/AsPredicted 双格式，复用 D-1 功效（`psyclaw/psych/preregister.py`）。
6. ~~**A-1 检验决策树特判**~~ ✅ 六类特判落地(`psyclaw/psych/decision_tree.py`)。
7. ~~**R-4 REPL Markdown 渲染**~~ ✅ 整块缓冲 + Markdown→ANSI（`psyclaw/md_render.py`）→ **R-1 prompt_toolkit REPL** → **R-2 writing 复用 academic-research-skills** → **R-3 MCP 归属标注**（决策已定，优先于 P3）。
8. 其余 P1/P2/P3 按需排期。
