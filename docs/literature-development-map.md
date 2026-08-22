> **v0.23 legacy documentation.** 本页保留用于复现 PsyClaw v0.23.0；v0.24.0 的当前范围、接口与验收标准请以 开工纪要.md、架构蓝图.md 和 评测框架.md 为准。

# 文献调研开发地图

**快照：** 2026-08-12  
**基线：** v0.22.0  
**对应总览：** [`DEVELOPMENT_MAP.md`](DEVELOPMENT_MAP.md)  
**范围：** literature workflow 与独立文献工具  

这份地图回答四个问题：文献调研由哪些功能组成、每个功能如何实现、已经留下了哪些可审计产物、当前到底完成到什么程度。状态严格区分：

| 状态 | 含义 |
|---|---|
| 已实现 | 代码路径已经存在，功能有明确输入、输出和错误处理 |
| 已测试 | 有离线自动化测试覆盖，不能等同于真实网络或账号验收 |
| 待真实验收 | 需要真实 Provider、网络、机构权限、浏览器或 Zotero |
| 技术债 | 已发现的实现差异或产品风险，需要单独修复 |

## 1. 用户价值与交付边界

文献调研不是一次搜索，而是一条证据链：

```text
研究问题
  -> 检索计划与预先标准
  -> 公开 API / 机构库多源检索
  -> DOI / 标题去重
  -> PRISMA identification
  -> 题录相关性初筛
  -> OA / 机构权限 / Zotero 全文获取
  -> 文献矩阵
  -> Evidence Map
  -> 有据综述
  -> 引用核验
  -> 同行评审
  -> workflow summary
```

产品上，PsyClaw 负责研究流程、证据追踪、规范约束和工具编排；它不绕过付费墙，也不把没有真实来源的文字包装成已验证结论。自动初筛目前是题录级的确定性相关性初筛，不是替代研究者判断的语义纳入排除。

## 2. 两条入口

### 2.1 正式流程：`run literature`

入口经过 `psyclaw/modes.py` 路由到 `psyclaw/workflows/registry.py` 中的 `lit-review` 定义，再由 `psyclaw/workflows/engine.py::run_workflow` 执行。

```text
clarify [required]
  -> lit_search [required]
  -> screen [required]
  -> synthesize [required]
  -> review [optional]
```

- 正式运行先调用 Provider 配置；无 Provider、缺 API key 或不可用后端会明确失败。
- `clarify` gate 未通过时 fail-closed，要求先运行 `psyclaw prepare`。
- `--exploratory` 可以显式跳过 gate，但会写入 `notes/gate_skips.md`，总验收标记 `exploratory: true`。
- 每步写检查点到 `.psyclaw/workflows/lit-review.json`，可用 `--resume` 从最后成功步骤继续。
- 末尾写 `notes/workflow_summary.json`，依据必需步骤是否完成给出机器可读 verdict。

**当前进展：已实现，离线测试覆盖；真实 Provider 端到端待验收。**

### 2.2 单项工具：`lit`

`psyclaw/psych/lit_cli.py` 是人工调试和局部重跑入口。它可以在不跑完整 workflow 的情况下执行搜索、全文、计划、导入、矩阵和合成。

| 操作 | 命令形态 | 主要产物 |
|---|---|---|
| 检索 | `psyclaw lit "主题"` | `notes/lit_search.json`、`notes/prisma_search.md` |
| 计划 | `psyclaw lit "主题" --plan` | `notes/search_plan.md`、`notes/screening_criteria.json` |
| 滚雪球 | `psyclaw lit --snowball DOI --direction both` | 终端结果，可继续导入或人工筛选 |
| 合法全文 | `psyclaw lit --fulltext DOI` | `outputs/pdfs/` 或全文文本 |
| 批量下载 | `psyclaw lit "主题" --download` | `outputs/pdfs/`、`pdf_audit.json` |
| 机构库回灌 | `psyclaw lit --import FILE` | 合并后的 `lit_search.json`、PRISMA 追加记录 |
| 文献矩阵 | `psyclaw lit --matrix "主题"` | `notes/lit_matrix.md`、`notes/evidence_map.json` |
| 有据综述 | `psyclaw lit "主题" --synthesize` | `notes/lit_review.md`、`evidence_map.json` |

**当前进展：已实现；真实网络、浏览器和账号链路待验收。**

## 3. 主流程逐步实现

### 3.1 研究准备 gate：防止没有问题定义就检索

**实现位置：**

- `psyclaw/workflows/registry.py::LIT_REVIEW`
- `psyclaw/workflows/steps.py::gate_clarify_complete`
- `psyclaw/psych/clarify.py::check_card`

**实现方式：**读取研究准备卡片，检查研究对象、核心构念、干预或暴露、结局、设计、样本、时间范围、理论、假设、分析计划、预注册等准备项是否已经 `resolved`。任何必需项未完成，正式流程停止而不是猜测缺失信息。

**产物与证据：**`notes/clarification.md`、准备卡片状态、流程日志；探索性跳过时另写 `notes/gate_skips.md`。

**进展：已实现 / 已测试。**

**边界：**它检查“是否完成准备”，不判断研究问题本身是否有价值，也不自动替研究者做最终纳入标准决策。

### 3.2 检索计划：先固定检索式和筛选标准

**实现位置：**`psyclaw/psych/litplan.py`

核心函数：

- `build_boolean_query`：将主题组织成中英文 OR 同义词块与 AND 领域限定。
- `default_criteria`：生成编号化纳入、排除标准。
- `build_search_plan`：组合公开 API 路线、机构库桥接步骤和目标条数。
- `write_search_plan`：落盘计划和标准。

**模型参与方式：**有 Provider 时允许 LLM 定制同义词和标准；模型调用失败或没有 Provider 时回到显式模板骨架。模板会保留占位符，不假装已经完成领域词扩展。

**产物：**

- `notes/search_plan.md`：中英文检索式、公开 API 命令、机构库操作步骤。
- `notes/screening_criteria.json`：机器可读标准。
- 人读版筛选标准目前包含在 `notes/search_plan.md`；稳定的机器可读真源是 `notes/screening_criteria.json`。

**进展：已实现 / 已测试。**

**产品意义：**把“先搜结果再临时改标准”的风险前置暴露，支持后续 PRISMA 和审计。

### 3.3 多源检索：统一题录 schema

**实现位置：**`psyclaw/psych/litsearch.py`

公开源适配器：

| 来源 | 实现重点 | 全文/元数据价值 |
|---|---|---|
| OpenAlex | 覆盖广；还原倒排摘要；提供 OA 状态、引用数 | DOI、OA、引用网络 |
| Crossref | DOI 元数据和中文 DOI 覆盖 | 题录权威补全 |
| Europe PMC | 心理/医学检索；摘要和 PMCID | OA XML 全文 |
| arXiv | 预印本 API 与 PDF 入口 | 预印本全文 |
| Semantic Scholar | 摘要、TL;DR、被引数、OA PDF | 语义补充和引用图谱 |

`search` 接收 `sources`、`limit`、`year_from`，对源名做别名解析；单个源网络异常时保留其他源结果，所有未知源在 `per_source` 中明确说明，不静默吞掉。

**统一记录字段：**标题、作者、年份、DOI、摘要、来源、OA 状态、OA URL、PMID/PMCID/arXiv id 等。

**进展：已实现 / 已测试。**

**技术债 TD-LIT-01：**`litsearch.DEFAULT_SOURCES` 是 OpenAlex、Crossref、Europe PMC，但 workflow 的 `step_lit_search` 当前显式传入 `openalex,europepmc`，导致正式 `run literature` 不使用 Crossref。CLI 与 workflow 的默认覆盖不一致，应收敛到同一个默认源真源，并补集成断言。

### 3.4 DOI 与标题去重：避免重复计数和重复引用

**实现位置：**`psyclaw/psych/litsearch.py::search`、`psyclaw/psych/litbridge.py::merge_results`、`psyclaw/psych/litmatrix.py::import_results`。

**实现方式：**优先以规范化 DOI 去重；没有 DOI 时以清洗后的标题或标题前 80 个字符去重。检索返回原始数、去重数、重复数和分来源计数。机构库回灌复用相同口径，并把导入事件追加到 PRISMA 记录。

**进展：已实现 / 已测试。**

**风险：**仅靠截断标题可能在极相似题名下误合并或漏合并，正式系统综述仍应人工核对题录。

### 3.5 PRISMA 记录：把检索和筛选变成可复查状态

**实现位置：**`steps.py::step_lit_search`、`steps.py::step_screen`、`lit_cli.py`、`litmatrix.py::import_results`。

识别阶段记录原始命中、去重后命中、重复数、来源和 OA 数；筛选阶段记录 screened、included、excluded 和筛选方法。机构库导入会追加解析、增加、重复和缺标题数量。

**产物：**`notes/prisma_search.md`、`notes/prisma_flow.md`。

**进展：已实现 / 已测试。**

**边界：**目前没有完整的全文资格审查、排除原因编码和最终纳入数管理界面；PRISMA 记录仍需要研究者补齐正式筛选决策。

### 3.6 题录初筛：确定性相关性排序，不冒充语义判断

**实现位置：**`psyclaw/workflows/steps.py::screen_papers`。

**实现方式：**从主题与“标题 + 摘要”提取英文内容词和中文二元组，计算主题词重叠比例；低于 `0.12` 的记录列为初步排除。当大多数记录都会被排除时，系统自动改为全部纳入待人工复核，避免跨语言或缺摘要导致错误筛空。

**产物：**`ctx.data["included"]` 供合成步骤使用；`notes/prisma_flow.md` 记录方法和数量；排除项包含标题、重叠分数和理由。

**进展：已实现 / 已测试。**

**产品边界：**这是“初筛 + 人工复核建议”，不是语义精筛、全文筛选或研究质量评价。下一阶段可增加人工决策表、双人筛选和冲突解决，而不是直接扩大自动排除权限。

### 3.7 全文获取：合法渠道优先，不绕过付费墙

**实现位置：**`psyclaw/psych/litsearch.py::get_fulltext`、`fetch_and_save`、`download_pdf`。

**获取优先级：**Europe PMC OA XML → Unpaywall OA PDF → arXiv/预印本 → 明确 OA 链接 → 机构权限入口 → closed/paywall。

**实现细节：**PDF 下载检查 `%PDF-` 魔数，拒绝把登录页或 HTML 保存为 PDF；文件按作者、年份和题名规范命名；按 SHA-256 查重；每次下载把 URL、路径、字节数、hash 和是否重复追加到 `outputs/pdfs/pdf_audit.json`。

**进展：已实现 / 已测试（离线模拟）；真实出版社和 OA 链接待验收。**

### 3.8 机构权限：把登录动作留给用户

**实现位置：**`psyclaw/psych/paywall.py`、`psyclaw/psych/institution.py`。

**实现方式：**按 LibKey → EZProxy → DOI 出版社页面选择入口。PsyClaw 只打开页面，不读取账号密码；用户登录并点击下载后，`capture_from_downloads` 监控系统下载目录，验证新文件是合法 PDF，再移动到 `outputs/pdfs/` 并规范命名。

**Agent 工具：**`lit_open_institutional`、`lit_capture_pdf`。打开浏览器是副作用，需要审批或显式用户动作。

**进展：已实现 / 已测试；真实机构配置、SSO、下载目录待验收。**

### 3.9 WebBridge 机构库桥接：中文库补覆盖

**实现位置：**`psyclaw/psych/litbridge.py`、`psyclaw/psych/bridge_fetch.py`、`lit_cli.py`。

支持知网、万方、维普三套页面画像。`--bridge` 显式开启后，流程检查二进制、守护进程和浏览器扩展状态，导航到检索页，在用户真实浏览器上下文中执行页面 JS，提取标题、作者、来源和年份，再按统一 schema 合并。

默认中文主题路由三库；英文 WoS/Scopus 仍提示采用交互式浏览器检索或手动导入。桥接失败、页面结构变化或抽取为空时 fail-safe 返回公开 API 结果，并给出安装、启动或手动导入命令。

**进展：已实现 / 已测试（模拟 WebBridge）；真实浏览器扩展和三库页面待验收。**

### 3.10 结果导入：让人工浏览也能回到同一条证据链

**实现位置：**`psyclaw/psych/litmatrix.py::import_results`。

支持 Markdown 表格、CSV、TSV 和 JSON 的字段归一化。缺标题记录跳过；未知字段不猜测；导入记录按 DOI/标题去重，写回 `notes/lit_search.json`，并在 `notes/prisma_search.md` 追加导入痕迹。

**进展：已实现 / 已测试。**

### 3.11 Zotero：复用用户已有文库和已购全文

**实现位置：**`psyclaw/psych/zotero_client.py`。

支持 API key + library id 配置，按关键词检索文库、按 DOI 定位、读取 Zotero 已索引附件全文、按 DOI 从 Crossref 补元数据并添加条目。添加前查重，写入失败不重试，handoff manifest 不包含凭据，并对本地 PDF 记录 SHA-256。

**Agent 工具：**`zotero_search`、`zotero_fulltext`、`zotero_add`。读取工具只读；添加条目属于外部写入副作用，应走审批。

**进展：已实现 / 已测试；真实 Zotero 凭据、文库和附件索引待验收。**

### 3.12 文献矩阵：把题录转成可人工完成的研究表

**实现位置：**`psyclaw/psych/litmatrix.py::build_matrix_md`、`write_matrix`。

矩阵字段包括标题、作者年份、来源、研究对象、研究方法、形式/场景、主要发现、局限和纳入状态。已有题录字段直接填入；摘要或全文无法支持的内容标记“待核查”或“全文未获取”，不由模型猜测。

矩阵使用与合成、引用核验相同的确定性 citation key；生成时同步写 `evidence_map.json`，让矩阵、综述和 cite-check 共用一套证据身份。

**进展：已实现 / 已测试。**

### 3.13 Evidence Map：机器可读的证据中间层

**实现位置：**`psyclaw/psych/synthesize.py::build_evidence_map`。

它为每篇文献生成可消歧 citation key，统计年份范围和 OA 数量，从标题/摘要抽取重复主题词，并建立“主题 → 支持文献键”的映射。参考文献中的 DOI、年份、OA 状态保留回溯信息。

**产物：**`notes/evidence_map.json`，同时渲染到 `notes/lit_review.md` 的证据图谱表。

**进展：已实现 / 已测试。**

**边界：**当前主题抽取是词频/文献频次层面的证据索引，不等于效应方向、研究质量、证据强度或因果结论。

### 3.14 有据综述：模型叙事与确定性骨架分开

**实现位置：**`psyclaw/psych/synthesize.py::synthesize_review`。

- 有真实 Provider 且有检索命中：把证据键和摘要片段作为上下文，要求模型只引用允许键，不编造数值、DOI 或文献。
- 没有 Provider 或没有命中：生成确定性、可追溯的结构骨架，明确标注“LLM 未接入”，不冒充模型综述。
- 模型生成失败：回到确定性骨架，并将 `grounded` 置为 `false`。

**进展：代码已实现 / 离线测试已覆盖；真实 Provider 的 grounded narrative 待验收。**

**产品决策：**无模型时不再默认降级为 MockProvider。确定性骨架是内部的可追溯中间产物，不是虚构模型结果，也不应被宣传为正式综述。

### 3.15 引用核验：独立检查模型是否越过证据边界

**实现位置：**`psyclaw/psych/citations.py`。

`load_allowed` 优先读取 `evidence_map.json`，缺失时从 `lit_search.json` 重建允许键；`audit_citations` 按首位作者姓氏 + 年份比对文内引用；`consistency_check` 双向检查文内引用和参考文献表；未知语料或特殊引用格式时标记人工核验，而不是报“通过”。

**产物：**`notes/citation_audit.json`、`notes/citation_audit.md`。孤儿引用会把 `no_fabricated_citations` 置为 false，可被写作质量 gate 读取。

**进展：已实现 / 已测试。**

**边界：**作者年份粒度能抓住大多数明显杜撰，但不能替代 Crossref/出版社级逐条核验；`cite --verify` 才会进一步请求 Crossref。

### 3.16 同行评审：对综述做独立质量回看

**实现位置：**`psyclaw/review.py::run_review`。

模型扮演 EIC、三位同行评审和 Devil’s Advocate，解析推荐、严重性和行动项，汇总编辑决定，写出回应信骨架；可选 `revise` 将 BLOCKING/MAJOR 意见回灌执行者后复审。

**产物：**`notes/review_panel.md`、`notes/review_panel.json`、`notes/response_letter.md`，修订模式下可能产生 `notes/revised_draft.md`。

**进展：已实现 / 已测试；真实 Provider 下的审稿质量和可用性待验收。**

**产品风险：**在 literature workflow 中该步骤是 optional，评审失败不会阻断主流程。若“可交付综述”必须经过评审，需要把它升级为 required 或增加明确的交付策略。

## 4. Agent 原生工具与 CLI 对照

| 能力 | CLI | Agent/工具层 | 副作用控制 |
|---|---|---|---|
| 公开检索 | `psyclaw lit` | `lit_search` | 只读网络请求 |
| 引用滚雪球 | `--snowball` | `lit_snowball` | 只读网络请求 |
| OA 下载 | `--fulltext` / `--download` | `lit_download` | 写入项目文件，需检查回执 |
| 机构权限 | `auth` / 浏览器 | `lit_open_institutional` | 打开浏览器，需审批 |
| 收取 PDF | 下载目录 | `lit_capture_pdf` | 移动本地文件，需确认路径 |
| Zotero 搜索/全文 | `--zotero` | `zotero_search` / `zotero_fulltext` | 只读 |
| Zotero 添加 | 无完整等价 CLI | `zotero_add` | 外部文库写入，必须审批 |
| 计划/矩阵 | `--plan` / `--matrix` | 可由 Agent 编排 | 主要写入 notes |
| 引用核验 | `cite --verify` | 质量工具调用 | 只读稿件与证据产物 |

原则是 Agent 使用结构化参数和工具回执，CLI 保留人工调试、定位卡点和离线复现入口。

## 5. 证据与测试矩阵

| 功能 | 主要测试 | 当前证据 | 仍缺什么 |
|---|---|---|---|
| Workflow gate/checkpoint/verdict | `tests/test_workflows.py` | fail-closed、暂停、恢复、可选步骤 | 真实长流程重跑 |
| 多源检索/工具注册 | `tests/test_lit_tools.py` | mock 网络回执、参数和错误路径 | 真实 API 网络 |
| 初筛 | `tests/test_workflows.py` | 相关/不相关、全排除降级、空语料 | 中文跨语言人工验收 |
| 合成/Evidence Map | `tests/test_synthesize.py` | 键消歧、有据/骨架/失败回退 | 真实 Provider 叙事质量 |
| 机构库桥接 | `tests/test_litbridge.py` | 三库画像、解析、合并、不可用降级 | 真实扩展和页面结构 |
| 全文与付费墙 | `tests/test_lit_tools.py`, `tests/test_paywall_handoff.py` | OA、PDF 魔数、handoff、下载收取 | 真实机构登录和出版社 |
| 文献矩阵 | `tests/test_litmatrix.py` | 导入、去重、待核查字段、Evidence Map 同源 | 大规模人工矩阵 |
| 引用核验 | `tests/test_citations.py` | 孤儿、无语料、双向一致性、sidecar | 复杂引用格式与 Crossref |
| Zotero | `tests/test_zotero_manage.py` | 查重、写入失败保护、handoff hash | 真实文库和权限 |

建议执行的窄范围回归：

```powershell
python -m pytest -q tests/test_workflows.py tests/test_lit_tools.py tests/test_litmatrix.py tests/test_litbridge.py tests/test_paywall_handoff.py tests/test_synthesize.py tests/test_citations.py tests/test_zotero_manage.py
```

## 6. 当前进展结论

### 已完成

1. 文献 workflow 的声明式步骤、gate、检查点和总验收已经形成。
2. 公开多源检索、统一题录、去重和 PRISMA identification 已形成。
3. 检索计划、机构库导入、中文三库 WebBridge 路线已经产品化。
4. 合规 OA、机构权限 handoff、用户下载收取和 Zotero 路线已经实现。
5. 文献矩阵、Evidence Map、确定性骨架和引用核验已经形成可追溯链路。
6. 文献相关离线测试覆盖了主要纯函数、错误路径和工具注册。

### 部分完成

1. 自动初筛只能做题录级内容词相关性判断，仍需人工筛选和理由记录。
2. Evidence Map 记录的是主题和题录证据关系，不包含效应方向、质量评级和证据强度。
3. grounded synthesis、同行评审依赖真实 Provider，离线测试不能证明文本质量。
4. `review` 目前是可选步骤，正式交付是否阻断尚未定案。

### 待验收与优先级

| 优先级 | 事项 | 验收条件 |
|---|---|---|
| P0 | 真实 Provider 跑完整 literature 教程 | 有命令记录、耗时、每步产物、首个阻塞点和 workflow verdict |
| P0 | 修复 Workflow/CLI 默认来源差异 | 两条入口共享 `DEFAULT_SOURCES`，测试验证 Crossref 被纳入 |
| P1 | 真实 WebBridge + 知网/万方/维普 | 登录、导航、抽取、合并、失败提示均人工确认 |
| P1 | 真实机构权限和 Zotero | 不泄露凭据，全文和写入回执可追溯 |
| P1 | 定义 review 是否阻断交付 | 明确 required/optional 和用户可见交付规则 |
| P2 | 双人筛选、全文资格审查、排除原因表 | 支持研究者复核、冲突记录和最终 PRISMA 数字 |

## 7. 推荐验收路径

```powershell
# 1. 检查环境与 Provider
python -m psyclaw doctor

# 2. 先生成检索计划，不依赖真实模型也可得到模板
python -m psyclaw lit "正念训练对大学生考试焦虑的干预效果" --plan

# 3. 单独验证公开检索与落盘
python -m psyclaw lit "正念训练对大学生考试焦虑的干预效果" --sources openalex,crossref,europepmc --limit 10

# 4. 生成矩阵，再人工补齐纳入、方法、主要发现和局限
python -m psyclaw lit --matrix "正念训练对大学生考试焦虑的干预效果"

# 5. 配置真实 Provider 后再跑正式流程
python -m psyclaw run literature "正念训练对大学生考试焦虑的干预效果"

# 6. 流程中断后恢复，不重复已完成步骤
python -m psyclaw run literature "正念训练对大学生考试焦虑的干预效果" --resume
```

每次验收至少检查 `notes/lit_search.json`、`notes/prisma_search.md`、`notes/prisma_flow.md`、`notes/evidence_map.json` 和 `notes/workflow_summary.json`，不要只依据终端的“完成”提示。
