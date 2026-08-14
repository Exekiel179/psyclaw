# 社会科学智能体 100 个具体多轮测评案例

这份题库把能力索引转成可执行案例。每个案例都应配套固定 fixture、同一 prompt、同一预算和同一验收器；模型只能改变答案，不能改变输入和验收规范。

## 有效性硬门槛

本文件只收录需要智能体编排能力的任务。每个案例必须满足：

1. `min_model_turns >= 2`：至少一次规划/判断，至少一次工具结果回灌后的继续决策；
2. 至少调用一个真实工具，并产生工具回执；
3. 至少包含两项：依赖传递、失败恢复、产物验收、学术规范或人工审批；
4. 需要保存、下载、分析、导出或写作交接的任务，必须验证真实产物；
5. 只有“一次回答问题”“一次写 Markdown”“一次格式转换”的案例一律废弃，不计入 100 项得分。

因此，表中的“写报告”不是单轮写作题，而是“读取上游证据→选择结构/方法→调用工具落盘→读取/验收→修订或交接”的多轮任务。

## 固定案例格式

每个案例至少包含：`case_id`、`prompt`、`fixture`、`expected_tools`、`expected_artifacts`、`checks`、`fatal_gates`。除特别说明外，所有案例都检查真实工具回执、RunState、路径安全和无虚报完成。

额外必填字段：`min_model_turns: 2`、`min_tool_calls: 1`、`requires_verification: true`、`recovery_case: true|false`。

## 100 个案例

### 研究问题与理论

| ID | 具体任务 prompt | 固定 fixture | 期望证据/产物 | 通过标准 |
|---|---|---|---|---|
| SS01 | “我想研究大学生刷短视频。请把它改成可执行研究问题。” | `fixtures/ss01_brief.md`：某校拟研究短视频与睡眠 | `outputs/research_question.md` | 主问题+3子问题；对象、暴露、结局、时间明确 |
| SS02 | “从‘2024 年某市青年就业调查’简介提取研究对象、分析单位和场域。” | `fixtures/ss02_project.md` | `outputs/scope.json` | 人/家庭/城市层级不混淆，时间地点完整 |
| SS03 | “把‘了解远程办公影响’拆成描述、解释、预测三个目标。” | `fixtures/ss03_aims.md` | `outputs/aims.md` | 三种目标各 1 个，说明不可互换 |
| SS04 | “为孤独感、社交媒体使用、抑郁症状写概念和操作定义。” | `fixtures/ss04_constructs.csv` | `outputs/operational_definitions.csv` | 每个构念有量表/单位/测量层级 |
| SS05 | “根据‘睡眠影响考试成绩’画 DAG，加入压力和家庭社会经济地位。” | `fixtures/ss05_theory.md` | `outputs/theory_dag.md` | 方向、混杂、中介标注正确 |
| SS06 | “论文声称社区花园提高幸福感，请列出至少 3 个竞争解释。” | `fixtures/ss06_claim.md` | `outputs/alternative_explanations.md` | 自选择、社区资源、反向因果均出现 |
| SS07 | “把‘同伴支持提高课堂参与’改成可证伪假设。” | `fixtures/ss07_variables.json` | `outputs/hypotheses.md` | 含方向、群体、时间和反例 |
| SS08 | “预算 2 万元、8 周、只能访问一所学校，检查研究是否可行。” | `fixtures/ss08_constraints.md` | `outputs/feasibility_check.md` | 样本、时间、测量、伦理逐项给出结论 |
| SS09 | “把‘检索文献、分析 survey.csv、写方法’拆成有依赖工作流。” | `fixtures/ss09_survey.csv` | RunState + `outputs/workflow_plan.json` | 3 节点依赖和停止条件完整 |
| SS10 | “我想研究‘年轻人更焦虑’。先提出阻塞性澄清问题；读取 `fixtures/ss10_answer.md` 中的用户补充后，更新研究范围并保存。” | `fixtures/ss10_ambiguous.md` + `fixtures/ss10_answer.md` | `read_file`; `save_file`; RunState; `outputs/scope_after_clarification.json` | 第一轮只问总体/时间/测量；第二轮复用回答，不重复提问并完成范围产物 |

### 文献检索与证据发现

| ID | 具体任务 prompt | 固定 fixture | 期望证据/产物 | 通过标准 |
|---|---|---|---|---|
| SS11 | “为‘远程办公与工作满意度’写 OpenAlex/Crossref 检索式，限定 2020–2025。” | `fixtures/ss11_pico.md` | `outputs/search_strategy.json` | 同义词、字段、年份和布尔式可复跑 |
| SS12 | “检索‘社会孤立与老年抑郁’，最多 10 条，保留 DOI。” | `fixtures/ss12_query.txt` | `notes/lit_search.json` | 多源记录、查询、时间、去重数齐全 |
| SS13 | “从给定 20 条题录中保留 2019–2024、英文、纵向研究。” | `fixtures/ss13_records.json` | `outputs/filtered_records.json` | 过滤规则和排除数可核验 |
| SS14 | “合并 Crossref 与 OpenAlex 的 12 条重复题录。” | `fixtures/ss14_sources.json` | `outputs/deduplicated_records.json` | DOI 优先去重，保留 source 列 |
| SS15 | “把 8 条 RIS 转成统一 CSV。” | `fixtures/ss15_refs.ris` | `outputs/normalized_records.csv` | 作者、年份、标题、DOI 字段无错位 |
| SS16 | “依据检索日志生成 PRISMA 计数。” | `fixtures/ss16_search_log.json` | `outputs/prisma_counts.json` | 识别=24、去重=20、筛选=12、纳入=5 自洽 |
| SS17 | “按‘必须有成人样本和抑郁结局’初筛 10 条题录并写理由。” | `fixtures/ss17_records.json` | `outputs/screening.csv` | 每条 include/exclude 和理由 |
| SS18 | “根据 5 篇纳入研究判断睡眠干预的证据空白。” | `fixtures/ss18_included.json` | `outputs/evidence_gaps.md` | 空白引用具体研究，标检索边界 |
| SS19 | “以 DOI 10.1000/seed 为种子做前向/后向滚雪球。” | `fixtures/ss19_seed.json` | `outputs/snowball.json` | 方向、来源、去重和失败记录 |
| SS20 | “EuropePMC 不可用时完成同一检索并说明降级。” | `fixtures/ss20_disabled_source.json` | RunState + failure log | 不宣称全库覆盖，列替代源和人工下一步 |

### 获取、阅读与引用

| ID | 具体任务 prompt | 固定 fixture | 期望证据/产物 | 通过标准 |
|---|---|---|---|---|
| SS21 | “下载 DOI 10.1000/oa 的开放 PDF，并核验是 PDF。” | `fixtures/ss21_oa.json` | `outputs/pdfs/oa.pdf` | 下载回执、PDF 魔数、非空 |
| SS22 | “DOI 10.1000/paywall 撞付费墙，请给合法下一步。” | `fixtures/ss22_paywall.json` | handoff record | 不绕过权限，给机构/Zotero/浏览器路径 |
| SS23 | “从附带 PDF 提取研究设计、样本和主要结局并带页码。” | `fixtures/ss23_article.pdf` | `outputs/extractions/design.json` | 每项字段有页码或段落证据 |
| SS24 | “从三篇文章提取样本量、年龄范围、纳排标准。” | `fixtures/ss24_articles/` | `outputs/study_characteristics.csv` | 数值与原文一致，缺失写 NA |
| SS25 | “比较三篇文章使用的 UCLA 孤独量表版本和信度。” | `fixtures/ss25_articles/` | `outputs/measurement_matrix.csv` | 版本、范围、alpha 来源齐全 |
| SS26 | “从结果表提取每项效应量、CI、样本量。” | `fixtures/ss26_results.pdf` | `outputs/effect_extraction.csv` | 单位和统计量类型不混淆 |
| SS27 | “为 6 篇文章生成摘要卡片。” | `fixtures/ss27_articles.json` | `outputs/literature_cards.json` | 问题、设计、结果、局限、引用键齐全 |
| SS28 | “把‘认知行为疗法降低失眠’与文献证据逐条对齐。” | `fixtures/ss28_claims.json` | `outputs/claim_evidence_map.json` | 支持/不支持/待核状态准确 |
| SS29 | “按 APA7 为 10 条已核验 DOI 生成 BibTeX。” | `fixtures/ss29_refs.json` | `outputs/references.bib` | 不编造作者、年份、DOI |
| SS30 | “审计正文中的 12 个引用和文末 15 条参考文献。” | `fixtures/ss30_manuscript.md` | `outputs/citation_audit.json` | 双向匹配，3 条未引用项单列 |

### 设计与伦理

| ID | 具体任务 prompt | 固定 fixture | 期望证据/产物 | 通过标准 |
|---|---|---|---|---|
| SS31 | “研究一次性测量的社交媒体与孤独感，推荐设计并说明不能因果化。” | `fixtures/ss31_question.md` | `outputs/design_recommendation.md` | 横断面局限和替代设计明确 |
| SS32 | “为 8 周正念课程设计 RCT protocol。” | `fixtures/ss32_intervention.md` | `outputs/rct_protocol.md` | 随机、对照、主要结局、盲法/注册 |
| SS33 | “评估 2023 年地铁开通对通勤满意度的影响。” | `fixtures/ss33_policy_timeline.csv` | `outputs/quasi_experiment.md` | DID/平行趋势和反事实说明 |
| SS34 | “为 5000 名社区居民抽取 400 人问卷样本。” | `fixtures/ss34_population.md` | `outputs/sampling_plan.md` | 抽样框、分层、权重、非应答 |
| SS35 | “为照护者压力研究写 12 人访谈提纲。” | `fixtures/ss35_brief.md` | `outputs/interview_protocol.md` | 招募、问题、饱和、退出机制 |
| SS36 | “先做问卷再访谈解释异常结果，写混合方法方案。” | `fixtures/ss36_design.md` | `outputs/mixed_methods_plan.md` | 时序和整合点明确 |
| SS37 | “检测 d=0.30 的两组差异，alpha=.05、power=.80，估样本量。” | `fixtures/ss37_power.json` | `outputs/power_analysis.*` | 参数、单双侧、脱落敏感性 |
| SS38 | “审查收集未成年人网络使用数据的伦理风险。” | `fixtures/ss38_protocol.md` | `outputs/ethics_risk_register.csv` | 同意、隐私、伤害、升级路径 |
| SS39 | “为匿名在线问卷写知情同意检查表。” | `fixtures/ss39_survey.md` | `outputs/consent_checklist.md` | 自愿、退出、用途、联系人 |
| SS40 | “检查一份预注册：结果已出来但作者想改主要结局。” | `fixtures/ss40_preregistration.md` | `outputs/preregistration_audit.md` | 阻止事后改写，分探索/确认 |

### 数据治理与清理

| ID | 具体任务 prompt | 固定 fixture | 期望证据/产物 | 通过标准 |
|---|---|---|---|---|
| SS41 | “检查 survey.csv 与 data_dictionary.xlsx 是否一致。” | `fixtures/ss41/` | `outputs/data_dictionary_audit.json` | 变量、类型、单位、缺失码逐项 |
| SS42 | “画像 100 行、8 列的青年就业 CSV。” | `fixtures/ss42/youth.csv` | `outputs/profile.json` | n、缺失、重复、范围和类型 |
| SS43 | “找出 participant_id 重复记录，不要自动删除。” | `fixtures/ss43/duplicate.csv` | `outputs/duplicates.csv` | 保留原行、重复键和计数 |
| SS44 | “按预注册规则识别收入 z>3 的异常值。” | `fixtures/ss44/income.csv` | `outputs/outlier_report.json` | 只标记，不删除，不改规则 |
| SS45 | “分析 PHQ9 缺失是否与组别相关并提出处理方案。” | `fixtures/ss45/missing.csv` | `outputs/missingness_report.json` | 缺失比例、机制假设、敏感性 |
| SS46 | “将性别 male/female/unknown 编码并保留原值。” | `fixtures/ss46/gender.csv` | `outputs/recoding_log.csv` | 映射可逆、unknown 不变成缺失 |
| SS47 | “按 participant_id 合并问卷和行为日志。” | `fixtures/ss47/` | `outputs/merged_dataset.csv` + log | 行数变化、未匹配、冲突审计 |
| SS48 | “去除身份证号和手机号，保留分析所需年龄段。” | `fixtures/ss48/sensitive.csv` | `outputs/deidentified.csv` + log | 原敏感值不进入输出 |
| SS49 | “为清理后的数据建立 SHA256 manifest。” | `fixtures/ss49/data.csv` | `outputs/data_manifest.json` | 哈希、时间、版本、来源 |
| SS50 | “检查项目目录是否含 .env、token.json 或 raw 个资。” | `fixtures/ss50_project/` | `outputs/gates/privacy.json` | 能发现并拒绝打包敏感文件 |

### 定量统计

| ID | 具体任务 prompt | 固定 fixture | 期望证据/产物 | 通过标准 |
|---|---|---|---|---|
| SS51 | “根据两组 score 和研究问题选择检验。” | `fixtures/ss51/two_group.csv` | `outputs/analysis_plan.json` | t 检验/非参备选与假设 |
| SS52 | “生成 8 名被试反应时的描述统计。” | `fixtures/ss52/rt.csv` | `outputs/descriptives.csv` | n、均值、SD、中位数、IQR |
| SS53 | “比较干预组和对照组 PHQ9，报告 d 和 95% CI。” | `fixtures/ss53/phq9.csv` | `outputs/ttest.json` | 差异、CI、d、方向正确 |
| SS54 | “比较 low/mid/high 三组满意度并做校正事后比较。” | `fixtures/ss54/three_groups.csv` | `outputs/anova.json` | F、效应量、CI、校正 |
| SS55 | “计算睡眠时长与压力的相关及 CI。” | `fixtures/ss55/sleep_stress.csv` | `outputs/correlation.csv` | r、CI、n、缺失和非因果措辞 |
| SS56 | “用年龄、收入预测幸福感，写回归结果。” | `fixtures/ss56/happiness.csv` | `outputs/regression.json` | 系数、CI、拟合、诊断 |
| SS57 | “预测是否失业的 Logistic 模型。” | `fixtures/ss57/employment.csv` | `outputs/glm_results.json` | OR、CI、基线类别、校准 |
| SS58 | “检验社会支持是否调节失业与抑郁关系。” | `fixtures/ss58/moderation.csv` | `outputs/mediation_moderation.json` | 交互项、简单斜率、边界 |
| SS59 | “对 30 人三次测量的压力做混合模型。” | `fixtures/ss59/repeated.csv` | `outputs/multilevel_results.json` | 随机效应、收敛、时间效应 |
| SS60 | “审计一篇报告中 20 个 p 值是否做多重比较控制。” | `fixtures/ss60/results.md` | `outputs/multiplicity_audit.md` | 所有检验列出，拒绝选择性报告 |

### 质性与文本

| ID | 具体任务 prompt | 固定 fixture | 期望证据/产物 | 通过标准 |
|---|---|---|---|---|
| SS61 | “为 20 条照护者访谈建立初始 codebook。” | `fixtures/ss61/transcripts.txt` | `outputs/codebook.md` | 定义、例子、排除规则 |
| SS62 | “根据两名研究者试编码修订 codebook v2。” | `fixtures/ss62/coding_pilot.csv` | `outputs/pilot_coding.csv` | 修订原因和版本差异 |
| SS63 | “计算两位编码者对 50 段文本的一致性。” | `fixtures/ss63/coders.csv` | `outputs/intercoder_agreement.json` | 指标、分母、冲突处理 |
| SS64 | “从已编码访谈归纳住房压力主题。” | `fixtures/ss64/coded_quotes.json` | `outputs/themes.md` | 主题有多条证据和反例 |
| SS65 | “重建某政策从提案到实施的事件时间线。” | `fixtures/ss65/events.csv` | `outputs/process_trace.csv` | 日期、来源、因果谨慎 |
| SS66 | “分析 30 篇新闻中的‘移民’框架。” | `fixtures/ss66/news.json` | `outputs/discourse_analysis.md` | 语料边界、编码和位置性 |
| SS67 | “用 80 条已标注评论做训练/测试分类。” | `fixtures/ss67/comments.csv` | `outputs/classification_metrics.json` | 分离数据，precision/recall/F1 |
| SS68 | “对 100 条政策文本做探索性主题分析。” | `fixtures/ss68/policy_texts/` | `outputs/topic_model_report.md` | 主题不当作真实变量，报告不确定性 |
| SS69 | “检查质性报告引语是否暴露受访者身份。” | `fixtures/ss69/report.md` | `outputs/quote_privacy_audit.json` | 标记组合身份线索，不回显敏感原文 |
| SS70 | “审计三条质性结论是否都有原始引语支持。” | `fixtures/ss70/claims.json` | `outputs/qualitative_audit.md` | 支持、反例、饱和状态逐条 |

### 图表、解释与复现

| ID | 具体任务 prompt | 固定 fixture | 期望证据/产物 | 通过标准 |
|---|---|---|---|---|
| SS71 | “为两组分布、缺失和异常值各选一张图。” | `fixtures/ss71/profile.json` | `outputs/figure_plan.json` | 图形与变量类型匹配 |
| SS72 | “画八名被试反应时箱线图。” | `fixtures/ss72/rt.csv` | `outputs/figures/rt_boxplot.png` | 标签、单位、n、来源 |
| SS73 | “根据五项研究画随机效应森林图。” | `fixtures/ss73/effects.csv` | `outputs/figures/forest.png` | CI、权重、零线和模型 |
| SS74 | “画收入×教育交互的边际效应图。” | `fixtures/ss74/model.json` | `outputs/figures/marginal.png` | 预测范围、CI、图例 |
| SS75 | “审查一张红绿配色的政策图是否可访问。” | `fixtures/ss75/figure.png` | `outputs/figure_accessibility.md` | 色盲、对比度、文字替代 |
| SS76 | “从回归 JSON 写 300 字结果段落。” | `fixtures/ss76/regression.json` | `outputs/results_narrative.md` | 数字一致，不能把相关写成因果 |
| SS77 | “解释 d=0.18 是否具有实际意义。” | `fixtures/ss77/effect.json` | `outputs/practical_significance.md` | 区分统计/实际重要和不确定性 |
| SS78 | “为本项目生成可重跑 Python 分析脚本。” | `fixtures/ss78/analysis_plan.json` | `outputs/analysis_script.py` | 输入、依赖、seed、输出完整 |
| SS79 | “运行脚本两次并比较输出哈希。” | `fixtures/ss79/` | `outputs/reproducibility_check.json` | 一致或解释随机差异 |
| SS80 | “为数据、脚本、图表生成 manifest。” | `fixtures/ss80/project/` | `outputs/analysis_manifest.json` | 文件哈希和版本完整 |

### 写作与同行审查

| ID | 具体任务 prompt | 固定 fixture | 期望证据/产物 | 通过标准 |
|---|---|---|---|---|
| SS81 | “根据研究问题和三张结果表写论文大纲。” | `fixtures/ss81/` | `outputs/manuscript_outline.md` | 论点—证据顺序清晰 |
| SS82 | “根据 protocol 和脚本写方法部分。” | `fixtures/ss82/` | `outputs/methods.md` | 他人可复现样本、变量、模型 |
| SS83 | “根据结果表写结果，不添加未检验结论。” | `fixtures/ss83/results.json` | `outputs/results.md` | 数字与表一致，措辞克制 |
| SS84 | “写讨论：贡献、限制、替代解释和外推边界。” | `fixtures/ss84/` | `outputs/discussion.md` | 不把观察研究写成干预证据 |
| SS85 | “将 1200 字稿件压成结构化摘要。” | `fixtures/ss85/manuscript.md` | `outputs/abstract.md` | 目的、方法、结果、限制、结论 |
| SS86 | “把失业研究结果写成给市政府的政策简报。” | `fixtures/ss86/` | `outputs/policy_brief.md` | 建议强度与证据强度相符 |
| SS87 | “按目标期刊模板整理稿件和参考文献。” | `fixtures/ss87/` | `outputs/submission/` | 格式清单逐项通过 |
| SS88 | “模拟审稿：重点检查因果、统计和透明度。” | `fixtures/ss88/manuscript.md` | `outputs/review_report.md` | 严重/一般问题分级且有定位 |
| SS89 | “根据 8 条审稿意见修订，并保留 diff。” | `fixtures/ss89/` | `outputs/revision/` | 逐条回应，未擅自新增结果 |
| SS90 | “生成给编辑的逐条回复信。” | `fixtures/ss90/reviewer_comments.md` | `outputs/response_letter.md` | 每条意见有回应和页码定位 |

### 质量、合规与交付

| ID | 具体任务 prompt | 固定 fixture | 期望证据/产物 | 通过标准 |
|---|---|---|---|---|
| SS91 | “审查结果稿是否报告效应量和 95% CI。” | `fixtures/ss91/results.md` | `outputs/gates/statistics.json` | 缺失项 fail-closed |
| SS92 | “核验正文中 10 条关键主张的引用是否真的支持。” | `fixtures/ss92/claims_refs/` | `outputs/gates/citations.json` | 逐条支持/不支持/待核 |
| SS93 | “根据项目实际资产写 Data Availability 声明。” | `fixtures/ss93/manifest.json` | `outputs/data_availability.md` | 不虚构公开仓库或 DOI |
| SS94 | “扫描交付目录中的密钥、手机号和内部 URL。” | `fixtures/ss94/delivery/` | `outputs/gates/privacy.json` | 发现并隔离敏感文件 |
| SS95 | “审查结果是否存在 p-hacking、选择性报告或伪造。” | `fixtures/ss95/audit_bundle/` | `outputs/gates/integrity.json` | 证据、风险、整改步骤完整 |
| SS96 | “生成让新成员接手的项目交接包。” | `fixtures/ss96/project/` | `outputs/handoff/` | README、清单、入口、依赖、未决项 |
| SS97 | “写出从新环境重跑该分析的命令和排错路径。” | `fixtures/ss97/` | `outputs/reproduce.md` | 命令可执行，失败点可诊断 |
| SS98 | “完成检索→下载→分析→写方法→质检连续链。” | `fixtures/ss98/brief.md` + 题录/CSV | RunState + 交接包 | 每节点通过，证据正确传递，失败不虚报 |
| SS99 | “用两个模型跑 SS53、SS82、SS98，比较质量和成本。” | `fixtures/ss99/benchmark.yaml` | `outputs/benchmark.json` | 输入、预算、规范相同，指标齐全 |
| SS100 | “基于全部案例生成版本判定。” | `fixtures/ss100/eval_report.json` | `outputs/release_verdict.json` | 总分和关键维度达标才可交付 |

## 多轮有效性检查器

每个案例的自动检查器至少执行以下断言：

```python
assert result["model_turns"] >= 2
assert result["successful_tool_calls"] >= 1
assert result["verification_passed"] is True
assert result["run_state_receipts"] >= result["successful_tool_calls"]
```

对于连续任务，再检查依赖任务的回执是否出现在下游 prompt/RunState 中；对于失败恢复任务，检查第一次失败后没有重复执行不可重放副作用。

## 评测执行顺序

1. 先运行当前离线回归，记录基线；
2. 建立 SS01–SS10 的 fixture 和检查器，验证任务格式；
3. 按组依次接入 SS11–SS20、SS21–SS40、SS41–SS70、SS71–SS90；
4. 最后运行连续链 SS98、多模型 SS99 和发布门槛 SS100；
5. 每个案例保存原始 prompt、模型配置、RunState、工具回执、产物哈希和 verdict。
