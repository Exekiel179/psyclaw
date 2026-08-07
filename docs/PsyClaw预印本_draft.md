# PsyClaw：面向社会科学研究的智能体助手

*把 Claude Code 的智能体范式引入研究流程，并内建学术诚信核查*

[作者一]<sup>1,2</sup>，[作者二]<sup>1,2</sup>，[通讯作者]<sup>1,2,\*</sup>

<sup>1</sup> [单位一]；<sup>2</sup> [单位二]
<sup>\*</sup> 通讯作者：[邮箱]

---

**摘要：** 近年来，以 Claude Code 为代表的智能体编程助手改变了软件工程的工作方式：它常驻终端、理解整个项目、以自然语言接受指令，并通过调用工具与执行命令真正地完成工作，而非仅作代码补全。本文提出 PsyClaw，把这一范式引入社会科学研究。它是一个开源的智能体研究助手：常驻终端、理解研究项目，以自然语言驱动文献检索、研究澄清与预注册、统计分析、论文写作与同行评审。正如 Claude Code 之于软件工程，PsyClaw 意在成为社会科学研究者的智能体助手。然而，研究与编程有一处根本不同：代码写得对不对，有编译器和测试来判定；研究做得规不规范，却缺一道现成的自动关卡。这正是 PsyClaw 的着力点——它在流程编排之外专设一层**学术诚信核查**：效应量与置信区间必报、区分探索与确证、确证研究须预注册、不把相关当因果、图件不得缺失等十四条规则，由机器逐条把关，产出一旦不合规就拦下并提示修改。Claude Code 靠测试与持续集成兜底，PsyClaw 就靠这层核查兜底，防止模型把存疑的分析包装成可信的结论。架构上，系统采用“四层加两横切”的可组合结构，并守一条铁律：**不自行实现任何统计**，统计一律交由 pingouin、statsmodels、SciPy 等成熟库或专用 MCP 后端（如 MNE-MCP）完成。本文介绍其设计与实现，报告 2228 项自动化测试全部通过，并以一个真实案例——一份草稿因插图缺失被核查当场拦下——印证这层把关的实效。PsyClaw 现阶段主要在心理学中打磨，但同一套核查与流程亦适用于其他定量社会科学，意在降低研究门槛，同时让成果更经得起复现与检验。

**关键词：** 智能体研究助手；社会科学；学术诚信；可复现性；大语言模型；Claude Code

---

**PsyClaw: An Agentic Assistant for Social-Science Research—Bringing the Claude Code Paradigm to the Research Workflow with Built-in Academic-Integrity Gates**

[Author One]<sup>1,2</sup>, [Author Two]<sup>1,2</sup> & [Corresponding Author]<sup>1,2,\*</sup>

<sup>1</sup> [Affiliation One]; <sup>2</sup> [Affiliation Two]

**Abstract:** Agentic coding assistants such as Claude Code have recently changed how software is built: they live in the terminal, understand the whole project, take natural-language instructions, and get real work done by calling tools and running commands rather than merely autocompleting code. This paper presents PsyClaw, which brings that paradigm to social-science research—an open-source agentic research assistant that likewise lives in the terminal, understands your research project, and drives the entire pipeline in natural language, from literature search, study clarification, and preregistration to statistical analysis, manuscript writing, and peer review. Research, however, differs from coding in one basic respect: whether code is correct is settled by compilers and tests, whereas whether research is sound has no such ready-made, automatic checkpoint. This is where PsyClaw concentrates. Alongside orchestration it adds a layer of academic-integrity checks—effect sizes and confidence intervals are mandatory, exploratory and confirmatory work must be kept apart, confirmatory studies must be preregistered, correlation is not passed off as causation, figures may not be missing, and so on, across fourteen machine-checkable rules—that vet each output and, whenever something is non-compliant, block it on the spot and suggest a fix. Where Claude Code relies on tests and continuous integration as its safety net, PsyClaw relies on this layer of checks, keeping the model from dressing up questionable analyses as trustworthy conclusions. Architecturally the system is organized as composable layers and holds to one rule: it computes no statistics itself, delegating all of them to mature libraries (pingouin, statsmodels, SciPy) or dedicated MCP backends such as MNE-MCP. We describe the design and its rationale, report that all 2228 automated tests pass, and use a real case—a manuscript draft blocked on the spot because a figure was missing—to show that the checks work in practice. PsyClaw is being refined primarily in psychology, yet the same checks and workflows carry over to other quantitative social sciences, with the aim of making research less laborious and more reproducible.

**Keywords:** Agentic research assistant; Social science; Academic integrity; Reproducibility; Large Language Model; Claude Code

---

## 1 引言

社会科学研究是一条环节众多、规范密集的长链条。一项典型的实证研究——无论出自心理学、教育学、传播学、社会学还是管理学——都需要研究者依次完成：文献检索与综述、研究问题澄清与假设界定、研究设计与功效分析、（视情况）预注册、数据采集与清洗、统计分析、结果可视化、论文撰写与投稿格式化、同行评审与修回。每一环都要求研究者同时具备方法学知识、软件操作能力与规范意识；任一环的疏漏都可能在最终结论中被放大。过去十余年，社会科学经历了严重的可复现性危机：对心理学已发表效应的大规模重复研究发现，仅约三分之一至半数能被稳健复现（Open Science Collaboration, 2015）；对发表于 *Nature* 与 *Science* 的社会科学实验的系统重复亦得到相近的结论（Camerer et al., 2018）。危机的根源之一是研究者自由度（researcher degrees of freedom）在缺乏约束时被系统性地滥用——包括未声明的多重比较、择优报告、事后假设伪装成事前（hypothesizing after the results are known, HARKing; Kerr, 1998），以及各类可疑研究实践（questionable research practices, QRPs），后者在匿名调查中被自我报告为相当普遍（John et al., 2012; Simmons et al., 2011）。为回应危机，学界确立了一系列规范：期刊论文报告标准（Journal Article Reporting Standards, JARS; Appelbaum et al., 2018）、"新统计学"对效应量与置信区间而非孤立 *p* 值的强调（Cumming, 2014）、系统综述的 PRISMA 流程（Page et al., 2021），以及预注册作为区分确证性与探索性研究的制度手段（Nosek et al., 2018）。然而，这些规范多以"研究者应当遵守"的形式存在，其执行仍高度依赖个人自律与评审者的事后把关。

与此同时，另一个领域正经历一场由智能体（agent）驱动的工作方式变革——软件工程。以 Anthropic 的 Claude Code 为代表的智能体编程助手（Anthropic, 2025），把大语言模型（Large Language Models, LLMs）从"代码补全"推进到"真正完成工作"：它常驻于终端，理解整个项目的上下文，以自然语言接受指令，并通过读写文件、执行命令、调用外部工具（经模型上下文协议接入）来实际推进任务；其对具有副作用的操作采用逐条审批、可回退的权限机制。这一范式的要义不在于"生成一段代码"，而在于把一个专业工作者的完整工作流——理解现状、规划、执行、验证——交由一个可对话、可审批、工具在手的智能体来编排。一个自然的问题是：这套已在软件工程中被验证的范式，能否同样服务于社会科学研究？

将现有的通用 LLM 数据工具直接用于研究，会暴露两项结构性缺口。其一是**编排缺口**。以 ChatGPT Code Interpreter（后更名 Advanced Data Analysis）为代表的通用数据分析范式，聚焦于"给定一份数据、产出一段分析"（Rahman et al., 2025; Hong et al., 2024）；而社会科学研究是一条跨阶段、有前后依赖的流程：文献要先于设计、设计要先于数据、分析结论要回流到写作、写作又要接受评审。通用范式难以把这些环节串成一条状态连续、可复现、可审计的工作流，更难以把"这一步做之前必须先完成上一步"的方法学约束显式地表达出来。其二是**规范缺口**，也是更为要害的一点。软件工程中，代码的对错由编译器、测试与持续集成客观裁决；而研究背负着软件所没有的正确性与规范要求，且 LLM 恰恰倾向于以自信、流畅的措辞给出结论。当模型被用于选择检验方法、剔除异常值、解释显著性或撰写结果段落时，它可能在无人审查的情况下，把一个存疑的分析自由度"洗白"成看似权威的表述——把相关当作因果、把大样本下的微小显著当作重要、把探索性发现表述为确证、或在报告中悄然省略未通过的检验。这正是自动化偏误（automation bias）在科研场景中的具体表现：越是流畅的自动化输出，越容易被不加审查地采纳。

模型上下文协议（Model Context Protocol, MCP）是 Anthropic 于 2024 年发布的开放标准，采用客户端—服务器架构，定义了工具（Tools）、资源（Resources）与提示词（Prompts）三类能力，使 LLM 应用能以标准化方式接入外部工具与数据源（Anthropic, 2024）。MCP 生态已经孕育出面向特定科研领域的服务器，例如将神经电生理分析平台 MNE-Python 接入 AI 编程助手的 MNE-MCP（Xue et al., 2025）。这类服务器出色地解决了"把一个专业工具交给智能体"的问题，但从整条研究链条来看，统计分析仍只是其中一环——它的上游是文献与设计，下游是写作与评审，而把这些环节编排为一条守规矩的可复现流程，尚缺一个专门的编排框架层。

本文提出 **PsyClaw**：把 Claude Code 所代表的智能体范式引入社会科学研究。它是一个开源的智能体研究助手，常驻终端、理解研究项目，以自然语言驱动文献、澄清、分析、写作与评审。正如 Claude Code 之于软件工程，PsyClaw 意在成为社会科学研究者的智能体助手。但针对上述规范缺口，PsyClaw 做了一项关键的加法：**在流程编排之上内建一层贯穿全程、失败即阻断的学术诚信核查**——如果说 Claude Code 以测试、类型检查与持续集成为护栏，那么 PsyClaw 就以效应量必报、探索确证之分、预注册、相关非因果、图件完整性等学术诚信核查为护栏。为坚守"编排"而非"重造轮子"的定位，PsyClaw 秉持一条铁律：**自身不实现任何统计算法**，一切统计计算外移至成熟库（pingouin、statsmodels、SciPy）或专用 MCP 后端（如上述 MNE-MCP）。系统围绕三项核心设计展开：声明式的研究流程定义、失败即阻断的学术诚信核查，以及统计外移的分层委托。需要说明的是，PsyClaw 以心理学为主要试验场（其内置的期刊画像与 JARS 检查根植于此），但其核查与流程可推广至定量社会科学的诸多分支。本文给出关键实现细节、验证结果、局限分析与使用建议，并以宽松许可证开源发布，便于复用与扩展。

## 2 设计与原理

### 2.1 为什么这样分层

PsyClaw 的设计出发点是一个判断：研究流程之所以难以交给通用工具，是因为它同时要求两件常相拉扯的事——既要"听得懂人话、能自主推进"，又要"步步可复现、处处守规范"。太偏前者，就成了一个流畅却难以复现、也不守规范的黑箱；太偏后者，又退回成僵硬的脚本，失去了自然语言协作的意义。为同时容纳这两种诉求，PsyClaw 把职责分成四层，再用两条横切贯穿其间（见图 1）。

四层自上而下，各回答一个问题。**路由层（L0）**回答"以什么方式介入"：研究者可以只是对话（`chat`，随需而动），可以指定一条明确、可复现的流程（`run`），也可以让系统感知项目状态、自主推进（`auto`）。**流程层（L1）**回答"一类研究该怎么走"：每一类研究被写成一份声明式的步骤清单，而不是一段写死的脚本，因而既能被完整复现，也能被重新拼装。**子功能层（L2）**回答"每一步能否独立成立"：每个步骤既能单独当一条命令用、能拆出来单独测试，也能拼进别的流程——同一份能力，多种用法。**实现层（L3）**回答"活到底由谁干"：真正的计算不由 PsyClaw 亲自完成，而是委托给外部的成熟工具。

两条横切则回答"如何始终守住底线"。其一是**核查**：每一步动手之前先过一道前置检查，不合规就当场拦下；整条流程跑完，还留下一份机器可读的总验收。其二是**记忆**：研究者的方法学偏好、目标期刊的惯例、过往的教训被沉淀下来并贯穿始终，使系统在多次交互中保持一致的前提。这套分层的意义不在于工程上的整洁，而在于把"自主"与"守规矩"这两种看似矛盾的诉求，各自安放在了合适的位置上。

![图 1　PsyClaw 的四层加两横切架构与数据流](../figures/psyclaw_fig1_architecture.png)

**图 1**　PsyClaw 的四层加两横切架构与数据流。研究者以自然语言经三入口（chat/run/auto）进入；L0–L3 自上而下逐层委托、结果与证据回流；Harness 横切（左）为每层附加失败即阻断的前置检查，Memory 横切（右）以三层记忆贯穿全程；统计计算整体外移至 L3 之下的成熟库与 MCP 后端，本仓不实现任何统计算法。

### 2.2 核心设计理念：声明式流程、失败即阻断的核查、统计外移

社会科学研究流程与无状态、一次性的代码执行范式存在本质差异，这决定了 PsyClaw 的三项设计取向。

**第一，声明式的研究流程。** 一个流程是"数据"而非"脚本"——它只声明"要走哪几步、每步动手前要满足什么前提"，具体怎么执行交给统一的引擎。以文献综述为例，它就是"研究准备检查 → 文献检索 → 筛选 → 结构化合成 → 同行评审"这样一串带前提的步骤。引擎对每一步的处理是固定的：先验前提，不满足就当场拦下；再执行；再记录产物与可恢复的检查点；必要时在步间征求人工确认；最后给出一份机器可读的总验收。这样做的好处不在于代码优雅，而在于研究流程因此变成可被完整重放、也可被自由重组的对象——同一份分析，别人能照着复算，自己也能改几步复用。

**第二，把学术规范做成不可绕过的核查。** 这是 PsyClaw 区别于通用 LLM 数据分析方案的核心。学术规范——效应量、探索确证之分、预注册、相关与因果之别——历来以"研究者应当遵守"的形式存在，执行全靠自律。PsyClaw 把这些要求凝练成一份规范：它既写给人看，也作为系统提示注入模型，让模型在生成阶段就受约束；同时把其中可机器判定的部分做成一张规则表，在每个产出点强制核查。核查默认"不合规即拦下"：不达标时不是给个警告然后放行，而是拦住产出、要求修复（详见 2.4 节）。用意很简单——把"该不该这么做、报告是否合规"从依赖自律的软约束，变成流程内绕不过去的硬约束。

**第三，统计外移的分层委托。** PsyClaw 秉持一条明确的铁律：**不在本仓实现任何统计算法**（分布函数、参数估计、各类检验、因子分析、生存分析等一概不写）。需要统计时，一律委托给 L3 的成熟库或 MCP 后端。这一取舍有三重理由：其一，成熟统计库经过长期社区检验，其数值正确性远非一个编排工具重新实现所能企及；其二，把统计留在外部，使 PsyClaw 的职责边界清晰——它只负责"编排得对不对、报告合不合规"，而非"数值算得准不准"；其三，同一份外部后端既可被智能体在多步推理中直接调用，也可被声明式流程在分析步中委托，两条路径落到同一实现，避免重复。作为两处样板，元分析流程生成委托 statsmodels 的脚本（随机效应 DerSimonian–Laird 估计、*I*²/*τ*²/*Q* 异质性、Egger 检验；DerSimonian & Laird, 1986; Egger et al., 1997），实证分析流程据数据画像推荐分析（*t* 检验、方差分析、相关、回归、描述统计）并生成委托 pingouin 与 SciPy 的脚本（Vallat, 2018; Virtanen et al., 2020）——**仓内不计算任何一个统计量**（见图 2）。

![图 2　三项核心设计理念在一个流程步骤上的协同](../figures/psyclaw_fig2_principles.png)

**图 2**　三项核心设计理念在一个流程步骤上的协同。声明式流程定义并驱动每个步骤（①）；步骤执行前经失败即阻断的核查把关，通过则放行、不过则阻断并给出修复（②）；步骤把统计计算委托给外部成熟库或 MCP 后端，数值正确性由外部库承担（③）；三者合力产出"工作流可复现 × 内容合规 × 数值可信"的成果。

### 2.3 能力的组织方式：一份能力，两种用法

PsyClaw 覆盖研究的完整链条——研究准备、文献、分析、写作、评审与质量检查。但比"覆盖了多少功能"更值得说的，是这些能力被组织的方式：**每一份能力既能被单独使用，又同时是某条流程里的一步**。赶时间时，研究者可以只用其中一环（比如只做一次文献检索、或只跑一遍格式核查）；要严谨、可复现时，就让同一批能力按声明式流程自动串起来。二者背后是同一套实现，因此"单独用"和"进流程"不会给出两种不同的行为——这正是可复现性的前提之一。表 1 按研究阶段勾勒了这些能力所承担的角色。

**表 1** PsyClaw 的能力按研究阶段划分

| 研究阶段 | PsyClaw 承担的事 |
|---|---|
| 研究准备 | 澄清研究问题与假设、登记预注册、功效与样本量估算、伦理核对 |
| 文献 | 多库检索与引文滚雪球、生成规范引用、核查引用是否真实存在 |
| 分析 | 据数据画像推荐合适的分析，生成可复现脚本并委托外部库执行 |
| 写作 | 按目标期刊规范起草与润色、稿件标注、多格式导出 |
| 评审 | 模拟同行评审、按 JARS 等规范自检 |
| 贯穿全程 | 学术诚信核查与三层记忆（见 2.4、2.5） |

无论单独使用还是纳入流程，每一环都遵循同一种约定：所需能力不可用时，先给出可诊断的提示或一份可自行运行的降级方案，而不是中途报错；凡涉及统计结论，都附上可复现脚本与数据指纹。正是这种一致的约定，让"单用"与"入流程"之间没有行为落差。目前，文献综述、元分析、实证分析、质性分析四类研究被固化为稳定的声明式流程，其余能力则可按需拼装。

### 2.4 学术诚信核查与质量检查

学术诚信核查是 PsyClaw 的招牌设计——它把"研究做得规不规范"这件事，从"把活干完"里单独拎出来专门保障，而不是混在流程里听天由命。

**规范与规则两种形态。** 这层核查有两种形态。一是一份人读的规范，把研究诚信原则讲清楚——可复现优先、不 p-hacking、效应量与不确定性并报、区分探索与确证、诚实可视化、相关不等于因果、尊重原始数据、遵循 APA7；这份规范同时作为系统提示注入模型，使它在生成阶段就受约束。二是把其中可机器判定的部分，落成十四条带"触发点—判据—不合规怎么办"的规则，在每个产出点自动核查（见表 2）。阻断类规则不达标就中止产出并给出修复路径（如自动补算效应量与置信区间、提示稳健替代检验、把确证改标为探索）；告警类规则则记入审计日志，供人工复核。

**表 2** PsyClaw 的机器可核查学术诚信规则（共十四项）

| 规则 | 触发点 | 要求 | 不合规时 |
|---|---|---|---|
| `STAT.effect_size` | 统计产出 | 显著性检验必含效应量 + CI | 阻断，自动补算 Cohen's *d* / *η*² / *r* 及 95% CI |
| `STAT.assumptions` | 跑检验前 | 正态/方差齐性/独立性已诊断 | 阻断，提示稳健替代（Welch/非参/bootstrap） |
| `STAT.no_phack` | 分析过程 | 无未声明多重比较/择优/HARKing | 告警 + 审计日志 |
| `DESIGN.power` | 实验设计 | 样本量来自先验功效分析 | 阻断 |
| `DESIGN.prereg` | 确证性研究 | 有预注册或明确标注探索性 | 阻断或改标探索性 |
| `WRITE.apa7` | 论文产出 | 引用/数字/表格符合 APA7 | 阻断，自动修正 |
| `LIT.prisma` | 文献综述 | 检索/筛选符合 PRISMA | 提示补全 |
| `REPRO.script` | 任何统计结论 | 附复现脚本 + 数据指纹 | 阻断 |
| `FIG.honest` | 出图 | 坐标轴诚实、误差棒含义、色盲友好 | 阻断 |
| `DATA.careless` | 数据筛查 | 已跑粗心作答筛查、剔除经人工批准 | 阻断 |
| `MEASURE.reliability` | 使用量表分 | 合成量表分前必报信度 | 阻断 |
| `CLARIFY.complete` | 研究开始 | 研究准备卡全部项已解决 | 阻断 |
| `DESIGN.evidence` | 设计决策 | 每条决策有方法学文献背书 | 阻断 |
| `STAT.rigor` | 分析流水线 | 数据质量→描述→诊断→稳健性→限定措辞 | 阻断 |

**机器管客观、人管主观。** 这里要区分两类把关：一类是价值判断——什么时候停下、异常值该不该剔、这个取舍值不值，这类事没有唯一正确答案，交给人；另一类是合规判断——产出本身有没有违反明确的规范，这类事有客观标准，交给机器。核查负责后者并给评审提供客观依据，前者始终留给研究者。二者互补，谁也不越俎代庖。

**图，也是内容的一部分。** 核查不只看统计与文字，也看图。它会拦下两类问题：其一，图注自称"待生成/占位"却仍随稿交付的占位图；其二，正文里的本地图片链接指向的文件在稿件里根本不存在的断链。这条规则来自一次真实的教训（详见 3.4 节）：图是论文内容的一部分，不是可选项；一张主图从未生成、却在交付稿里留着占位符，这样的稿子不该被悄悄放过。

**兜底的高标准。** 还有一种兜底：当某项具体依据（如某本期刊的字数与版块要求）不在系统覆盖范围内时，它不把"查无匹配"说成失败或死路，而是明确套用通用高标准（效应量加 CI、相关不等于因果、区分探索与确证、图件不得缺失等），并指清哪些细节需研究者对照官方指南自行确认。这样，覆盖盲区就不会变成规避规范的缺口。

### 2.5 记忆、澄清与预注册

**三层记忆。** 系统维护贯穿路由与各步的三层记忆：方法学偏好（研究者惯用的检验取向、报告格式）、期刊惯例（目标刊的画像与要求）、教训卡（跨会话累积的具体教训）。记忆影响路由默认值与各步行为，使模型在多会话交互中自动遵循一致的前提与参数设定，并为过程审计提供可追溯依据。

**澄清与预注册作为前置核查。** 与"先跑起来再说"的取向相反，PsyClaw 把研究准备前置为硬性核查。`CLARIFY.complete` 核查要求在研究开始前完成研究准备卡的全部项（无未决项）；`DESIGN.prereg` 核查要求确证性研究在分析前具备预注册或明确标注为探索性。这把"区分探索与确证"这一研究方法学的核心规范，从事后自述变成了流程内不可绕过的前置步骤（Nosek et al., 2018）。

### 2.6 把关键决定留给人

自动化程度越高，越要想清楚哪些事不能让机器自己拍板。PsyClaw 的原则很简单：凡是有外部影响的操作——写文件、执行命令、调用外部工具——默认都要先经研究者批准，而非先斩后奏；批准的松紧档位可随时调整。更要紧的是，删数据、改测量口径、改核查判据这类既不可逆、又直接关系结论的操作，系统绝不自作主张，而是写成一份"决策请求"交给人来定。再加上"能力缺失时给可运行的降级方案、不碰原始数据、不在产出里写入任何密钥"，这些合起来保证了一件事：效率可以由自动化来提，但关键的、不可逆的、涉及诚信的判断，始终握在研究者手里。

### 2.7 验证

作为一个以编排与核查为主的系统，PsyClaw 的验证重点是"流程走得对、核查拦得住"，而不是统计数值本身。测试覆盖路由、声明式流程引擎、各子功能与核查规则等；在本文写作环境下的一次全量运行中，**2228 项测试全部通过**。

有一点必须讲清楚：测试**不校验统计量的数值精度**——这与"统计外移"的铁律一致，数值对不对由被委托的外部库负责。因此本文所称"可复现性"主要指**工作流层面**：每个统计结论都附带可复现脚本与数据指纹，流程末尾还有一份机器可读的总验收，使同一分析可被审计、复算与共享。作为统计确已"外移到位"的证据，元分析与实证分析流程生成的委托脚本，都能在装好相应库的环境中独立跑到正常退出——也就是说，PsyClaw 产出的编排是可执行的，真正做统计的是外部库，而非它自己。

**表 3** PsyClaw 的验证概览

| 层面 | 内容 | 结果 |
|---|---|---|
| 流程与接口 | 路由、配置、命令行、核查规则 | 全部通过 |
| 子功能 | 文献筛选、效应量校验、分析推荐、元分析脚本生成、转录本加载 | 全部通过 |
| 流程集成 | 四类声明式流程引擎 + 总验收 | 全部通过 |
| 统计外移 | meta/analysis 生成的委托脚本在装库环境独立运行 | 正常退出 |
| 全量 | 约 2200 个测试 | **2228 通过** |

### 2.8 与传统工作流的对比

表 4 从多个维度比较了 PsyClaw 辅助的工作流与三种传统方式（手写分析脚本、图形界面统计软件、通用 LLM 数据分析）的差异。需要强调的是，对比旨在刻画取舍而非否定其他方式：手写脚本在确定性与精确复现上具有优势，图形界面在零编程上手上具有优势，通用 LLM 在灵活性上具有优势；PsyClaw 的独特之处在于把研究编排与学术规范护栏一并纳入。

**表 4** PsyClaw 与传统工作流的对比

| 维度 | 手写脚本 | 图形界面软件 | 通用 LLM 分析 | PsyClaw |
|---|---|---|---|---|
| 覆盖范围 | 单环节 | 单环节（统计） | 单环节（分析） | 全链条编排 |
| 交互方式 | 编程 | 菜单 | 自然语言 | 自然语言 |
| 流程可复现 | 高（依赖规范） | 低（菜单难留痕） | 中 | 高（等效脚本+指纹+归档） |
| 学术规范护栏 | 依赖自律 | 无 | 无 | **失败即阻断核查** |
| 统计数值来源 | 自选库 | 内置 | 模型生成代码 | 外部成熟库/MCP |
| 上手门槛 | 高 | 低 | 低 | 低 |
| 确定性 | 高 | 高 | 低 | 中（编排非确定） |

## 3 面向社会科学研究者的使用建议

### 3.1 系统要求与安装

PsyClaw 以 Python 标准库为主实现，需 Python 3.11 及以上版本；唯一的第三方运行依赖是交互基础设施 prompt_toolkit（缺失时降级至 readline），因此可跨平台运行于 Windows、macOS 与 Linux。统计外移所依赖的成熟库（pingouin、statsmodels、SciPy 等）按需安装：不装则相关命令返回可运行的降级脚本，装了则可直接执行或经 MCP 后端委托运行。

安装提供在线脚本、包管理器与离线整包三种方式，并对网络受限环境做了适配。在 macOS 与 Linux 上可用一条 curl 命令安装；在 Windows 上可用 PowerShell 一条命令安装；安装脚本会自动探测 GitHub 可达性，在不通时切换至镜像与国内 PyPI 索引。亦可用 uv 或 pip 直接从源安装。装好后运行 `psyclaw doctor` 进行环境自检，运行 `psyclaw start` 进入交互式向导。若需接入外部统计或领域后端，可用 `psyclaw mcp` 配置并启用 MCP 服务器（系统内置对多种统计后端的委托封装，并可接入如 MNE-MCP 等领域服务器）。

### 3.2 典型使用场景

PsyClaw 面向四类具备稳定契约的研究流程，可用 `run <类型>` 一次性、可复现地执行，也可在 `chat` 中以自然语言分步驱动：

- **文献综述（literature）。** 从研究准备检查开始，经 PRISMA 识别的多库检索、PRISMA 筛选、结构化合成，到可选的同行评审。适用于系统综述与研究背景梳理。
- **元分析（meta）。** 校验各研究的效应量与不确定性后，生成委托 statsmodels 的随机效应元分析脚本（含异质性与发表偏倚检验）。**仓内不计算任何统计量**。
- **实证分析（analysis）。** 据数据画像推荐合适的分析（*t*/方差/相关/回归/描述），生成委托 pingouin/SciPy 的脚本；全程受 `STAT.*` 核查约束（效应量加 CI、假设诊断、稳健性、复现脚本）。
- **质性分析（qualitative）。** 解释性的 LLM 辅助编码与主题分析，研究者复核（HITL）。

无论走哪条流程，学术诚信核查都在相应产出点自动生效。对于拟用于发表的确证性研究，建议在项目根目录以记忆形式集中记录项目级约定（默认数据目录、目标期刊、报告格式、量表信度口径等），使模型在跨会话交互中自动遵循一致前提。

### 3.3 自然语言交互示例

以下示例展示了 PsyClaw 在接收自然语言请求后，如何自动编排流程、执行核查并在不合规时阻断。为聚焦交互逻辑，示例对系统返回内容做了精简；其中的数值与文献计数均为示例性说明，而非来自真实数据的测量结果。

**表 5** 自然语言交互示例：一次"分析到写作"的逐轮对话

| 轮次 | 用户（自然语言） | PsyClaw（编排 + 核查） |
|---|---|---|
| 1 | "我想比较两组被试的反应时。" | `CLARIFY.complete` 触发：研究准备卡尚有未决项（这是确证还是探索？有无预注册？）。请先完成澄清，否则阻断开工。 |
| 2 | "确证性，已在 OSF 预注册，组间独立样本 *t* 检验。" | 澄清完成，`DESIGN.prereg` 通过。据数据画像推荐独立样本 *t*（先诊断正态与方差齐性）。已生成委托 pingouin 的脚本，将在你本地执行——本系统不自算统计。 |
| 3 | "跑吧。" | 方差齐性不满足 → `STAT.assumptions` 提示改用 Welch *t*。结果：*t*(88.3)=2.41，*p*=.018。`STAT.effect_size` 触发：缺效应量与 CI → 自动补算 Cohen's *d*=0.51, 95% CI [0.09, 0.93]。已附复现脚本与数据指纹（`REPRO.script` 通过）。 |
| 4 | "帮我写进结果段落，就说 A 组更快导致了差异。" | 生成 APA7 结果段落（`WRITE.apa7`）。但"导致"属因果断言，此为非实验的组间比较 → 核查改写为相关性表述并提示：如需因果结论须满足识别假设。差异波与效应量已按 JARS 报告。 |
| 5 | "配一张组均值柱状图。" | 出图并过 `FIG.honest`：坐标轴自零起、误差棒标注为 95% CI、采用色盲友好配色；图件完整性校验确认图片文件已生成且链接可达，方才随稿内嵌。 |

该示例表明，研究者只需用自然语言描述目标，系统即可自动完成"澄清—推荐—委托执行—合规写作—诚实出图"的完整循环，并在每一处规范要点上自动把关；与此同时，统计计算始终在外部库中完成，关键的价值判断仍由研究者确认。

### 3.4 真实案例：图件完整性核查拦截一份缺陷手稿

为在真实产出上展示核查的把关，本节给出一次真实发生、并据此加固系统的案例。在一次以某高影响力期刊为目标的论文写作中，系统交付的手稿存在两处图件缺陷：其一，一张核心路径图从未被生成，交付稿里却赫然留着替代文本为"路径图——待生成"（Path diagram — to be generated）的占位图；其二，一张次要的调节效应图虽已生成，却未被内嵌，且其保存路径与稿中链接指向的目录不一致，导致该链接落空。

问题在于，当时的质量检查（JARS 与诚信启发式）**完全不看图**：手稿全过、静默交付——而这恰是"可视化不足、内容缺失"的直接来源。诊断显示，图是论文内容的一部分，而非可选项；一份主图从未兑现、却以占位符充数的稿件，不应被放行。据此，系统在质量检查中新增了图件完整性核查：`I.figure_placeholder` 拦截替代文本自认"待生成/将补充/占位"（中英文均覆盖）的占位图，`I.figure_missing_file` 校验每个本地图片链接指向的文件是否真实存在（远程与内嵌数据链接跳过）。为高精度、避免误伤正文中谈论"占位符"这一概念的行文，占位检测仅扫描替代文本，且沿用参考文献区截断规则不予扫描。

在那份真实手稿上复核的结果是：**修复前，零阻断、静默通过；修复后，同时命中 `I.figure_placeholder` 与 `I.figure_missing_file`，手稿被阻断**并给出具体的待修项。这一案例与 MNE-MCP 中方法学审查代理对"伪重复"返回修订裁定的情形同类（Xue et al., 2025）：它表明核查能对系统自身的产出提出实质性质疑，而非形式化附和，从而把 2.4 节所述的自动化偏误风险落到一次具体的真实拦截上。相应的图件完整性校验已随十二项新增测试固化进测试套件，且遵循"质量检查只增不减"的原则——核查一旦确立，只会加严、不会悄然放松。

## 4 结论

本文介绍了 PsyClaw：把 Claude Code 所代表的智能体范式引入社会科学研究的开源智能体研究助手。针对社会科学研究"流程长、规范密"的本质，系统以"四层加两横切"的可组合架构，把文献、澄清预注册、统计分析、论文写作与同行评审编排为自然语言驱动、可复现的工作流。其三项核心设计——声明式的研究流程、失败即阻断的学术诚信核查、统计外移的分层委托——共同构成了它区别于通用 LLM 数据分析方案的特征。系统通过约 2200 个自动化测试（本文环境下 2228 项全部通过）、四类声明式流程的集成测试、统计外移生成脚本的独立可执行性，以及核查自检完成质量保证，并以一次真实手稿被图件完整性核查拦截的案例，展示了核查的实际把关。

PsyClaw 的核心贡献有二。其一，它把在软件工程中被验证的智能体范式（Claude Code）迁移并适配到社会科学研究的完整链条：由 LLM 依用户意图分派研究类型、逐步执行并回流结果，声明式流程与等效脚本、数据指纹、归档机制保障了工作流层面的可复现与可审计。其二，也是更关键的，它把散落于 JARS、PRISMA、预注册等规范中的学术诚信要求，凝练为一层**失败即阻断的机器核查**，前置到每一个产出点——从而把可复现性与规范性，从依赖个人自律的软约束，转变为流程内不可绕过的硬约束。与以代码生成为主的通用方案相比，这一路径把"编排得对不对、报告合不合规"置于系统的核心位置。同时，通过坚持"不在本仓实现任何统计算法"的铁律，PsyClaw 把数值正确性交给成熟库、把规范正确性留给自己，两相分离而各司其职；作为编排框架，它天然地能够托管如 MNE-MCP 这样的领域 MCP 服务器，把专业统计接入同一条守规矩的研究流程。

**局限与风险。** 本研究存在若干局限，使用时需特别注意。其一，学术诚信核查是基于规范的启发式检查，能拦截可机器判定的违规（缺效应量、占位图、无预注册的确证分析等），但**不能替代人类的方法学判断**：许多深层的效度问题（构念效度、混淆变量、因果识别假设的合理性）仍需研究者与评审者把关，核查是辅助而非替代。其二，把"看图—判断—写作"自动化仍存在**自动化偏误**风险：模型以自信措辞给出的建议，可能在缺乏审查时被不加辨别地采纳，因此人在回路不可或缺，涉及价值判断与不可逆操作的环节始终保留人工审批。其三，各统计量的**数值精度继承自外部库**，而非由本系统保证；本文的验证确立的是编排的功能正确性与流程集成，而非统计数值的准确性。其四，相较于确定性的手写脚本，经由 LLM 的编排存在**非确定性**，并带来延迟与调用成本。

**未来工作。** 可在以下方向继续推进：在真实研究场景中对核查的拦截准确率（真阳性与假阳性）进行系统评估；把预注册与投稿格式化进一步一键化；扩充可委托的 MCP 统计与领域后端；以及将质性编码升级为专用技能。随着 MCP 生态的成长与 LLM 能力的提升，专业科研规范与 AI 助手的集成将进一步深入。作为这一方向的早期实践，PsyClaw 尝试证明：AI 辅助的科研自动化，不应以牺牲学术规范为代价——恰恰相反，规范可以被编码为流程内不可绕过的护栏。其架构与核查设计，亦可为其他规范密集学科的研究编排所借鉴。

---

## 参考文献

Anthropic. (2024). *Model Context Protocol: An open standard for connecting AI assistants to data systems*. https://modelcontextprotocol.io

Anthropic. (2025). *Claude Code* [Computer software]. https://www.anthropic.com/claude-code

Appelbaum, M., Cooper, H., Kline, R. B., Mayo-Wilson, E., Nezu, A. M., & Rao, S. M. (2018). Journal article reporting standards for quantitative research in psychology: The APA Publications and Communications Board task force report. *American Psychologist, 73*(1), 3–25. https://doi.org/10.1037/amp0000191

Camerer, C. F., Dreber, A., Holzmeister, F., Ho, T.-H., Huber, J., Johannesson, M., Kirchler, M., Nave, G., Nosek, B. A., Pfeiffer, T., Altmejd, A., Buttrick, N., Chan, T., Chen, Y., Forsell, E., Gampa, A., Heikensten, E., Hummer, L., Imai, T., … Wu, H. (2018). Evaluating the replicability of social science experiments in Nature and Science between 2010 and 2015. *Nature Human Behaviour, 2*(9), 637–644. https://doi.org/10.1038/s41562-018-0399-z

Cumming, G. (2014). The new statistics: Why and how. *Psychological Science, 25*(1), 7–29. https://doi.org/10.1177/0956797613504966

DerSimonian, R., & Laird, N. (1986). Meta-analysis in clinical trials. *Controlled Clinical Trials, 7*(3), 177–188. https://doi.org/10.1016/0197-2456(86)90046-2

Egger, M., Davey Smith, G., Schneider, M., & Minder, C. (1997). Bias in meta-analysis detected by a simple, graphical test. *BMJ, 315*(7109), 629–634. https://doi.org/10.1136/bmj.315.7109.629

Gramfort, A., Luessi, M., Larson, E., Engemann, D. A., Strohmeier, D., Brodbeck, C., Goj, R., Jas, M., Brooks, T., Parkkonen, L., & Hämäläinen, M. (2013). MEG and EEG data analysis with MNE-Python. *Frontiers in Neuroscience, 7*, 267. https://doi.org/10.3389/fnins.2013.00267

Harris, C. R., Millman, K. J., van der Walt, S. J., Gommers, R., Virtanen, P., Cournapeau, D., Wieser, E., Taylor, J., Berg, S., Smith, N. J., Kern, R., Picus, M., Hoyer, S., van Kerkwijk, M. H., Brett, M., Haldane, A., del Río, J. F., Wiebe, M., Peterson, P., … Oliphant, T. E. (2020). Array programming with NumPy. *Nature, 585*, 357–362. https://doi.org/10.1038/s41586-020-2649-2

Hong, S., Lin, Y., Liu, B., Liu, B., Wu, B., Zhang, C., Wei, C., Li, D., Chen, J., Zhang, J., Wang, J., Zhang, L., Zhang, L., Yang, M., Zhuge, M., Guo, T., Zhou, T., Tao, W., Tang, X., … Wu, C. (2024). *Data Interpreter: An LLM agent for data science* (arXiv:2402.18679). arXiv. https://doi.org/10.48550/arXiv.2402.18679

John, L. K., Loewenstein, G., & Prelec, D. (2012). Measuring the prevalence of questionable research practices with incentives for truth telling. *Psychological Science, 23*(5), 524–532. https://doi.org/10.1177/0956797611430953

Kerr, N. L. (1998). HARKing: Hypothesizing after the results are known. *Personality and Social Psychology Review, 2*(3), 196–217. https://doi.org/10.1207/s15327957pspr0203_4

Meade, A. W., & Craig, S. B. (2012). Identifying careless responses in survey data. *Psychological Methods, 17*(3), 437–455. https://doi.org/10.1037/a0028085

Nosek, B. A., Ebersole, C. R., DeHaven, A. C., & Mellor, D. T. (2018). The preregistration revolution. *Proceedings of the National Academy of Sciences, 115*(11), 2600–2606. https://doi.org/10.1073/pnas.1708274114

Open Science Collaboration. (2015). Estimating the reproducibility of psychological science. *Science, 349*(6251), aac4716. https://doi.org/10.1126/science.aac4716

Page, M. J., McKenzie, J. E., Bossuyt, P. M., Boutron, I., Hoffmann, T. C., Mulrow, C. D., Shamseer, L., Tetzlaff, J. M., Akl, E. A., Brennan, S. E., Chou, R., Glanville, J., Grimshaw, J. M., Hróbjartsson, A., Lalu, M. M., Li, T., Loder, E. W., Mayo-Wilson, E., McDonald, S., … Moher, D. (2021). The PRISMA 2020 statement: An updated guideline for reporting systematic reviews. *BMJ, 372*, n71. https://doi.org/10.1136/bmj.n71

Rahman, M., Bhuiyan, A., Islam, M. S., Laskar, M. T. R., Mahbub, R., Masry, A., Joty, S., & Hoque, E. (2025). *LLM-based data science agents: A survey of capabilities, challenges, and future directions* (arXiv:2510.04023). arXiv. https://doi.org/10.48550/arXiv.2510.04023

Simmons, J. P., Nelson, L. D., & Simonsohn, U. (2011). False-positive psychology: Undisclosed flexibility in data collection and analysis allows presenting anything as significant. *Psychological Science, 22*(11), 1359–1366. https://doi.org/10.1177/0956797611417632

Vallat, R. (2018). Pingouin: Statistics in Python. *Journal of Open Source Software, 3*(31), 1026. https://doi.org/10.21105/joss.01026

Virtanen, P., Gommers, R., Oliphant, T. E., Haberland, M., Reddy, T., Cournapeau, D., Burovski, E., Peterson, P., Weckesser, W., Bright, J., van der Walt, S. J., Brett, M., Wilson, J., Millman, K. J., Mayorov, N., Nelson, A. R. J., Jones, E., Kern, R., Larson, E., … SciPy 1.0 Contributors. (2020). SciPy 1.0: Fundamental algorithms for scientific computing in Python. *Nature Methods, 17*, 261–272. https://doi.org/10.1038/s41592-019-0686-2

Xue, J., Wei, S., & Zhu, T. (2025). *MNE-MCP: An automated neurophysiological analysis system for MCP-compatible AI coding assistants* [Manuscript / preprint].
