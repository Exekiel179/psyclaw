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
| ✅ P3-2 | 缺失数据报告 | **已落地** `psyclaw/psych/missing_data.py`：缺失模式矩阵（`missing_pattern`）、Little's MCAR 检验（`little_mcar_test`，完整案例协方差估计，stdlib only）、MAR 预测分组 t 检验（`mar_test`，Welch df）、插补策略推荐（`recommend_imputation`，MCAR/MAR/比例三维判断）、APA-7 缺失报告段落（`format_apa_missing`）；主入口 `analyze_missing` 写 `missing_report.md` + `missing_report.json`；CLI `psyclaw missing <data.csv> [--json] [--out <dir>]`（已注册 `cli.py`）。测试 `tests/test_missing_data.py`（39 例）。 | `tests/test_missing_data.py` ≥25例 |
| ✅ P3-3 | 敏感性分析框架 | **已落地** `psyclaw/psych/sensitivity.py`：极简 YAML 解析（`_parse_forks_yaml`，避免 pyyaml）、笛卡尔积多元宇宙生成（`generate_multiverse`）、组内 SD 阈值离群值过滤（`_apply_outlier_filter`）、三类统计检验（Welch/Student/Mann-Whitney，效应量统一转 Cohen's *d*）、稳健性指标（`compute_robustness`）、ASCII 规格曲线表（`format_ascii_spec_curve`）、APA-7 段落（`format_apa_sensitivity`）、MD+JSON sidecar 输出；`psyclaw sensitivity <plan.md\|forks.yaml> [--data CSV] [--dv col] [--group col] [--out dir]`（REPL `/sensitivity`）；引入 Steegen et al. 2016 + Simonsohn et al. 2020 引文。测试 `tests/test_sensitivity.py`（43 例）。 | `tests/test_sensitivity.py` ≥20例 |

---

## ✅ 已决策（2026-06-14，原 DESIGN §8 开放问题）

1. **REPL 库选型 → `prompt_toolkit`（功能全）**。落地为 R-1，**保留 stdlib 降级**（零依赖铁律不破）。
2. **ARS 子技能组织 → 维持现状**：独立子技能 SKILL.md + ARS 总编排，不改。
3. **复用 academic-research-skills 插件作为 writing 子技能后端 → 采纳**。落地为 R-2。
4. **商业统计软件 MCP 归属 → 定位为「可选便捷集成」**：`spss-mcp` 为用户（你）自研；Mplus/Stata/SPSS 等 MCP 仅在用户本机检测到对应软件时启用（`enable_when: detect`），用户自愿使用，非核心路径。E-2/E-3 已实现该可选模型，仅需补全归属标注（R-3）。

## P4 · 决策落地任务（优先于 P3 自我扩展）

| # | 任务 | 说明 | 验收 |
|---|------|------|------|
| ✅ R-1 | prompt_toolkit REPL 后端 | **已落地** `psyclaw/ui_input.py`：`_slash_completions`(纯函数补全逻辑)、`_SlashCompleter`(ptk Completer子类，仅 ptk 可用时定义)、`_get_ptk_session`(单例 PromptSession，InMemoryHistory)、`_ptk_read_line`；`read_line` 优先路径：ptk available + TTY → ptk；ptk 失败/非 TTY → stdlib 交互 → input() 三级降级，KeyboardInterrupt/EOFError 始终穿透。`tests/test_repl_ptk.py`（28 例）。 | `tests/test_repl_ptk.py`；无 prompt_toolkit 环境 REPL 仍可跑、现有命令不回归 |
| ✅ R-2 | writing 后端复用 academic-research-skills | **已落地** `psyclaw/output/writing_backend.py`：`detect_backend`（env var→插件路径→builtin 三级优先）、`get_write_task`（ARS 后端含双语摘要/JARS 章节列表，内置保持原契约）、`write_abstract`（双语/单语两路+LLM解析）、`write_paper`（主入口，ARS 后端附加双语摘要 `notes/abstract_bilingual.md` + JARS 自动检查）；插件缺失或 env=builtin 自动降级；`pipeline.py` ④ 写作阶段改用 `write_paper()`（评审仍在 review.py，单一契约不破）。测试 `tests/test_writing_backend.py`（42 例）。 | `tests/test_writing_backend.py`；插件缺失降级可用 |
| ✅ R-3 | 商业统计 MCP 归属标注 | **已落地** `registry.yaml`：mplus-mcp/stata-mcp → `origin: optional` + `category: stats-commercial` + `enable_when: detect:mplus/stata`；spss-mcp → `origin: user` + `enable_when: detect:statisticsb`；mne-mcp 保留 `origin: builtin/always`。`manager.py`：`is_optional()`/`OPTIONAL_ORIGINS`/`health_check` 带「可选，未安装」标注/`list_mcp_catalog*` 含 origin 字段/SERVER_NOTES 更新；`cli.py` `doctor` 可选服务器不计入强制门禁/`[可选]` 标签；`cmd_mcp` 显示 `[可选]` 标签。测试 `tests/test_mcp_registry.py`（61 例，较原 41 例 +20）。 | 现有 MCP 测试不回归 + 标注校验 |
| ✅ R-4 | REPL 输出框 Markdown 渲染（**用户实测痛点，优先**） | **已落地** `psyclaw/md_render.py`：`render_md`/`_render`/`_inline`/`_paint`；支持 **bold**/*italic*/`code`/# H1–H3/有序+无序列表/---水平线/> 引用/``` 代码块；`enabled` 参数独立于 `ui._ENABLED`（可在非 TTY 测试环境中验证 ANSI 输出）；`NO_COLOR`/非 TTY 降级为去标记纯文本；`ui.StreamBlock` 改为缓冲整块内容，`close()` 时 Markdown 渲染 + ANSI 光标覆盖生成指示符。`tests/test_ui_markdown.py`（62 例）。 | `tests/test_ui_markdown.py` ≥25例，NO_COLOR 无 ANSI 且无残留标记符 |

---

## 里程碑对照（DESIGN §10 原始路线图）

| 里程碑 | 内容 | 状态 |
|--------|------|------|
| M0–M5 | 骨架 → REPL → ARS-Stat → Gates → MCP → 全流水线 | ✅ 主干完成 |
| 后续 | 审稿模拟 · 一句话编排 · 综述自动化 · 心理学纵深 · 工程化 | 📋 即本文档 P0–P2 |

---

---

## P4 · 持续扩展（P3 完成后自我扩展）

| # | 任务 | 说明 | 验收 |
|---|------|------|------|
| ✅ P4-1 | TOST 等价检验 | **已落地** `psyclaw/psych/equivalence.py`：`tost_two_sample`（Welch t）、`tost_one_sample`（单样本）、`tost_paired`（配对）三类 TOST；`compute_mdes`（大样本正态近似 MDES）；`format_apa_equivalence` APA-7 段落；`write_equivalence_report` MD+JSON sidecar；`analyze_equivalence` CSV 主入口；`equivalence_cli`；`STAT.equivalence` 门禁（block，trigger: equivalence_test，自动校验 `equivalence_tested`）注册入 `rules.yaml`+`checker.py`+`KIND_TRIGGERS`；`psyclaw tost <data.csv> --dv <col> --group <col> --lower <lb> --upper <ub> [--alpha] [--paired] [--one-sample <mu0>] [--json] [--out]`。理论依据：Schuirmann 1987；Lakens 2017；Lakens et al. 2018。门禁升至 19 条。测试 `tests/test_equivalence.py`（49 例）。 | `tests/test_equivalence.py` ≥25例，STAT.equivalence 门禁自动校验 |
| ✅ P4-2 | 贝叶斯因子分析 | **已落地** `psyclaw/psych/bayes.py`：`bf_t_one_sample`（单样本/配对，JZS Cauchy 先验）、`bf_t_two_sample`（独立样本）、`bf_correlation`（Pearson r）三类贝叶斯因子；`_quad_0_inf_stdlib`（变量替换中点法数值积分）+ scipy 精确积分可选升级；`interpret_bf`（Jeffreys 1961 + Lee & Wagenmakers 2013 量表）；`format_apa_bayes` APA-7 段落；`write_bayes_report` MD+JSON sidecar；`analyze_bayes` CSV 主入口；`bayes_cli`；`psyclaw bayes <data.csv> --dv <col> --test ttest\|paired\|correlation [--group <col>] [--mu0 0] [--r-scale 0.707] [--json] [--out]`。理论依据：Rouder et al. 2009；Ly et al. 2016；Lee & Wagenmakers 2013。stdlib only + scipy 可用时自动升级精度。测试 `tests/test_bayes.py`（56 例）。 | `tests/test_bayes.py` ≥40例，BF₁₀ × BF₀₁ ≈ 1，解读量表边界正确 |
| ✅ P5-1 | 描述统计报告 | **已落地** `psyclaw/psych/descriptives.py`：`compute_descriptives`（N/M/SD/SE/Median/Sk/Kurt/95%CI）、`compute_correlation_matrix`（Pearson r + 双尾 p + Fisher-z CI）、`format_apa_descriptives_table`（APA-7 Markdown 三线表）、`format_apa_correlation_table`（下三角 \*/\*\*/\*\*\* 标注）、`format_apa_paragraph`、`write_descriptives_report`（MD+JSON sidecar）、`analyze_descriptives` CSV 主入口；stdlib only；`psyclaw describe <data.csv> [--cols c1,c2] [--corr] [--alpha .05] [--json] [--out dir]`。峰度公式 SPSS/Excel 兼容（G2）。测试 `tests/test_descriptives.py`（47 例）。 | `tests/test_descriptives.py` ≥30例，r 对已知线性数据=1，CI 随 n 收窄 |
| ✅ P5-2 | OLS 回归分析表 | **已落地** `psyclaw/psych/regression.py`：Gauss-Jordan 矩阵求逆、正规方程 OLS；B（非标准化）/β（标准化）/SE/t/p/95%CI 系数表；R²/调整R²/F检验（p）；`format_apa_regression_table`（APA-7 Markdown 三线表）；`format_apa_paragraph`（显著预测变量文字段落）；`write_regression_report` MD+JSON sidecar；`analyze_regression` CSV 主入口（完整案例过滤、缺失计数）；`psyclaw regress <data.csv> --dv <col> --iv col1,col2,... [--alpha] [--json] [--out]`；stdlib only；奇异矩阵抛 ValueError。测试 `tests/test_regression.py`（32 例）。 | `tests/test_regression.py` ≥25例，y=2x+1 精确恢复系数，标准化β公式正确 |
| ✅ P5-4 | 效应量转换器 | **已落地** `psyclaw/psych/effect_size.py`：d↔r（Cohen 1988）、d↔f（d=2f）、d↔eta²、f↔eta²、F→eta²、t→d（双/单样本）、chi²→phi/Cramér's V、OR↔d（Borenstein et al. 2009）；`interpret_d/r/eta2/f` Cohen (1988) 言语标签（4档）；`cohens_d_two_group`（合并 SD + Hedges' g + SE + 95%CI）、`cohens_d_one_sample`；`convert` 通用转换入口；`format_apa_effect_size` APA-7 段落；`psyclaw effect-size convert --from d --to r --value 0.5 | compute ... | interpret ...`；stdlib only。测试 `tests/test_effect_size.py`（51 例）。 | d↔r 互逆精确，d=0.5→r≈0.243，BH Hedges' g < d |
| ✅ P5-3 | 多重检验校正 | **已落地** `psyclaw/psych/multiple_testing.py`：`bonferroni`（阈值=α/m，调整p=min(p×m,1)）、`holm`（Holm 1979 逐步降低 FWER，调整p单调递增）、`benjamini_hochberg`（BH 1995 FDR，k×α/m 规则，调整p单调递增）；`format_apa_corrections`（APA-7段落+Markdown表格）；`write_corrections_report` MD+JSON sidecar；`analyze_corrections` CSV 主入口（p 值列批量校正）；`psyclaw correct-p <p1,p2,...\|--csv file> [--method bh\|holm\|bonferroni] [--alpha .05] [--json] [--out]`；stdlib only；BH 1995 论文 Table 1 示例验证（拒绝4项）。测试 `tests/test_multiple_testing.py`（35 例）。 | `tests/test_multiple_testing.py` ≥25例，BH 1995 Table 1 正确，拒绝数 BH≥Holm≥Bonferroni |
| ✅ P5-5 | 单因素 ANOVA | **已落地** `psyclaw/psych/anova.py`：`one_way_anova`（F/df/p/eta²/omega²/SS/MS/组描述统计，SS_b=0完全简并→F=0，SS_w=0完全分离→F=inf）、`post_hoc_pairwise`（Welch t+Holm校正+Cohen's d，C(k,2)对比）、`format_apa_anova`（APA-7 Markdown 三线表+段落）、`format_apa_post_hoc`、`write_anova_report` MD+JSON sidecar、`analyze_anova` CSV 主入口（缺失过滤+n_excluded计数+可选事后检验）；`psyclaw anova <data.csv> --dv <col> --group <col> [--post-hoc] [--alpha .05] [--json] [--out]`；stdlib only；omega² 下界截0防负值。测试 `tests/test_anova.py`（31 例）。 | `tests/test_anova.py` 31例全绿，F=50精确值边界正确，简并/分离两种极端均处理 |

---

## P6 · 统计纵深扩展（P5 完成后自我扩展）

| # | 任务 | 说明 | 验收 |
|---|------|------|------|
| ✅ P6-1 | 非参数检验套件 | **已落地** `psyclaw/psych/nonparametric.py`：`mann_whitney_u`（Wilcoxon 秩和，U1/U2/Z/r_effect）、`wilcoxon_signed_rank`（配对差值秩和，W+/W-/Z/r）、`kruskal_wallis`（多组非参数替代单因素 ANOVA，H/eta²_H/各组中位数+平均秩）、`spearman_rho`（秩相关，ρ/t/p）；正态近似（erfc）+ chi²近似（不完全伽马函数），stdlib only；`format_apa_nonpar` APA-7 段落；`write_nonpar_report` MD+JSON sidecar；`analyze_nonpar` CSV 主入口；`psyclaw nonpar <data.csv> --test mwu\|wilcoxon\|kruskal\|spearman --dv <col> [--group col] [--y col] [--alpha] [--json] [--out]`。测试 `tests/test_nonparametric.py`（47 例）。 | 47例全绿，ρ=1精确，U1+U2=n1×n2，W++W-=n(n+1)/2 |
| ✅ P6-2 | 双因素析因 ANOVA | **已落地** `psyclaw/psych/anova2.py`：`two_way_anova`（Type-I SS，主效应A/B+交互效应A×B/eta²/omega²/单元格均值表，F=0→p=1 特判）；`format_apa_anova2`（APA-7 ANOVA 汇总表+效应文字段落+单元格均值表）；`write_anova2_report` MD+JSON sidecar；`analyze_anova2` CSV 主入口；`psyclaw anova2 <data.csv> --dv <col> --factorA <col> --factorB <col> [--alpha] [--json] [--out]`；stdlib only；支持 2×2 至 m×n 均衡/非均衡设计；df_e=0 时报错。测试 `tests/test_anova2.py`（24 例）。 | SS 加和精确，交互效应显著检出，无效应 p>0.05 |
| ✅ P6-3 | 卡方检验套件 | **已落地** `psyclaw/psych/chisquare.py`：`chi2_goodness_of_fit`（拟合优度，效应量 w=√χ²/N，自动均匀期望/比例缩放）、`chi2_independence`（独立性，phi/Cramér's V/调整 V/期望频率表/小期望警告）、`fisher_exact_2x2`（超几何精确双尾 p，OR）；`format_apa_chi2` APA-7 段落；`write_chi2_report` MD+JSON sidecar；`analyze_chi2` CSV 主入口（原始数据自动构建列联表）；`psyclaw chi2 <data.csv> --test gof\|independence\|fisher [--obs --exp --row-col --col-col --label --alpha --json --out]`；stdlib only。测试 `tests/test_chisquare.py`（40 例）。 | 40例全绿，χ²=0精确，完全关联 V>0.9，OR=16精确 |
| ✅ P6-4 | t 检验套件 | **已落地** `psyclaw/psych/ttest.py`：`ttest_one_sample`（单样本 t，Cohen's d + 95% CI）、`ttest_independent`（Welch/Student 独立样本 t，合并 d + CI，`--student` 切换等方差）、`ttest_paired`（配对 t，Cohen's dz + CI，差值均值 CI）；`format_apa_ttest` APA-7 段落（三类格式分支）；`write_ttest_report` MD+JSON sidecar；`analyze_ttest` CSV 主入口；`psyclaw ttest <data.csv> --dv <col> [--test independent\|paired\|one-sample] [--group col] [--y col] [--mu0 0] [--student] [--alpha] [--json] [--out]`；stdlib only（`_t_quantile` 二分法求临界值）。测试 `tests/test_ttest.py`（30 例）。 | 30例全绿，Welch df≤Student df，CI 包含 d，配对差值方差非零校验 |

---

## P7 · 统计纵深扩展 II（P6 完成后自我扩展）

| # | 任务 | 说明 | 验收 |
|---|------|------|------|
| ✅ P7-1 | 二元 Logistic 回归 | **已落地** `psyclaw/psych/logistic.py`：IRLS（Newton-Raphson 精确 Hessian）二元 Logistic 回归；Wald z/p/OR/95%CI；LR chi²/df/p；Cox-Snell R² + Nagelkerke R²；`_safe_exp` 防完全分离溢出；`hosmer_lemeshow`（g=10 分组，χ²(g-2)）拟合优度；`format_apa_logistic`（APA-7 Markdown 三线系数表 + 模型总结段落 + 显著预测变量文字 + HL 段落）；`write_logistic_report` MD+JSON sidecar；`analyze_logistic` CSV 主入口（0/1 校验 + 缺失排除）；`psyclaw logit <data.csv> --dv <col> --iv col1,col2,... [--alpha] [--no-hl] [--json] [--out]`。理论依据：Hosmer & Lemeshow (2000)；Nagelkerke (1991)。stdlib only。测试 `tests/test_logistic.py`（68 例）。 | `tests/test_logistic.py` ≥35例，OR=exp(B) 精确，Nagelkerke≥Cox-Snell，HL p∈[0,1] |

---

## P8 · 统计纵深扩展 III（P7 完成后自我扩展）

| # | 任务 | 说明 | 验收 |
|---|------|------|------|
| ✅ P8-1 | 探索性因子分析（EFA） | **已落地** `psyclaw/psych/efa.py`：循环 Jacobi 特征值分解（对称矩阵，60 sweep 收敛）；SMC 初始公因子方差（R⁻¹对角线）；主轴因子法（PAF，迭代共同度估计）+ PCA 可选；Kaiser Varimax 正交旋转（非规范化，最大化载荷⁴方差）；Kaiser 准则自动确定因子数（特征值 ≥ 1.0）；ASCII 碎石图；APA-7 Markdown 因子载荷三线表（低于阈值空白，≥.50 加粗）+ 段落；MD+JSON sidecar；`psyclaw efa <data.csv> --cols c1,c2,... [--n-factors N] [--rotation varimax\|none] [--method paf\|pca] [--min-loading .30] [--json] [--out]`；CLI 注册 `cli.py`。理论依据：Harman (1976)；Kaiser (1958)；Cattell (1966)。stdlib only。测试 `tests/test_efa.py`（54 例）。 | `tests/test_efa.py` ≥35例，2因子结构正确检出，Varimax 旋转矩阵正交，SMC 随相关升高 |

---

## P9 · 统计纵深扩展 IV（P8 完成后自我扩展）

| # | 任务 | 说明 | 验收 |
|---|------|------|------|
| ✅ P9-1 | 两层随机截距混合线性模型（MLM/HLM） | **已落地** `psyclaw/psych/mlm.py`：EM 算法 ML 估计；GLS 固定效应（Gauss-Jordan）；BLUP 随机效应（后验均值/方差）；ICC = τ²/(τ²+σ²)；对数似然/AIC/BIC；`format_apa_mlm` APA-7 固定效应 Markdown 三线表 + 方差分量表 + 结果段落；`write_mlm_report` MD+JSON sidecar；`analyze_mlm` CSV 主入口；`psyclaw mlm <data.csv> --dv <col> --cluster <col> [--iv col1,...] [--alpha .05] [--max-iter 200] [--json] [--out]`；CLI 注册 `cli.py`；stdlib only。理论依据：Laird & Ware (1982)；Raudenbush & Bryk (2002)。测试 `tests/test_mlm.py`（65 例）。 | `tests/test_mlm.py` ≥50例，ICC∈[0,1]，AIC/BIC 公式精确，大效应 p<.05 |

---

## 建议的下一步执行顺序

1. ~~**P0-1 审稿模拟**~~ ✅ 已闭合「写作 → 评审 → 修复」回路（`psyclaw/review.py`）。
2. ~~**P0-2 一句话编排**~~ ✅ 四象限端到端流水线（`psyclaw/pipeline.py`,`psyclaw research`）。
3. ~~**P0-3 knowledge 抽取入综述**~~ ✅ `/lit --synthesize` 一键综述 + 流水线 ① 据 `/lit` 缓存合成有据综述（`psyclaw/psych/synthesize.py`）。
4. ~~**D-1 功效分析**~~ ✅ G*Power 对标的先验功效分析（`psyclaw power`，`psyclaw/psych/power.py`）。
5. ~~**D-2 预注册模板**~~ ✅ `/preregister` 据澄清卡产 OSF/AsPredicted 双格式，复用 D-1 功效（`psyclaw/psych/preregister.py`）。
6. ~~**A-1 检验决策树特判**~~ ✅ 六类特判落地(`psyclaw/psych/decision_tree.py`)。
7. ~~**R-4 REPL Markdown 渲染**~~ ✅ 整块缓冲 + Markdown→ANSI（`psyclaw/md_render.py`）→ ~~**R-1 prompt_toolkit REPL**~~ ✅ 三级降级（ptk→stdlib→input），`_slash_completions` 纯函数 + PromptSession 单例（`psyclaw/ui_input.py`） → **R-2 writing 复用 academic-research-skills** → **R-3 MCP 归属标注**（决策已定，优先于 P3）。
8. 其余 P1/P2/P3 按需排期。
