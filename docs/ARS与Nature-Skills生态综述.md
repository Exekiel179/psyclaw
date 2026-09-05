# ARS 与 Nature Skills：学术研究 Agent Skill 生态综述

状态：调查综述，不构成准入、安装或执行批准  
资料截点：2026-09-02（Asia/Shanghai）

## 摘要

2026 年 GitHub 上的学术研究 Agent 生态出现了两个关注度很高、但路线明显不同的项目：Academic Research Skills（ARS）与 Nature Skills。需要先澄清项目谱系：本文所称 ARS 是 Claude Code 原始上游 [`Imbad0202/academic-research-skills`](https://github.com/Imbad0202/academic-research-skills)，不是其 Codex 适配仓。后者 [`Imbad0202/academic-research-skills-codex`](https://github.com/Imbad0202/academic-research-skills-codex) 的 README 明确称其为独立打包、独立版本的 Codex-native sibling，并以 commit 固定、vendoring 的方式同步上游内容。

截至资料截点，GitHub API 显示 ARS 上游约 45,346 stars、3,573 forks，Nature Skills 约 38,612 stars、2,135 forks；两者都在 2026 年创建，并在 2026-09-01 仍有提交。它们确实是当前学术 Skill 赛道的高关注项目，但 star 只能证明传播与关注，不能证明学术正确性、安全性、可复现性或跨学科有效性。

两者的核心差异不是“谁包含的功能更多”，而是控制平面不同：ARS 是一个由统一状态机、阶段检查点、Material Passport、引用与 Claim 门禁连接起来的端到端研究协作框架；Nature Skills 是由 19 个可触发技能和 1 个共享支持包组成的横向工具箱，强调按任务安装、直接生成阅读卡片、图件、PPT、审稿回复、检索结果等具体产物。前者适合借鉴研究流程与完整性契约，后者适合选择性接入末端专业能力。

对 PsyClaw 而言，合理方向不是复制任一套 runtime，也不是把两个仓库整体并入核心。更稳健的组合是：保留 PsyClaw 的证据账本、审批、receipt、幂等、路径隔离和 Verifier 作为唯一控制面；把 ARS 的阶段门、Claim/引用治理和 human-in-the-loop 原则转译成自身契约；把 Nature 中经过逐项准入的 Skill 当作末端工具。任何真实统计仍委托成熟 Python/R 库或受信 MCP。

## 1. 调查方法与证据边界

本综述使用三类材料：

1. GitHub API 的仓库元数据、commit、release、contributors、pull request 和文件树，用于描述可观测活动与仓库结构。
2. 项目官方 README、SKILL.md、架构、风险、许可证、依赖和安全文档，用于描述项目自我声明的能力与边界。
3. 官方论文或会议页面，用于建立学术研究 Agent 的研究背景和独立基准。

仓库自述与独立验证严格区分。诸如“Stable”“production-tested”“真实案例验证”“被其他机构借鉴”等标签，如果没有公开评测协议、数据、模型版本、人工 gold set 和可复现结果，只作为维护者声明，不作为效果事实。本文没有 clone、安装或执行任何外部仓库，也没有复跑其测试，因此不对功能可用性、安全性或研究效果作认证。

GitHub 的 `updated_at` 会被 star、issue 等活动更新，本文以 `pushed_at` 判断代码活动。stars、forks、issues 都是瞬时值，后续会变化。

## 2. GitHub 趋势快照

| 项目 | 创建时间 | Stars | Forks | 最近 push | 发布与维护信号 |
|---|---:|---:|---:|---:|---|
| [ARS 上游（Claude Code）](https://github.com/Imbad0202/academic-research-skills) | 2026-02-26 | 45,346 | 3,573 | 2026-09-01 | v3.21.1；2026-06 至 08 有连续版本化 releases；有架构、风险、安全、评测与治理文档 |
| [Nature Skills](https://github.com/Yuan1z0825/nature-skills) | 2026-04-24 | 38,612 | 2,135 | 2026-09-01 | 无 GitHub Release；持续以 main 提交扩展技能、图件检查、写作规范和多宿主安装面 |
| [ARS-Codex 派生发行](https://github.com/Imbad0202/academic-research-skills-codex) | 2026-04-25 | 9,812 | 455 | 2026-08-24 | 独立版本 v0.1.27；12 个 releases、15 个 tags；README 记录同步 ARS v3.21.1 的上游 commit |

数据源为三个仓库的 GitHub API 元数据端点，例如 [`api.github.com/repos/Imbad0202/academic-research-skills`](https://api.github.com/repos/Imbad0202/academic-research-skills) 与 [`api.github.com/repos/Yuan1z0825/nature-skills`](https://api.github.com/repos/Yuan1z0825/nature-skills)。

Nature 仓库保存了一份由 GitHub stargazer timestamps 生成的静态历史图。其 2026-09-01 快照记录 38,177 stars，说明从 4 月末到 9 月初持续增长；次日 API 快照为 38,612。该历史图是仓库自生成资产，但底层声称来自 GitHub stargazers API，适合证明其自身增长曲线，不适合作为两个项目的统一比较基准。ARS 未提供同口径历史文件，因此本文不计算两者的“最近 30/90 天增长率”，避免用不对称数据制造精确比较。

活动窗口可提供另一个视角。按 GitHub API `since` 查询，在 2026-08-03 至资料截点的 30 天窗口，Nature 有 76 个 commit、23 个被更新的 PR；在 2026-06-04 起的 90 天窗口有 378 个 commit、129 个被更新的 PR。ARS-Codex 对应为 8/3 与 26/10。这里的 PR 是 `updated_at` 口径，不等于新建或合并数量；commit 也包含 bot 更新。由于本次对 ARS 主体的范围纠正在 worker 派发后发生，没有用同一查询一次性取得 ARS 上游的窗口计数，故不以这些数字给 ARS 与 Nature 排名。

工程活动也不能只看 commit 数。ARS 文件树中只有 4 个顶层可触发 Skill，但它们内部组成一个庞大的统一工作流；公开树快照含大量 scripts/tests 文件，并通过连续 release 管理语义变化。Nature 当前有 19 个可触发 Skill，另有 `nature-shared` 支持包；文件树可见约 101 个脚本文件和 84 个测试路径。Nature 最近 30 条 commit 中混合了功能提交与由 GitHub Actions 生成的 star-history 更新，因此原始 commit 数会高估人工工程活动。

贡献结构仍然集中。GitHub contributors 快照中，ARS 第一贡献者的提交数远高于其余贡献者；Nature 的前三位包括 GitHub Actions bot 与两名主要维护者。两者都已有外部 PR 贡献，但不能据此推断已经形成低 bus-factor 的稳定组织。

## 3. ARS 的正确谱系

ARS 的参考实现是 [`Imbad0202/academic-research-skills`](https://github.com/Imbad0202/academic-research-skills)，项目自述定位为 Claude Code 的 research -> write -> review -> revise -> finalize 套件。它包含四个顶层 Skill：`deep-research`、`academic-paper`、`academic-paper-reviewer` 与 `academic-pipeline`，并通过 `skills/`、commands、agents、hooks、shared contracts 和 tests 提供 Claude Code 安装面。

[`academic-research-skills-codex`](https://github.com/Imbad0202/academic-research-skills-codex) 不是上游，也不是 GitHub fork。它是同一维护者提供的 Codex-native sibling：把 ARS 工作流 vendoring 到一个 `academic-research-suite` Skill，通过单一 router 暴露五条逻辑工作流，并独立维护 adapter 版本。其 README 在本次调查时记录 vendored source 为 ARS v3.21.1、commit `127ff85e4bbfcdd10b95040537b6c6bd7ad17aeb`。因此：

- 讨论 ARS 的理念、历史、维护活动与主热度时，应引用 Claude 上游。
- 讨论 Codex 的入口、alias、hook 降级和打包方式时，才引用 ARS-Codex。
- 两仓库 stars 不能相加；它们代表相关但不同的 GitHub 发行面。

这一谱系也揭示了学术 Skill 的新趋势：方法内容开始与宿主 adapter 分离，但不同宿主可用的 hook、subagent、command registry 与安全边界并不等价。内容“相同”不意味着运行语义相同。

## 4. 两种架构范式

### 4.1 ARS：统一研究状态机

ARS 的 [`ARCHITECTURE.md`](https://github.com/Imbad0202/academic-research-skills/blob/main/docs/ARCHITECTURE.md) 描述一条带分支与回路的 10 阶段宏观流程：研究、写作、完整性检查、审稿、修订、复审、再修订、最终完整性检查、格式化与过程总结。关键状态转换要求用户确认；Stage 2.5 与 4.5 先做机器检查，再由用户确认。

它的主要工程对象不是单个提示词，而是跨阶段不变量：

- Material Passport 承载来源、Claim、实验 provenance 和阶段状态。
- 引用存在性、locator、claim-source alignment 与冲突证据被分成不同检查层。
- reviewer 使用独立角色、盲化阶段、稳定 concern identity 与 revision traceability。
- 写作、审稿和修订之间有明确的产物交接与回归检查。
- 有风险登记、控制可用性矩阵、降级登记和版本化发布。

ARS 的 [`POSITIONING.md`](https://github.com/Imbad0202/academic-research-skills/blob/main/POSITIONING.md) 对其能力上限给出了重要限制：它检查稿件与“被报告的过程”，但不能证明实验实际执行、原始数据真实完整或结果可从底层材料复现。一个内部一致、引用和包装完备的伪造研究仍可能通过其门禁。这一自我限制比“端到端论文生成”宣传更值得借鉴。

统一状态机的优点是跨阶段 Claim identity、证据状态和人工权力较容易保持一致；代价是耦合重、上下文大、局部替换困难，并高度依赖宿主是否真实支持声明的 hook、agent team 与 checkpoint 语义。

### 4.2 Nature Skills：可组合的专业工具箱

Nature Skills 的 [`README_EN.md`](https://github.com/Yuan1z0825/nature-skills/blob/main/README_EN.md) 将每个 `skills/nature-*` 顶层目录定义为独立安装单元，复杂 Skill 可以包含 `SKILL.md`、`manifest.yaml`、static fragments、references、scripts 与 assets；`nature-shared` 为部分技能提供按需公共规则。

当前 19 个可触发 Skill 横跨：

- 文献：多源检索、引用与参考文献核验、合法全文获取、每日文献 pipeline。
- 阅读与知识表达：双语全文 reader、Paper Card、论文转 PPT、图片转可编辑 PPT。
- 写作与评审：proposal-first 写作、Nature 风格写作/润色、三份互盲审稿、逐点回复。
- 研究产物：科研图、统计报告审计、Data Availability/FAIR、实验日志、中国专利草稿。

这套结构的优势是最窄路由和渐进采用：用户可以只安装 `nature-ref-verifier` 或 `nature-figure`，不必进入整篇论文状态机。劣势是跨 Skill 的状态词、证据 identity、审批和 handoff 并无一个仓库级统一运行时强制；这些责任更多落在宿主 Agent 上。

Nature 自身对成熟度做了区分：本次快照中只有 `nature-figure`、`nature-polishing`、`nature-ref-verifier` 与 `nature-literature-pipeline` 标为 Stable，其余多为 Beta 或 Draft；项目对 Draft 的定义就是规则已写明但尚未在真实案例测试。综述或集成时不能把“仓库有 19 个 Skill”等价为“19 个能力均已验证”。

## 5. 核心对比

| 维度 | ARS 上游 | Nature Skills |
|---|---|---|
| 基本形态 | 4 个高耦合 Skill + 统一 pipeline | 19 个可触发 Skill + 1 个共享包 |
| 主入口 | Claude Code plugin/commands；另有 Codex sibling | Open Agent Skills 风格，多宿主按 Skill 安装或 wrapper |
| 控制模型 | 状态机、阶段 checkpoint、mandatory gate | 最窄 Skill 路由，任务局部 workflow |
| 强项 | 研究问题收敛、跨阶段证据、审稿修订、完整性门 | 全文阅读、图件、PPT、引用、检索、回复、数据与传播产物 |
| 证据机制 | Material Passport、Claim registry、locator、分层引用与完整性检查 | 各 Skill 的 source anchor、verified/mismatch/not_found/manual_needed、共享写作原则 |
| 人类角色 | 每个关键研究状态转换由研究者确认 | 多数 Skill 定义输入、边界与人工检查，但缺统一跨 Skill checkpoint |
| 统计边界 | 主套件不证明真实实验；另有 experiment-agent 伴生项目 | `nature-statistics` 主要审计报告，不应替代真实重分析 |
| Release | 连续语义化 release，本次为 v3.21.1 | 无 GitHub Releases，以 main 演进 |
| 根许可证 | CC BY-NC 4.0，项目自称 source-available、非开源许可证 | Apache-2.0 |
| 供应链优势 | 上游/派生 manifest 可记录精确 commit；风险与降级文档较完整 | 模块可单独审计、Apache 许可证清晰、安装脚本有 copy/diff 与受管 prune 防护 |
| 供应链风险 | 仓库体量大、重复 vendored 内容多、dev 依赖未完全 hash-lock；`main` 安装仍可漂移 | 自动更新 hook、`git pull`/`npx`、宽 Python/MCP/browser/API 依赖；无 SECURITY.md 与 release pin |

### 5.1 引用与 Claim 真实性

两者都已经超越“给每段加几个看起来合理的引用”，但成熟度不同。ARS 将引用存在性、可定位性、Claim 支撑、负面约束与修订漂移组织成全流程合同，并明确某些检查是抽样或 LLM-mediated。Nature 的 `nature-academic-search`、`nature-ref-verifier`、`nature-reviewer` 和 `nature-paper-card` 分别提供多源核对、字段不一致、evidence pointer 与作者陈述/Agent 分析分离。

ARS 更接近全局 fail-closed 账本；Nature 更常用 `manual_needed`、`unverified` 或材料不足不可评的开放协作状态。接入 PsyClaw 时，不能直接混用两套状态词，应该统一映射到 `supported | uncertain | unsupported` 及 `block | warn`，并保留原始判断、locator、工具 receipt 和理由。

### 5.2 统计与研究方法

两套项目的仓库名与功能覆盖很容易让用户误以为它们能验证研究结果。事实不是这样。ARS 明确承认其完整性检查不验证原始数据真实性与实际执行；Nature 的统计 Skill 主要面向统计报告透明性、实验单位、重复、p 值、多重比较、效应量、置信区间及跨章节一致性。

这与 PsyClaw 的边界一致：Skill 可以检查报告契约、提出分析计划或生成委托规格，但统计数值必须来自成熟库、专业软件或受信 MCP 的真实运行，并保存脚本、输入指纹、环境和结果哈希。任何“由模型读稿判断统计正确”的输出都只能是审阅意见，不能成为计算证据。

### 5.3 许可证与可集成性

ARS 根 [`LICENSE`](https://github.com/Imbad0202/academic-research-skills/blob/main/LICENSE) 是 CC BY-NC 4.0。其 [`POSITIONING.md`](https://github.com/Imbad0202/academic-research-skills/blob/main/POSITIONING.md) 明确称其为 source-available、非商业学术使用框架，并指出该许可证不是开源许可证。PsyClaw 若是商业产品、收费服务或企业部署，不能仅因代码公开就复制其正文或 vendored 内容，必须先获得适用许可或只独立实现不受版权保护的抽象思想与自有契约。

Nature 根许可证为 [Apache-2.0](https://github.com/Yuan1z0825/nature-skills/blob/main/LICENSE)，通常更利于商业修改与再分发，但许可证兼容并不等于供应链可信。逐 Skill 的第三方 assets、references、模型/API 服务条款和依赖许可证仍需审计。

## 6. 更广的研究与 GitHub 生态

ARS 与 Nature 不是孤立项目。2023-2026 的学术 Agent 大致沿四条路线演进。

### 6.1 Grounded synthesis：先解决“找得到、引得准”

[STORM](https://github.com/stanford-oval/storm) 把多视角提问、检索、模拟访谈、outline 和带引用长文组合起来，其论文分别发表于 NAACL 2024 与 EMNLP 2024；[PaperQA2](https://github.com/Future-House/paper-qa) 聚焦科学全文 RAG、证据定位和问答评测。它们奠定了后续 deep research 的问题分解、检索、引用 grounding 与 benchmark 范式。

这条路线的价值在于缩小“生成流畅文本”和“回答有可定位来源”之间的差距，但它仍不能自动证明来源真的蕴含 Claim，也不保证检索覆盖没有语言、数据库或可访问性偏差。

### 6.2 闭环科研自动化：从检索扩张到实验和论文

[The AI Scientist-v2](https://arxiv.org/abs/2504.08066) 把假设、实验、分析、写作和评审串为端到端系统，并报告一篇全 AI 生成稿件通过 ICLR workshop 评审。该结果证明有限领域的闭环可以运行，但 workshop 接收不是研究真实性、普适能力或顶级会议主会质量的证明。

更关键的独立制约来自 [ScienceAgentBench（ICLR 2025）](https://proceedings.iclr.cc/paper_files/paper/2025/hash/f12b4df26344f3be803c06b555252efe-Abstract-Conference.html)：它从 44 篇同行评议论文构造 102 个数据驱动科研任务，由 9 名领域专家验证；论文报告当时最佳 Agent 在提供专家知识时也只解决 34.3% 的任务。这个基准支持“先验证工作流中的单项任务，再主张端到端自动化”的谨慎路线。

### 6.3 多 Agent 论文生产：专业分工和基准化

[PaperOrchestra](https://arxiv.org/abs/2604.05018) 将未结构化研究材料转换为带文献综述和视觉元素的 LaTeX 稿件，并提出包含 200 篇顶级 AI 会议论文逆向材料的 PaperWritingBench。它代表了“专业 Agent 分工 + 原始材料到稿件 + 自动/人工评测”的路线，也说明论文写作 Agent 的比较需要固定输入、基线与人类并排评估，而不能只展示一篇漂亮样例。

这类研究主要来自 AI/ML 论文，不能自动外推到心理学、调查研究、民族志、历史研究或政策研究。不同范式的证据充分性、伦理、研究者反身性和允许的结论动词必须独立建 profile。

### 6.4 可移植 Skill 与 MCP：把科研 SOP 产品化

2026 年一个显著的工程现象，是将科研 SOP、数据库说明和工具调用封装为可跨 Claude Code、Codex、OpenCode 等宿主复用的 `SKILL.md` 包。除 ARS 与 Nature 外，高相关项目包括：

| 项目 | 2026-09-02 stars 快照 | 主要邻接关系 |
|---|---:|---|
| [K-Dense Scientific Agent Skills](https://github.com/K-Dense-AI/scientific-agent-skills) | 约 41,978 | 160+ 科学工具/数据库 Skill；比 ARS 更像大规模工具目录，比 Nature 更偏科学计算与垂直数据库 |
| [STORM](https://github.com/stanford-oval/storm) | 约 31,203 | deep research / pre-writing 基础设施 |
| [The AI Scientist](https://github.com/SakanaAI/AI-Scientist) | 约 14,483 | 端到端自主 ML 研究，与 ARS 的 human-in-the-loop 形成对照 |
| [PaperQA2](https://github.com/Future-House/paper-qa) | 约 9,141 | 全文检索与带 locator 的证据回答，可作为检索引擎层而非写作 Skill |
| [Agent Laboratory](https://github.com/SamuelSchmidgall/AgentLaboratory) | 约 5,824 | 多 Agent 文献、实验与报告，包含阶段性人类反馈 |
| [Google DeepMind Science Skills](https://github.com/google-deepmind/science-skills) | 约 2,821 | 基因组学、结构生物学、化学信息学等官方数据库 Skill |
| [Paper2Agent](https://github.com/jmiao24/Paper2Agent) | 约 2,344 | 将论文及代码转成 MCP，执行面与供应链风险更高 |
| [AI4S Skills](https://github.com/ai4s-research/ai4s-skills) | 约 203 | 数值来源标签、results provenance、checkpoint 等契约与 PsyClaw 接近 |

这些 stars 来自同日 GitHub API/搜索快照，只用于说明关注度量级。仓库规模和传播渠道差异巨大，不能据此排名质量。

Skill 化降低了安装和复用门槛，也把新的风险带入研究流程：一个看似纯文本的 Skill 可以要求执行脚本、自动安装依赖、读取文件、调用浏览器或远程 API、写入知识库，甚至在 SessionStart 自动拉取更新。因此 `SKILL.md` 是代码供应链的一部分，而不是普通文档。

## 7. 对 PsyClaw 的设计启示

### 7.1 不复制 runtime，吸收契约

PsyClaw 应继续通过官方 Pi adapter/extension 接入，而不是 vendoring ARS 的 Claude/Codex runtime 或复制 Nature 的自动更新体系。值得吸收的是可独立实现和验证的合同：

- 研究状态转换必须有明确 owner；模型不能替研究者静默决定研究问题、方法、伦理或提交。
- Claim、Evidence、locator、contradiction、experiment provenance 和 revision concern 使用稳定 identity。
- 把“引用存在”“题录字段正确”“能定位到正文”“正文支持 Claim”拆成不同 verdict。
- 每个 artifact 记录输入、环境、脚本、模型/工具版本和 hash；声明可复现前必须真实复跑。
- Verifier 必须可校准，记录 FNR/FPR、gold set、覆盖率、抽样策略和失败形状。
- 安装渠道与运行时能力矩阵是合同的一部分；缺 hook 时不能声称门禁仍然生效。

### 7.2 推荐的组合架构

```text
PsyClaw project/run + policy
        |
        +-- Evidence / Claim / provenance ledger
        +-- approval / receipt / idempotency / path policy
        +-- paradigm-specific gates + Verifier
        |
        +-- ARS-derived ideas: stage contract, checkpoint, review/revision trace
        |
        +-- admitted Nature skills: reader / ref verifier / figure / response / ...
        |
        +-- trusted adapters: PaperQA-like retrieval, Python/R/SPSS/Stata/Mplus
```

ARS 更像流程骨架，Nature 更像能力叶节点；两者都不应成为新的事实源或权限控制面。统计、检索和文件生成工具返回的结果只能经 PsyClaw receipt、hash 与 gate 晋升为证据或 artifact。

### 7.3 准入优先级

若后续进行真实接入，建议按风险和可验证性分批，而不是整体安装：

1. 第一批只读且可确定性评测：`nature-ref-verifier`、局部 citation metadata 检查、reader 的 source-map 输出。
2. 第二批产物生成但不外发：figure、polishing、response；要求 owned paths、输入 hash、渲染/语义回归和人工验收。
3. 第三批网络与凭据：academic search、downloader、PaperQA/MCP；要求域名 allowlist、显式 env、合法访问和内容类型校验。
4. 最后一批自动化与高副作用：cron literature pipeline、browser、自动更新、Paper2Agent/实验执行；必须进隔离 sidecar，并有幂等与人工审批。

ARS 本体首先面临 CC BY-NC 许可问题。PsyClaw 可以研究其公开设计并独立实现相似的通用流程思想，但不应在未解决许可前复制 Skill 正文、模板、agents 或 vendored 文件。

### 7.4 建议新增的对比评测

对外部 Skill 的评价应以同一 fixture 横向比较，而不是 README 或 stars：

- 文献 fixture：citation existence、题录准确率、claim entailment、locator correctness、冲突披露、语言/数据库覆盖、成本与延迟。
- 稿件 fixture：错误召回率、误报率、稳定 concern identity、修订后回归、对 missing figure/table 的阻断。
- 数据/统计 fixture：raw-write 阻断、脚本/env/provenance 完整、探索/确证区分、效应量与区间报告、相关/因果边界。
- 安全 fixture：prompt injection paper、symlink escape、credential leakage、自动更新漂移、超时重复副作用、安装渠道缺 hook。
- 范式 fixture：`survey-observational` 与 `qualitative-thematic` 必须分开；不能用 Nature/AI/ML 的成功样例代表社会科学覆盖。

## 8. 结论

ARS 与 Nature Skills 的高关注度反映了一个真实变化：研究型 Agent 正从一次性提示词走向可安装、可版本化、带工具和流程状态的能力包。竞争焦点也正在从“能否生成论文文本”转向“能否保持来源、Claim、实验、修订和人类决策之间的可审计关系”。

ARS 当前在统一流程、风险自述、Claim/引用门禁和跨轮次一致性上更完整，但许可证、复杂度、宿主降级和“只能检查被报告过程”的上限很重要。Nature 当前在模块数量、具体产物、中文研究工作流和 Apache 许可上更有吸引力，但不同 Skill 的成熟度不一，自动更新、外部依赖、网络/浏览器和跨 Skill 状态需要宿主治理。

因此，对 PsyClaw 最有价值的不是选边，而是明确层级：ARS 提供可参考的研究控制合同，Nature 提供可候选的专业工具，PsyClaw 保留唯一的信任、证据和完成判定权。任何未经 source/ref/hash/license/dependency/fixture 预检的外部 Skill，都只能保持 `discovered`，不能因为热度高而直接执行。

## 9. 主要来源

- [ARS 上游仓库](https://github.com/Imbad0202/academic-research-skills)、[架构](https://github.com/Imbad0202/academic-research-skills/blob/main/docs/ARCHITECTURE.md)、[定位与经验工作边界](https://github.com/Imbad0202/academic-research-skills/blob/main/POSITIONING.md)、[风险登记](https://github.com/Imbad0202/academic-research-skills/blob/main/docs/RISK_REGISTER.md)、[许可证](https://github.com/Imbad0202/academic-research-skills/blob/main/LICENSE)
- [ARS-Codex 仓库及谱系说明](https://github.com/Imbad0202/academic-research-skills-codex)
- [Nature Skills 仓库](https://github.com/Yuan1z0825/nature-skills)、[英文 README 与 Skill 索引](https://github.com/Yuan1z0825/nature-skills/blob/main/README_EN.md)、[许可证](https://github.com/Yuan1z0825/nature-skills/blob/main/LICENSE)
- [ScienceAgentBench，ICLR 2025](https://proceedings.iclr.cc/paper_files/paper/2025/hash/f12b4df26344f3be803c06b555252efe-Abstract-Conference.html)
- [The AI Scientist-v2](https://arxiv.org/abs/2504.08066)
- [PaperOrchestra / PaperWritingBench](https://arxiv.org/abs/2604.05018)
- [Anthropic：Coding agents in the social sciences](https://www.anthropic.com/research/coding-agents-social-sciences)
- [STORM](https://github.com/stanford-oval/storm)、[PaperQA2](https://github.com/Future-House/paper-qa)、[K-Dense Scientific Agent Skills](https://github.com/K-Dense-AI/scientific-agent-skills)、[Google DeepMind Science Skills](https://github.com/google-deepmind/science-skills)

## 10. 局限

- GitHub 指标会持续变化，也可能受到传播、组织声量、镜像或短期流量影响。
- GitHub API 的 `watchers_count` 与 stars 同值；真正的仓库订阅数是 `subscribers_count`。本文没有把 watchers 当成额外关注度相加。
- GitHub API 的 `open_issues_count` 同时包含 issues 与 pull requests，不应用作纯 issue 数；本文只将其用于辅助观察，没有作为质量指标。
- 多数 Skill 仓库的能力数、稳定状态与成功案例来自维护者自述，未经过本综述独立复现。
- 本次未执行外部代码、安装依赖或复跑基准，所以无法确认 README 所述功能在当前环境可用。
- 自然科学、AI/ML 写作和 Nature 风格材料占生态主体，对心理学及其他社会科学范式的外部有效性仍不确定。
- 本文是叙述性技术综述，不是系统综述或 meta-analysis；搜索源以 GitHub 和已知官方研究为主，未穷尽所有语言、平台和闭源产品。
