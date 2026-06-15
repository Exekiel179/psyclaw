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

## P0.5 · Bug / 体验修复（2026-06-15 实跑发现）

| # | 任务 | 说明 | 验收 | 文件 |
|---|------|------|------|------|
| ✅ BUG-1 | `--help` 崩溃 | **已修复** `psyclaw/cli.py`：`partial-corr`（行 1794）与 `roc`（行 1839）的 subparser `help=` 文本含裸 `95% CI` → argparse 把 `% C` 当 `%C` 格式符，顶层 `--help` 展开短 help 时崩 `ValueError: unsupported format character 'C'`。两处转义为 `95%% CI`（与已转义的行 1497 一致）。新增 `tests/test_cli_help.py`（约 8 例）：遍历所有 subparser 调 `format_help()`/`format_usage()` 不抛错 + 直接断言无裸 `%`（`h.replace("%%","").count("%")==0`）防回归。 | `psyclaw/cli.py` |
| ✅ UX-1 | REPL 方向键/历史失效 | **已修复** `psyclaw/ui_input.py`：新增 `_fallback_input(prompt)`——裸 `input()` 兜底前惰性 `import readline`（POSIX stdlib，导入一次即全局挂接 `builtins.input`，方向键移动光标 + ↑↓ 翻会话历史 + Ctrl-A/E/K 键位生效），结果缓存 `_readline_ready`（None/True/False 三态，不重复 import）；无 readline（Windows 等）或任何异常 try/except 静默降级为纯 `input()`，绝不阻断脚本化调用。`read_line` 两处裸 `input(prompt).strip()`（非 TTY 路径 + 交互降级路径）均改走 `_fallback_input`。新增 `tests/test_repl_ptk.py::TestFallbackReadline`（7 例）：惰性 import 仅一次 / strip / 缺失 readline 降级 / 缓存 False 不重试 / 非 TTY 与交互异常两路均路由经 `_fallback_input`。 | `psyclaw/ui_input.py` |

> 注：`nostop.sh` 在 macOS 自带 bash 3.2 + `set -u` 下失败分支崩溃的问题已在 `bf1b1c5` 修复（去 `set -u`、紧跟管道取退出码、MAX_TURNS 80→150），此处不再列。

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
| ✅ R-5 | 对话读取本地文件路径（**用户实测痛点，最优先**） | **已落地** `psyclaw/path_ingest.py`：`extract_paths`（正则检测 Unix/Windows/引号/相对/~展开路径，只返回磁盘实际存在的文件）、`classify`（data/text/unknown 三类）、`_data_metadata`（CSV/TSV 结构元数据，不含原始数据行，守住隐私铁律）、`process_message`（路由主入口：数据文件注入元数据+统计命令提示，文本文件走 `smart_excerpt`，缺失已知后缀文件友好报错）；`repl.py` `ask()` 方法集成：每轮自动检测路径→注入上下文→原文发 LLM；57 例测试 `tests/test_path_ingest.py`。 | `tests/test_path_ingest.py` ≥25例，csv 路由到元数据而非原始数据，文本走摘录，缺失文件报错，原文件未修改 |

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

---

## P10 · 统计纵深扩展 V（P9 完成后自我扩展）

| # | 任务 | 说明 | 验收 |
|---|------|------|------|
| ✅ P10-1 | 层级多元回归（Hierarchical OLS） | **已落地** `psyclaw/psych/hierarchical_regression.py`：分块逐步纳入预测变量（每块继承前块全部 IV + 新增变量）；ΔR²、ΔF 变化量检验（`F = (ΔR²/df_ch)/((1-R²)/df_res)`）；各块 R²/调整 R²/F/p 整体显著；最终块完整系数表（B/β/SE/t/p/95%CI）；`format_apa_hierarchical_table`（APA-7 Markdown 三线分块汇总表）+ `format_apa_coefficients_table` + `format_apa_hierarchical_paragraph`（含步骤描述 + 显著预测变量文字）；`write_hierarchical_report` MD+JSON sidecar；`analyze_hierarchical` CSV 主入口；`psyclaw hreg <data.csv> --dv <col> --block1 c1,c2 [--block2 c3 --block3 c4,c5 ...] [--alpha] [--json] [--out]`；CLI 注册 `cli.py`；stdlib only。理论依据：Cohen, Cohen, West & Aiken (2003)。测试 `tests/test_hierarchical_regression.py`（50 例）。 | `tests/test_hierarchical_regression.py` ≥35例，ΔF 公式精确，ΔR² 累加等于最终 R² |

---

## P11 · 统计纵深扩展 VI（P10 完成后自我扩展）

| # | 任务 | 说明 | 验收 |
|---|------|------|------|
| ✅ P11-1 | 重复测量单因素 ANOVA | **已落地** `psyclaw/psych/rm_anova.py`：Mauchly 球形检验（W/χ²/df/p，Helmert 正交归一对比矩阵，k=2 自动成立）；Greenhouse-Geisser ε + Huynh-Feldt ε（违反球形性时 ε_GG≥.75 报 HF 否则报 GG，APA 建议）；SS 分解（SS_between/SS_subjects/SS_error）；F 检验（未校正 + GG/HF 校正 df）；partial η² / ω²（Olejnik & Algina, 2003）；成对配对 t 检验 Holm 校正事后检验；APA-7 Markdown 三线表 + 结果段落；MD+JSON sidecar；`psyclaw rm-anova <data.csv> --dv <col> --subject <col> --within <col> [--alpha] [--post-hoc] [--json] [--out]`；CLI 注册 `cli.py`；stdlib only。理论依据：Greenhouse & Geisser (1959)；Huynh & Feldt (1976)；Mauchly (1940)；Maxwell, Delaney & Kelley (2017)。测试 `tests/test_rm_anova.py`（78 例）。 | `tests/test_rm_anova.py` ≥50例，SS 分解正确，GG/HF ε 在有效范围，Mauchly df 公式正确 |

---

---

## P12 · 统计纵深扩展 VII（P11 完成后自我扩展）

| # | 任务 | 说明 | 验收 |
|---|------|------|------|
| ✅ P12-1 | 协方差分析（ANCOVA） | **已落地** `psyclaw/psych/ancova.py`：Type-III SS（两次 OLS 对比）；GLM 哑变量编码（treatment coding，首组参照）；同质性回归斜率检验（group×cov 交互，k-1 df）；估计边际均值 EMM（协变量总体均值处的 GLM 预测）+ SE + 95% CI；偏 partial η² / partial ω²（Olejnik & Algina 2003）；事后成对 t 检验（GLM 对比向量，Holm 校正）；多协变量支持（Type-III SS 逐一剔除）；APA-7 ANOVA 汇总表 + 调整均值表 + 文字段落 + MD/JSON sidecar；`psyclaw ancova <data.csv> --dv <col> --group <col> --cov cov1[,cov2] [--post-hoc] [--alpha] [--json] [--out]`；CLI 注册 `cli.py`；stdlib only。理论依据：Maxwell et al. (2017)；Olejnik & Algina (2003)；Milliken & Johnson (2009)。测试 `tests/test_ancova.py`（69 例）。 | `tests/test_ancova.py` ≥35例，调整均值差精确，df_error=N-k-p，CI 包含均值 |

---

---

## P13 · 统计纵深扩展 VIII（P12 完成后自我扩展）

| # | 任务 | 说明 | 验收 |
|---|------|------|------|
| ✅ P13-1 | 混合 ANOVA（between × within） | **已落地** `psyclaw/psych/mixed_anova.py`：一个被试间因素 × 一个被试内因素 Split-plot ANOVA；标准 SS 分解（SS_A/SS_S(A)/SS_B/SS_AB/SS_BS(A)）+ 可加性验证；F_A=MS_A/MS_S(A)，F_B=F_AB=MS/MS_BS(A)；Mauchly 球形检验（W/χ²/p）+ GG/HF ε 校正（被试内及交互效应 df）；partial η²（Lakens 2013）+ partial ω²（Olejnik & Algina 2003）；`simple_effects_within`（各 between 水平上被试内简单主效应，配对 t + Holm 校正）；`format_apa_mixed`（单元格均值表 / Mauchly 段 / ANOVA 汇总表 / APA-7 文字段落 / 参考文献）；`write_mixed_report` MD+JSON sidecar（NaN/inf→null）；`analyze_mixed` CSV 主入口（完整案例筛选 + 非均衡警告）；`psyclaw mixed-anova <data.csv> --dv <col> --between <col> --within <col> --subject <col> [--post-hoc] [--alpha] [--json] [--out]`；CLI 注册 `cli.py`；stdlib only。理论依据：Kirk (2013)；Maxwell et al. (2017)；Olejnik & Algina (2003)；Greenhouse & Geisser (1959)；Huynh & Feldt (1976)。测试 `tests/test_mixed_anova.py`（70 例）。 | `tests/test_mixed_anova.py` ≥50例，SS 加和等于 SS_total，df 公式正确，手算已知值误差<1e-8 |

---

## P14 · 统计纵深扩展 IX（自我扩展）

| # | 任务 | 说明 | 验收 |
|---|------|------|------|
| ✅ P14-1 | 偏相关 / 半偏相关 / 偏相关矩阵 | **已落地** `psyclaw/psych/partial_corr.py`：回归残差法偏相关 `r_xy.controls`（OLS 残差 → Pearson r，控制任意个协变量，k=0 退化为 Pearson）；半偏相关 `semipartial_correlation`（仅对 x 或 y 去除控制影响，which=x/y）；偏相关矩阵 `partial_correlation_matrix`（同一协变量集对所有变量对，上三角对称填充，对角 r=1）；统计：t=r√df/√(1−r²)、双尾 p（不完全 Beta）、df=n−2−k、Fisher z 95% CI（SE=1/√(n−k−3)，Olkin & Finn 1995）；矩阵奇异（多重共线）报错；`format_apa_partial_corr`（文字段落 + 汇总表 + 参考文献）/ `format_apa_partial_matrix`（三线表 *** /** /* 显著性标注）；`write_partial_corr_report` MD+JSON sidecar（NaN/inf→null）；`analyze_partial_corr` CSV 主入口（缺失行排除 + n_excluded + 可选矩阵）；`psyclaw partial-corr <data.csv> --x <col> --y <col> [--controls c1,c2] [--semi] [--which x\|y] [--matrix c1,c2,...] [--alpha] [--json] [--out]`；CLI 注册 `cli.py`；stdlib only。理论依据：Cohen, Cohen, West & Aiken (2003)；Olkin & Finn (1995)。测试 `tests/test_partial_corr.py`（55 例）。 | `tests/test_partial_corr.py` ≥40例，k=0 等于 Pearson r，代数公式 r_xy.z 误差<1e-5，df=n−2−k，CI 含 r，奇异矩阵报错 |

---

## P15 · 统计纵深扩展 X（自我扩展）

| # | 任务 | 说明 | 验收 |
|---|------|------|------|
| ✅ P15-1 | 评分者间信度（Cohen's / Fleiss' κ + ICC） | **已落地** `psyclaw/psych/irr.py`（stdlib only，填补观察编码/内容分析一致性空白；此前仅有 Cronbach's α）：`cohens_kappa`（两评分者，名义 + 线性/二次有序加权；κ=(pₒ−pₑ)/(1−pₑ)；Fleiss-Cohen-Everitt 1969 渐近方差→Wald z/p + 95% CI；名义/加权统一方差路径，对 2×2 手算 SE 校验 0.127）；`fleiss_kappa`（多评分者名义，N×k 计数矩阵；Pᵢ 对象一致度 + 类别比例 + 渐近 z/p；`ratings_to_fleiss_counts` 标签表→计数转换）；`intraclass_correlation`（Shrout & Fleiss 1979 六模型 ICC(1/2/3,1/k)；双向 ANOVA 均方分解 MSR/MSC/MSE/MSW；F 检验 + McGraw & Wong 1996 95% CI；金标准数据手算校验 ICC(1,1)=.166/ICC(2,1)=.290/ICC(3,1)=.715）；`interpret_kappa`（Landis & Koch 1977）/ `interpret_icc`（Koo & Li 2016）；F 分布 CDF（不完全 Beta）+ 二分法求逆分位数；`format_apa_kappa` / `format_apa_icc`（APA-7 三线表 + 文字段落 + 参考文献）；`write_irr_report` MD+JSON sidecar（NaN/inf→null）；`analyze_irr` CSV 主入口（kappa/fleiss/icc 三路由 + 缺失排除）；`psyclaw irr <data.csv> --method kappa\|fleiss\|icc [--rater-a col --rater-b col] [--raters c1,c2,...] [--weights linear\|quadratic] [--alpha] [--json] [--out]`；CLI 注册 `cli.py`。理论依据：Cohen (1960, 1968)；Fleiss (1971)；Fleiss, Cohen & Everitt (1969)；Shrout & Fleiss (1979)；McGraw & Wong (1996)；Landis & Koch (1977)；Koo & Li (2016)。测试 `tests/test_irr.py`（约 110 例）。 | `tests/test_irr.py` ≥60例，Cohen κ=0.40 手算精确，ICC 对 Shrout & Fleiss 1979 金标准误差<.005，Fleiss κ=1/3 手算精确，加权 κ 对 2 类等于未加权 |

---

## P16 · 统计纵深扩展 XI（自我扩展）

| # | 任务 | 说明 | 验收 |
|---|------|------|------|
| ✅ P16-1 | ROC 曲线 / AUC 诊断准确性分析 | **已落地** `psyclaw/psych/roc.py`（stdlib only，填补量表筛查截断值验证空白；连续预测分 × 二元金标准结局）：`roc_auc`（AUC = Wilcoxon-Mann-Whitney 一致性法，秩排序 O(n log n) 含 .5 平局；Hanley & McNeil 1982 渐近 SE → Wald z/p 检验 H0:AUC=.5 + 正态 95% CI，完美分离 SE→0 特判）；`roc_curve`（全阈值 ROC 点：敏感度/特异度/FPR/Youden J，含 (0,0)(1,1) 端点，FPR 升序）；`optimal_cutoff`（Youden's J 最大化最优截断 + 该点敏感度/特异度/PPV/NPV/准确率/LR+/LR−/混淆矩阵）；`interpret_auc`（Hosmer, Lemeshow & Sturdivant 2013 五档，AUC<.5 对称反向）；`direction higher\|lower` 支持低分→阳性；正态 CDF(erf)/双尾 p/Acklam 分位数；`format_apa_roc`（AUC 汇总三线表 + 最优截断表 + 文字段落 + PPV/NPV 患病率告警 + 参考文献）；`write_roc_report` MD+JSON sidecar（NaN/inf→null）；`analyze_roc` CSV 主入口（positive_label 二值化 + 缺失/非数值排除 + n_excluded + 曲线点）；`psyclaw roc <data.csv> --score col --outcome col [--direction higher\|lower] [--positive 1] [--alpha] [--json] [--out]`；CLI 注册 `cli.py`。理论依据：Hanley & McNeil (1982)；Youden (1950)；Hosmer, Lemeshow & Sturdivant (2013)；DeLong et al. (1988)。测试 `tests/test_roc.py`（约 65 例）。 | `tests/test_roc.py` ≥40例，AUC 一致性法对手算金标准（pos=[2,3,4]/neg=[1,2] → 5.5/6）精确，完美分离 AUC=1 且 p=0，Youden 最优截断手算（cutoff=3, sens=2/3, spec=1）精确，AUC<.5 解读对称 |

---

## P17 · 统计纵深扩展 XII（自我扩展）

| # | 任务 | 说明 | 验收 |
|---|------|------|------|
| ✅ P17-1 | 相关系数差异检验（比较两个 *r*） | **已落地** `psyclaw/psych/compare_corr.py`（stdlib only，填补「两个相关系数是否显著不同」空白——此前仅能各自检验 *r*≠0，无法比较 *r*₁ vs *r*₂）：`compare_independent_corrs`（两独立样本，Fisher *z* 检验 + Zou 2007 MOVER 差异 CI）；`compare_dependent_overlapping`（同一样本、共享一个变量，*r*_jk vs *r*_jh：Williams 1959 *t* 检验 df=*n*−3 + Zou 2007 重叠 CI，估计量相关 c 由 Olkin 公式）；`compare_dependent_nonoverlapping`（同一样本、四个不同变量，*r*_jk vs *r*_hm：Steiger 1980 / Dunn & Clark 1969 *Z* 检验 + Zou 2007 非重叠 CI，协方差六相关式）；Fisher *z* CI 工具 `_fisher_z_ci`；正态 CDF(erf)/双尾 p/Acklam 分位数 + 不完全 Beta *t* 分布；`interpret_compare`（差异方向 + 显著性叙述）；`format_apa_compare_corr`（APA-7 三类分支文字段落 + 汇总表 + 参考文献）；`write_compare_corr_report` MD+JSON sidecar（NaN/inf→null）；`analyze_compare_corr` CSV 主入口（独立=按 group 二分计算各组 *r*(x,y)；重叠=列 x/y/z 计算 *r*_xy vs *r*_xz；非重叠=四列计算 *r*_ab vs *r*_cd + 四交叉相关；缺失排除 + n_excluded）；`compare_corr_cli`（支持 CSV 与手填 *r* 双模式）；`psyclaw compare-corr --kind independent\|overlapping\|nonoverlapping [data.csv ...\|手填 r/n]`；CLI 注册 `cli.py`。理论依据：Fisher (1921)；Williams (1959)；Steiger (1980)；Dunn & Clark (1969)；Zou (2007)。测试 `tests/test_compare_corr.py`（约 60 例）。 | `tests/test_compare_corr.py` ≥40例，独立 *r*₁=*r*₂→*z*=0/p=1，Fisher *z* 手算（*r*₁=.7/n=103, *r*₂=.5/n=103 → *z*≈2.249）精确，Williams 手算（*r*_jk=.6/*r*_jh=.4/*r*_kh=.5/n=103 → *t*≈2.486）精确，Steiger 全交叉=0 退化（*r*_jk=.5/*r*_hm=.2/n=103 → *Z*≈2.451）精确，相等相关→检验量=0/p=1，CI 含差值 |

---

## P18 · 统计纵深扩展 XIII（自我扩展）

| # | 任务 | 说明 | 验收 |
|---|------|------|------|
| ✅ P18-1 | 泊松回归（计数结局） | **已落地** `psyclaw/psych/poisson.py`（stdlib only，填补计数结局回归空白——心理学常见错误数/症状频次/攻击事件计数，此前只有 OLS/Logistic，无对数线性计数模型）：`poisson_regression`（IRLS = Newton-Raphson 精确 Hessian，对数连接 μ=exp(Xβ)，工作权重 w=μ）；Wald *z*/*p*/IRR(发生率比=exp(β))/95% CI；偏差 deviance + 零模型偏差 + LR χ² 检验；McFadden 伪 *R*²；AIC/BIC；**过度离散检测**（Pearson χ²/df 离散参数 φ，φ≳1.5 告警建议负二项/quasi-Poisson）；`_safe_exp` 防分离溢出；`format_apa_poisson`（APA-7 Markdown 三线系数表 *B*/SE/*z*/*p*/IRR/95%CI + 模型拟合段落 + 显著预测变量文字 + 过度离散告警）；`write_poisson_report` MD+JSON sidecar（NaN/inf→null）；`analyze_poisson` CSV 主入口（非负整数校验 + 缺失排除 + n_excluded）；`poisson_cli`；`psyclaw poisson <data.csv> --dv <col> --iv col1,col2,... [--alpha .05] [--json] [--out]`；CLI 注册 `cli.py`。理论依据：McCullagh & Nelder (1989) Generalized Linear Models；Cameron & Trivedi (2013) Regression Analysis of Count Data。测试 `tests/test_poisson.py`（约 55 例）。 | `tests/test_poisson.py` ≥35例，单二元预测变量饱和模型 β₀=log(ȳ₀)/β₁=log(ȳ₁/ȳ₀) 误差<1e-6，IRR=exp(B) 精确，偏差非负，LR χ²=null_dev−resid_dev，过度离散数据 φ>1 |

---

## P19 · 统计纵深扩展 XIV（自我扩展）

> **动机**：`poisson.py` 在 φ>1.5 时已显式建议改用负二项 / quasi-Poisson，但此前无实现。
> 心理学计数结局（症状频次、攻击事件、错误数等）几乎总是**过度离散**（Var > Mean），
> 泊松会低估 SE、夸大显著性。NB2 用色散参数 α（=1/θ）建模 Var(y)=μ+αμ²，θ→∞ 时退化为泊松。
> **核心增值**：α=0 的 LR 边界检验直接告诉用户「到底需不需要 NB」（泊松 vs NB 嵌套检验）。

| # | 任务 | 说明 | 验收 |
|---|------|------|------|
| ✅ P19-1 | 负二项回归（NB2，过度离散计数） | **已落地** `psyclaw/psych/negbin.py`（stdlib only，与 `poisson.py` 同构，复用其矩阵/分布工具模式）：`negbin_regression`——NB2 对数连接 GLM，**交替优化**（给定 θ 用 Fisher scoring 拟合 β：工作权重 W=θμ/(θ+μ)、score=Σx·θ(y−μ)/(θ+μ)；给定 μ 用黄金分割最大化 θ 条件对数似然）；色散参数 θ + α=1/θ + θ 的数值 SE（条件 ll 二阶差分）；Wald *z*/*p*/IRR=exp(β)/95% CI；NB 偏差 + 零模型 NB + LR χ² 检验；**α=0 边界 LR 检验**（泊松 vs NB，p=½·P(χ²₁>LR)，Cameron & Trivedi 2013）；McFadden 伪 *R*²（NB 基线）；AIC/BIC（参数计 k+1，含 θ）；`_nb_loglik`；`format_apa_negbin`（APA-7 三线系数表 + 模型拟合段 + θ/α 色散段 + 泊松-NB 检验段 + 显著预测变量文字）；`write_negbin_report` MD+JSON sidecar（NaN/inf→null）；`analyze_negbin` CSV 主入口（非负整数校验 + 缺失排除 + n_excluded）；`negbin_cli`；`psyclaw negbin <data.csv> --dv <col> --iv col1,col2,... [--alpha .05] [--json] [--out]`；CLI 注册 `cli.py`。理论依据：Cameron & Trivedi (2013) Regression Analysis of Count Data；Hilbe (2011) Negative Binomial Regression。测试 `tests/test_negbin.py`（≥45 例）。 | `tests/test_negbin.py` ≥40例，仅截距模型 exp(β₀)=ȳ 误差<1e-6，饱和二元模型 β₀=log(ȳ₀)/β₁=log(ȳ₁/ȳ₀)/IRR=ȳ₁/ȳ₀ 误差<1e-6（与 θ 无关），ll_NB≥ll_Poisson，α=0 LR≥0，过度离散数据 θ 有限且 α>0、α=0 检验显著，IRR=exp(B) 精确，偏差非负 |

---

## 建议的下一步执行顺序

1. ~~**P0-1 审稿模拟**~~ ✅ 已闭合「写作 → 评审 → 修复」回路（`psyclaw/review.py`）。
2. ~~**P0-2 一句话编排**~~ ✅ 四象限端到端流水线（`psyclaw/pipeline.py`,`psyclaw research`）。
3. ~~**P0-3 knowledge 抽取入综述**~~ ✅ `/lit --synthesize` 一键综述 + 流水线 ① 据 `/lit` 缓存合成有据综述（`psyclaw/psych/synthesize.py`）。
4. ~~**D-1 功效分析**~~ ✅ G*Power 对标的先验功效分析（`psyclaw power`，`psyclaw/psych/power.py`）。
5. ~~**D-2 预注册模板**~~ ✅ `/preregister` 据澄清卡产 OSF/AsPredicted 双格式，复用 D-1 功效（`psyclaw/psych/preregister.py`）。
6. ~~**A-1 检验决策树特判**~~ ✅ 六类特判落地(`psyclaw/psych/decision_tree.py`)。
7. ~~**R-4 REPL Markdown 渲染**~~ ✅ 整块缓冲 + Markdown→ANSI（`psyclaw/md_render.py`）→ ~~**R-1 prompt_toolkit REPL**~~ ✅ 三级降级（ptk→stdlib→input），`_slash_completions` 纯函数 + PromptSession 单例（`psyclaw/ui_input.py`） → **R-2 writing 复用 academic-research-skills** → **R-3 MCP 归属标注**（决策已定，优先于 P3）。
8. ~~**R-5 对话读取本地文件路径**~~ ✅ 路径自动检测（`psyclaw/path_ingest.py`）+ REPL 接线（`repl.py`）；57 例测试。
9. 其余 P1/P2/P3 按需排期。

---

## P5 · 正确性加固（自我扩展，2026-06-14 起）

| # | 任务 | 说明 | 验收 |
|---|------|------|------|
| ✅ P5-E6 | providers 单元测试 | **已落地** `tests/test_providers.py`：`MockProvider.chat`（迭代器/字符流/消息数/preview/长文本截断/VERDICT触发/无VERDICT/PSYCLAW注入/空消息/多轮/name属性 12例）、`Provider.describe`（无key/返回str/含name 3例）、`PRESETS`（必要provider/必要键/协议合法/mock无key_env/claude模型 5例）、`get_provider`（mock/空/model覆盖/无key回落mock/unknown回落mock 5例）；共25例。 | `tests/test_providers.py` ≥20例 |
| ✅ P5-E8 | stats_core.py 单元测试 | **已落地** `tests/test_stats_core.py`：`t_sf2`（零t→p=1/大t→小p/对称/df=0 NaN/大df趋正态/标准表df=30/值域 7例）、`chi2_sf`（x=0→1/x<0→1/大x小p/临界值df=1/df=3/值域 6例）、`norm_ppf`（中位数/1.96/对称/边界NaN/负/单调 7例）、`t_ppf`（大df近正态/df=30标准值/p<0.5负/df增大单调收敛 4例）、`welch_ttest`（键/显著/等组/d方向/符号翻转/CI含d/n正确 7例）、`student_ttest`（标签/df/显著/键 4例）、`paired_ttest`（显著/df=n-1/零差报错/dz正/CI键 5例）、`pearson_r`（r=1/r=-1/零方差错/df=n-2/n正确/值域/CI含r 7例）、`mann_whitney`（键/显著/p域/U非负/相同组p>0.5 5例）、`chisquare_independence`（独立χ²=0/关联显著/df公式/V域/N总数 5例）、`eta_squared`（同值/完全分离=1/值域 3例）、`bootstrap_ci`（2-tuple/下≤上/CI合理/固定种子可复现 4例）；共64例，对照教科书临界值（t=2.042 df=30，χ²=3.841 df=1）。 | `tests/test_stats_core.py` ≥40例 |
| ✅ P5-E7 | CFA 单元测试 | **已落地** `tests/test_cfa.py`：`_parse_model`（字符串/dict格式/标记变量/交叉载荷/未知变量/格式错误/空规格/单条目报错/空格容忍/单因子 12例）、`_corr_matrix`（对角/对称/值域/组内>组间/不足案例报错/n正确/NaN排除 7例）、`compute_cfa`（结构/fit键/维度/载荷矩阵形状/共同度范围/独特方差正/因子相关正交/fit值域/RMSEA-CI顺序/单因子/收敛标志/斜交对称/斜交对角 17例）、结构恢复精度（组内载荷>0.5/F2条目/标记恒等1.0/共同度合理/良好拟合/SRMR低 6例）、`format_apa_cfa`（返回str/CFI/TLI/RMSEA/SRMR/因子名/条目名/N/参考文献/斜交/单因子/警告节/表格/数值 14例）、`write_cfa_report`（MD/JSON/非空/JSON合法/无NaN/inf/创建目录 6例）、`analyze_cfa`（CSV读取/sidecar/return_json/文件不存在/斜交/max_iter 6例）、边界（未知列/最小条目/warnings列表/因子相关方阵/残差形状/Sigma形状/S对角1.0 7例）；共75例。 | `tests/test_cfa.py` ≥40例 |
| ✅ P5-E5 | bootstrap.py 单元测试 | **已落地** `tests/test_bootstrap.py`：`_has_module`（stdlib命中/不存在返回False/空串/psyclaw自身）、DEP_GROUPS/EXTERNAL_BINS 常量结构校验、`detect`（返回结构/所有键/have+missing互补=总数/ready一致性/reproducible）；20 例。 | `tests/test_bootstrap.py` ≥15例 |
| ✅ P5-E4 | ui.py 单元测试 | **已落地** `tests/test_ui.py`：`paint`（非TTY纯文本/TTY-ANSI/多样式/未知样式忽略）、语义函数（`ok`/`warn`/`err`/`accent`/`title`/`dim`/`rule`）双路径（disabled+enabled）、`panel`（含标题/内容/多行/结构/类型）、`term_width`（int/正数/上限100）、`banner`（含版本号/PsyClaw）；38 例。 | `tests/test_ui.py` ≥20例 |
| ✅ P5-E3 | embed.py 单元测试 | **已落地** `tests/test_embed.py`：`cosine`（同向1.0/正交0.0/反向-1.0/对称/不同长度/零向量）、`HashEmbedder._features`（英文token/CJK unigram+bigram/空/None/混排）、`HashEmbedder.encode`（dim=256/L2归一/确定性/不同文本不同向量/相似>不同/空文本不崩）、`_sha256`（known hash/空文件/不同内容/hex格式）、`local_model_dir`/`get_embedder(prefer='hash')`；40 例。 | `tests/test_embed.py` ≥25例 |
| ✅ P5-E2 | audit.py + memory.py 单元测试 | **已落地** `tests/test_audit_memory.py`：`parse_audit`（fail-closed 空/None/无 verdict/capped 100/最后一个 score/verdict wins/大小写容忍）、`render_verdict`（无分数标签/有分数/返回值类型）；三层记忆（`_decayed` 半衰期/极旧归零）、`suggest`（无数据/记录后命中/信度随次数升/极旧衰减）、`draft_lesson`（写入/去重）、`confirm_lesson`（激活/越界）、`active_lessons`（过滤/空）、`memory_prompt`（空/画像/教训卡）；fixture 将 MEM_DIR 重定向到 tmp_path 避免污染真实 ~/.psyclaw；48 例。 | `tests/test_audit_memory.py` ≥30例 |
| ✅ P5-E1 | context.py 单元测试 | **已落地** `tests/test_context.py`：`lean_core`（内容/可复现性）、`relevant_knowledge`（关键词命中/max_items 上限/中文别名/降级）、`compact_history`（阈值触发/recent-turns 保留/memo 累积/memo 长度上限）、`render_memo`（空/非空格式）、`_distill`（决策行抽取/角色标签/回退首行/截断）、`smart_excerpt`（大文件 head+tail/CSV 结构摘要/TSV/路径注入/错误降级）、`_is_num`（数值/非数值 parametrize）；57 例。 | `tests/test_context.py` ≥30例 |
| ✅ P5-E9 | diagnostics.py 单元测试 | **已落地** `tests/test_diagnostics.py`：`betai`（x=0/x=1/Uniform中点/对称ab/值域/单调/互补对称 7例）、`f_sf`（F=0/负F/教科书临界F(1,30)=4.171/F(1,60)=4.001/F(2,30)=3.316/大F小p/值域/单调/大df收敛chi² 10例）、`z_sf2`（z=0/1.96≈0.05/2.576≈0.01/3.291≈0.001/对称/值域/单调 7例）、`describe`（必须键/基本值/sd=2.0/偶数中位数/偏峰存在/小n无偏峰/零方差无偏峰/对称偏度≈0/右偏正值/p值域 12例）、`oneway_f`（必须键/df公式/等均值F=0/大效应显著/eta²值域/η²近1/p值域/零内部方差NaN/F正值 9例）、`welch_f`（必须键/df1公式/大效应显著/零效应F=0/零方差NaN/p值域/不等方差合法 7例）、`levene_bf`（必须键/等方差大p/不等方差小p/W非负/df1公式/p值域 6例）；共 58 例，全部对照教科书临界值验证（F(1,30)=4.171/F(2,30)=3.316/z=1.96/Beta互补恒等式）。 | `tests/test_diagnostics.py` ≥40例，教科书临界值误差<0.01，对称性/单调性不变量通过 |
| ✅ P5-E10 | reliability.py 单元测试 | **已落地** `tests/test_reliability.py`：`_variance`（空列表/单元素/全同值→0/已知值[3,5,7]→4.0/两元素/负数/返回float 7例）、`cronbach_alpha`（k=0 NaN/k=1 NaN/n=1 NaN/全常数 NaN/完全一致2题→1.0/完全一致3题→1.0/2题已知值→8/9/反向计分题负α/斜率方向/合理范围/返回float/Spearman-Brown 12例）、`alpha_if_deleted`（长度=k/索引1基/每元素2-tuple/索引int/值float/删反向题提高α/k=2删除→NaN/k=3返回合法float/顺序索引/与手动删除吻合 10例）、`interpret_alpha`（NaN→无法计算/0.95优/0.90优/0.89良/0.85良/0.80良/0.79可接受/0.70可接受/0.69勉强/0.60勉强/0.59差/0.0差/负值差/返回str/阈值下界/0.95冗余提示 16例）；共45例，数值对照手算（8/9 ≈ 0.8889，负α示例，[3,5,7]方差=4）。 | `tests/test_reliability.py` ≥30例，已知值手算误差 < 1e-9 |
