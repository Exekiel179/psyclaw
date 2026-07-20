# PsyClaw 心理学专属优化设计 v0.1

> 通用科研 agent 与心理学专用 agent 的差距,全在这份文档里。
> 状态标注:✅ M1 已落地(可运行) · 📋 已设计待实现(M2+)

---

## 1. 测量层(心理学数据的第一性问题:测的准不准)

### 1.1 量表注册表 ✅

`psyclaw/psych/scales.yaml` 收录常用量表的条目映射、计分、反向题、信度参考、已知坑:

- 已收录:DASS-42 / DASS-21 / PHQ-9 / GAD-7 / TIPI / RSES / PSS-10
- 每个量表带 `notes` 字段记录陷阱(如 DASS 在线版 1-4 计分 vs 纸质版 0-3;
  TIPI 两题/维度 α 注定偏低,应报重测信度)
- CLI:`psyclaw scale` 列出、`psyclaw scale dass-42` 查详情;REPL 内 `/scale`
- 📋 M2:ARS-Stat 据此自动计分(含反向题翻转)、自动跑子量表信度
- 📋 M3:支持用户自定义量表 YAML 放进项目 `.psyclaw/scales/`,与内置库合并

### 1.2 草率作答筛查 ✅

`psyclaw/psych/careless.py`,纯 stdlib 实现三个标准指标:

| 指标 | 含义 | 默认阈值 |
|------|------|----------|
| longstring | 最长连续相同作答(Johnson, 2005) | ≥ max(8, 条目数/3) |
| straightline | 众数作答占比 | ≥ 95% |
| IRV | 个体内作答标准差(Dunn et al., 2018) | < 0.3 |

- CLI:`psyclaw screen data.csv`(自动嗅探 tab/逗号分隔;默认匹配
  OpenPsychometrics 的 Q{N}A 列名,`--prefix/--suffix` 可调)
- **原则:标记 ≠ 剔除**。剔除决定必须走 HITL 审批门(`decision_request.md`),
  由新质量检查 `DATA.careless` 强制
- 📋 M2 扩展:psychsyn/psychant(语义一致性)、Mahalanobis D、作答时间
  (利用 Q{N}E 列)、假词法(VCL6/9/12 类 infrequency items)

### 1.3 信度 ✅

`psyclaw/psych/reliability.py`:Cronbach's α + 逐题删除 α + 解释规则
(含「α>.95 提示冗余」)。新质量检查 `MEASURE.reliability`:合成量表分前必报信度。
📋 M2 接 R 后默认双报 α + McDonald's ω,并跑 CFA 检验单维性假设。

### 1.4 测量不变性 📋

跨组比较(性别/年龄/文化)前,ARS-Stat 强制走
configural → metric → scalar 不变性检验序列(lavaan/Mplus),
不变性不成立则阻止潜均值比较并建议部分不变性方案。

---

## 2. 设计层(心理学实验的方法学债)

### 2.1 功效分析预设 📋

`/design` 内置心理学常见设计的功效分析模板(对标 G*Power):
t 检验族 / ANOVA 族 / 相关回归 / 中介(Monte Carlo)/ SEM(MacCallum RMSEA 法)。
默认假设从心理学元分析现实出发:**效应量先验默认 r≈.20 / d≈.40(而非教科书的"中等")**,
并提示发表偏倚导致文献效应量普遍高估。

### 2.2 预注册模板 📋

`/preregister` 生成 OSF / AsPredicted 双格式模板,自动从对话中抽取:
假设(区分确证/探索)、IV/DV/协变量、剔除规则(引用 §1.2 的筛查标准)、
样本量依据(引用 §2.1 的功效分析)、分析计划。对应质量检查 `DESIGN.prereg`。

### 2.3 伦理提示 📋

涉敏感测量(PHQ-9 条目 9 自伤意念等,量表注册表 `notes` 已标)时,
自动提示 IRB/伦理审查与危机转介流程要求。量表库是触发源。

---

## 3. 分析层(心理学统计的特殊性)

### 3.0 前提假设知识库 + 可运行诊断 ✅(M2 前半场已落地)

**知识库**(`psych/assumptions.json`,`psyclaw assume <id>`):16 个检验族,
每条假设带「怎么检查 → 违反了怎么办」,含现代默认做法:

- 经典族:t-ind / t-paired / anova-oneway / anova-rm / anova-mixed / correlation /
  regression / ancova / chisq
- 进阶族:mediation / mlm / efa / cfa-sem / irt / lpa-lca / network
- 内置方法学立场:Welch 默认、bootstrap 中介、HC3 稳健 SE、
  横断中介必须声明局限、ANCOVA 的 Lord's paradox 警告、RM-ANOVA→MLM 迁移建议

**可运行诊断**(`psych/diagnostics.py`,`psyclaw check data.csv --dv 分数 --group 组别`,纯 stdlib):

| 输出 | 实现 |
|------|------|
| 分组描述统计 | n/M/SD/Mdn/range |
| 正态性 | 偏度/峰度 + z 检验(自实现正态分布;大样本自动提示看经验线) |
| 方差齐性 | Brown-Forsythe Levene(中位数中心化,稳健) |
| 组间检验 | 经典 F + Welch F 并排输出(p 值经自实现正则化不完全 Beta,对照 F 分布表校准误差 <.0005) |
| 效应量 | η²(CI 待 ARS-Stat) |

**复杂方法目录**(`psych/methods.json`,`psyclaw method <id>`):13 个方法卡——
CFA / SEM / 双因子(ωH/ECV 判据) / 测量不变性 / MLM / IRT-GRM / LPA / 网络分析 /
CLPM+RI-CLPM / LGCM / 调节 / 元分析 / 贝叶斯 / 等价检验(TOST),
每卡含何时用、样本量、软件路径、报告标准、常见坑。

**实验设计目录**(`psych/designs.json`,`psyclaw design <id>`):12 个设计卡——
被试间/内/混合/析因/RCT 前后测/所罗门/准实验/纵向面板/ESM 日记法/单被试/
刺激抽样(交叉随机效应),每卡含效度威胁、抵消平衡、功效要点、分析映射
(直接链回 assume/method 条目),外加操纵与效度通用清单。

### 3.1 心理学检验决策树 📋(ARS-Stat 核心,M2 后半场)

通用决策树之外的心理学特判:

- **嵌套数据警觉**:被试嵌套于班级/团队/重复测量 → 强制考虑多层模型,
  报告 ICC,ICC>.05 仍用 OLS 需说明理由
- **量表分≠连续**:Likert 单题默认有序处理(ordinal logistic / 多分类 IRT);
  合成分才按连续
- **大样本警告**(你 DASS 案例 N=39,775 的教训):p 值几乎必显著,
  自动改以效应量+CI 为主要证据语言,critic 检查「显著但效应可忽略」的过度解读
- **中介调节规范**:中介默认 bootstrap CI(5000 次),不接受 Sobel;
  调节报告简单斜率+Johnson-Neyman 区间
- **SEM 拟合报告**:χ²/df、CFI、TLI、RMSEA(90% CI)、SRMR 全报,
  禁止只挑好看的指标(对应 STAT.no_phack)

### 3.2 多重比较与研究者自由度 📋

分析前声明分析计划(写入 `notes/plan.md`),实际执行偏离计划即触发
`STAT.no_phack` 审计记录;探索性分析明确标注并建议留出验证集
(大样本可 split-half:探索半样本生成假设,验证半样本检验)。

---

## 4. 写作层(APA 的细节地狱)

### 4.1 JARS 检查单 📋

按研究类型挂接 APA JARS 对应模块:JARS-Quant(实验/相关)、
JARS-Qual(质性)、JARS-Mixed。`/write` 产出前按检查单逐项核对,
缺项(如未报缺失数据处理、未报剔除人数与理由)阻断。

### 4.2 统计结果 APA7 格式化 📋

统一格式器:斜体统计量、两位小数、p 的报告规则(p < .001 而非 p = .000)、
效应量符号、表格三线表。中英双语模板(对接 academic-research-skills 的
bilingual abstract 能力,M2 评估复用)。

### 4.3 中文心理学语境 📋

- 量表中文版信息(如 DASS-21 中文版常模文献)进量表注册表扩展字段
- 投稿格式预设:《心理学报》/《心理科学》格式 vs APA 期刊格式切换

---

## 5. 质量检查追加(M1 已落地 ✅)

| Gate | 触发 | 规则 |
|------|------|------|
| `DATA.careless` | 数据筛查 | 必须跑草率作答筛查;剔除须人工批准 |
| `MEASURE.reliability` | 使用量表分 | 合成前必报信度 |

加上原有 9 条,当前共 **11 条质量检查**。

---

## 6. REPL 系统提示注入 ✅

REPL 每次对话注入:PSYCLAW.md 全文 + ARS SKILL.md + 心理学统计行为准则
(效应量优先、相关≠因果、区分探索/确证、大样本警觉)。
即使在 M2 工具链就位前,纯对话也已是"心理学方法论上靠谱"的助手。
