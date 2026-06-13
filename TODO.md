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
| M-2 | 子量表自动信度 | 计分后自动跑各子量表信度（α / ω） | `reliability.py` |
| M-3 | 测量不变性序列 | 跨组比较前强制 configural → metric → scalar 不变性检验；不成立则阻止潜均值比较，建议部分不变性 | `r_backend.py`，新门禁 `MEASURE.invariance` |
| M-4 | 自定义量表 | 用户量表 YAML 放 `.psyclaw/scales/`，与内置库合并 | loader 合并逻辑 |
| M-5 | 草率作答扩展指标 | psychsyn/psychant 语义一致性、Mahalanobis D、作答时间（Q{N}E）、假词法（infrequency items） | `careless.py` |

### 2. 设计层

| # | 任务 | 说明 | 关联门禁 |
|---|------|------|----------|
| ✅ D-1 | 功效分析预设 | 对标 G*Power：t / ANOVA / 相关回归 / 中介（Monte Carlo）/ SEM（MacCallum RMSEA）；先验默认 r≈.20 / d≈.40，提示发表偏倚高估 | **已落地** `psyclaw/psych/power.py`：纯 stdlib 非中心 t（积分）/F/χ²（Poisson 级数）核 + 六类检验功效与样本量反解（双向）；`psyclaw power <ttest\|anova\|r\|regression\|sem\|mediation> [-n N \| --power .80] [--json]`，保守先验默认 + 发表偏倚告警。无 scipy 环境下用闭式自检 + G*Power/Cohen 锚点 + 双路径互证验证。测试 `tests/test_power.py`（31 例） | `DESIGN.power` |
| ✅ D-2 | 预注册模板 | `/preregister` 生成 OSF / AsPredicted 双格式，自动抽取假设（确证/探索）、IV/DV/协变量、剔除规则、样本量依据、分析计划 | **已落地** `psyclaw/psych/preregister.py`：读 `notes/clarification.md`（17 槽位）→ OSF 6 节标准模板 + AsPredicted 标准 8 问双文稿（`notes/preregistration_{osf,aspredicted}.md`）。假设按确证/探索自动归类，未标注 **fail-closed 按探索性**并告警（防 HARKing）；关键槽位缺失渲染 `[待补充]` 占位+告警，不替用户编造；`--test` 复用 D-1 `power.compute` 嵌入确定性样本量依据（保留发表偏倚告警）。`psyclaw preregister [--osf\|--aspredicted] [--test … 功效参数]`（REPL `/preregister`）。测试 `tests/test_preregister.py`（21 例） |
| D-3 | 伦理提示 | 敏感测量（如 PHQ-9 条目 9 自伤意念）触发 IRB / 危机转介提示，量表库 `notes` 为触发源 | 新增软门禁 |

### 3. 分析层

| # | 任务 | 说明 | 关联门禁 |
|---|------|------|----------|
| ✅ A-1 | 心理学检验决策树特判 | 嵌套数据强制 MLM + 报 ICC；Likert 单题默认有序处理；大样本「显著但效应可忽略」自动改用效应量语言；中介默认 bootstrap CI(5000)，拒 Sobel；调节报简单斜率 + Johnson-Neyman；SEM 全拟合指数 | **已落地** `psyclaw/psych/decision_tree.py`：`detect_likert` / `large_sample_effect_language` / `compute_icc` / `bootstrap_mediation` / `moderation_analysis`；集成到 `analyze.py` (Likert/ICC/大样本自动检测)；新命令 `psyclaw mediation` / `psyclaw moderation`，`psyclaw stat --cluster`。测试 `tests/test_decision_tree.py`（35 例） |
| A-2 | 多重比较 / 研究者自由度 | 分析前声明计划写入 `notes/plan.md`；偏离即触发审计记录；探索性分析强制标注 + 建议 split-half 验证 | `STAT.no_phack` |

### 4. 写作层（`psyclaw/output/`）

| # | 任务 | 说明 |
|---|------|------|
| W-1 | JARS 检查单 | 按研究类型挂 JARS-Quant / Qual / Mixed；缺项（缺失数据处理、剔除人数与理由）阻断 |
| W-2 | 统计结果 APA7 格式器深化 | 斜体统计量、两位小数、`p < .001` 规则、效应量符号、三线表；扩展现有 `apa7.py` |
| W-3 | 中文心理学语境 | 中文版量表常模进量表库扩展字段；《心理学报》/《心理科学》格式 vs APA 切换；中英双语模板（评估复用 academic-research-skills 双语摘要能力） |

---

## P2 · 工程化与生态

| # | 任务 | 说明 |
|---|------|------|
| E-1 | 图表主题层 | `psyclaw.figures` 统一主题（matplotlib rcParams + seaborn + ggplot 对照），所有子技能出图走同一入口；落实 `figure_style.yaml` 的 APA7/nature/frontiers 预设与诚实性门禁（y 轴归零、误差棒标注） |
| E-2 | 商业统计软件 MCP | SPSS（已有 `spss_server.py` 雏形）/ Mplus / Stata 完整 MCP；先定接口契约，实现可后置 |
| E-3 | MCP registry 完善 | `config` 向导逐项启用 + 健康检查 + 能力探测；`doctor` 全绿 |

---

## ❓ 开放问题（需先决策，来自 DESIGN §8）

1. **REPL 库选型**：`prompt_toolkit`（功能全）vs `rich.prompt`（轻）vs 维持当前 stdlib 双实现（零依赖）？
2. **ARS 子技能组织**：独立 SKILL.md vs 单文件多 section？当前为独立子技能 + ARS 总编排。
3. **复用 academic-research-skills 插件**作为 writing 子技能后端，避免重造？（M2 曾建议评估，至今未定）
4. **商业统计软件 MCP 归属**：谁实现/维护？接口契约先行。

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
7. 其余 P1/P2 按需排期。
