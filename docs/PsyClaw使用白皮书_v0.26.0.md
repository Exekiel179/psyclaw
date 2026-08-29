# PsyClaw 使用白皮书

**版本：v0.26.0**
**发布日期：2026-08-24**
**适用对象：社会科学研究者、研究助理、方法学顾问与课题组负责人**

## 摘要

PsyClaw 是建立在官方 Pi runtime 之上的社会科学研究工作台。它把研究目标、来源材料、Claim-Evidence 关系、完整性门禁、人工裁决、交接记录和工作流状态放进一个可审计的项目结构。它的任务是让过程可追溯，而不是把模型生成的话当成研究事实。

PsyClaw 不在核心中实现统计学算法。描述、检验、建模和图表计算应委托成熟 Python/R 库、SPSS、Stata、Mplus 或经审查的 MCP；每次结果都应能回到输入、脚本、环境和证据来源。

## 1. 安装与首次启动

### 1.1 环境要求

需要 Node.js `22.19.0` 或更高版本。运行 `node --version` 可确认。PsyClaw 支持 Windows、macOS 和 Linux；发行基线为 Node 22 LTS。

### 1.2 安装 PsyClaw

官方 npm 源：

```powershell
npm install -g psyclaw@0.26.0
```

中国大陆网络环境可使用镜像：

```powershell
npm install -g psyclaw@0.26.0 --registry=https://registry.npmmirror.com
```

确认命令入口：

```powershell
psyclaw --help
```

出现帮助界面表示 npm 全局目录已在 PATH 中。若 PowerShell 找不到命令，重开终端后重试；仍失败时运行 `npm prefix -g`，确认 npm 的全局目录在 PATH 中。

### 1.3 配置模型并开始对话

直接运行：

```powershell
psyclaw
```

首次没有模型配置时会进入向导。也可以主动运行：

```powershell
psyclaw wizard
psyclaw setup --provider deepseek
```

模型凭据由 Pi 的本地认证配置管理。不要把 API key 粘贴到研究笔记、项目文件、白皮书、聊天导出或 Git 仓库。

## 2. 创建研究项目

每项研究使用独立目录。以下示例建立横断面问卷项目：

```powershell
mkdir social-support-study
cd social-support-study
psyclaw init "社会支持与研究生心理健康的关系" --paradigm survey-observational
```

可用范式如下：

| 范式 | 标识 |
| --- | --- |
| 问卷或观察研究 | `survey-observational` |
| 质性主题分析 | `qualitative-thematic` |
| 实验研究 | `experimental` |
| 准实验 | `quasi-experimental` |
| 纵向面板 | `longitudinal-panel` |
| 元分析 | `meta-analysis` |
| 民族志 | `ethnographic` |
| 历史或文献档案 | `historical-documentary` |
| 政策或法律研究 | `policy-legal` |
| 混合方法 | `mixed-methods` |

项目初始化创建以下目录：

```text
.psyclaw/      项目状态、证据账本、运行记录、审计与 manifest
data/raw/       原始数据，只读保护
data/clean/     经确认可用于分析的派生数据
notes/          研究笔记、交接、人工决策与方法说明
outputs/        通过工作流门禁的交付物
```

`data/raw/`、`.git/`、凭据文件与符号链接目标不能由 PsyClaw 写入。资料是否能发送给外部模型仍由研究者依据伦理、知情同意与数据管理协议决定。

## 3. 对话、人工裁决与交接

### 3.1 对话优先

启动 `psyclaw` 后直接描述研究目标。例如：

```text
我准备做一项有关社交支持和抑郁的问卷研究。请先指出研究问题、样本和因果解释上还缺什么。
```

尚不需要写入、下载或建立运行记录时，系统保持对话模式。需要可审计产物、证据记录、人工批准或可恢复运行时，PsyClaw 才进入相应工作流。

### 3.2 人工决定

研究者必须确认资料是否可共享、外部安装、网络下载、发布、数据处理规则和模型输出是否能进入项目结论。PsyClaw 应提供计划、风险与下一步，而不是自行跨过这些决定。

创建人工裁决记录模板：

```powershell
psyclaw hitl init
```

为下一次会话写可核验的项目交接：

```powershell
psyclaw handoff
```

## 4. 证据、Claim 与离线简报

### 4.1 登记本地证据

登记本地材料时，系统记录路径、哈希、时间和证据等级：

```powershell
psyclaw evidence add notes\literature-notes.md --level user
psyclaw evidence add notes\article-extract.md --level fulltext
```

`fulltext` 不等于自动支持任何结论。具体数值、方法或因果 Claim 仍需要精确定位、可追溯 Artifact 或独立核验。

### 4.2 生成离线证据简报

在项目与材料已准备好时执行：

```powershell
psyclaw brief
```

简报固定经过研究 intake、材料 capture、Claim-Evidence ledger、完整性 audit、brief 与 handoff。证据不足、存在未处理冲突或缺少定位信息时，结果会被阻断或标记为不确定，而不是生成貌似完整的结论。

## 5. 科研工作台面板

在 PsyClaw 对话中输入：

```text
/panel
```

系统会启动仅绑定 `127.0.0.1` 的本地工作台并在浏览器中打开。面板展示项目状态、运行事件、产物、模型配置、推荐 Skill/MCP 与人类决策入口。

面板浏览器助手在单独的只读 Pi RPC 进程中运行，只开放 `read`、`grep`、`find` 与 `ls`。它的内部约束不会作为聊天消息显示；聊天记录只保留用户问题和助手答复。

## 6. Skills、MCP 与外部 Agent

### 6.1 内置核心 Skill

PsyClaw 随包提供四个核心 Skill：

1. `research-intake`：明确研究目标、范式、范围与未决问题。
2. `evidence-capture`：登记和定位来源材料。
3. `citation-audit`：检查 Claim、引用与证据不足处。
4. `research-brief`：基于已通过的材料组织简报。

系统只在合适阶段加载核心 Skill，并向用户显示当前使用的 Skill。第三方 Skill 默认仅被发现，不会自动执行。

### 6.2 推荐 Skill 与 MCP

在对话中使用：

```text
/skills
/mcp
/install skill <id>
/install mcp <id>
```

“发现”不等于“可执行”。启用前需审查来源、版本/ref、哈希、许可证、依赖和信任状态。MCP 使用受控 stdio 通道；外部服务的环境变量只注入它自己的子进程，不能在聊天或日志中显示值。

### 6.3 扫描与导入其他 Agent 的 Skill

只读扫描本机已安装的 Agent：

```powershell
psyclaw agents
```

生成或执行安装计划、或导入允许的 Skill 时，需要显式确认：

```powershell
psyclaw install <agent-id> --yes
psyclaw import <agent-id> --yes
```

导入过程保留来源与 SHA-256 溯源，且不会读取或复制凭据内容。

## 7. 分析、写作与发表产物

### 7.1 分析委托而非内置统计

PsyClaw 负责分析任务的设计、证据、脚本约定、输入哈希和结果验收；统计计算由成熟工具完成。可在对话中提出：

```text
请为 data/clean/survey.csv 设计多元回归分析，先检查变量映射、缺失处理、混杂因素、效应量与置信区间应如何报告；不要直接编造统计结果。
```

真正执行分析时，应保存分析脚本、依赖和环境版本。没有真实 Artifact 支撑的统计数值不得视为完成结果。

### 7.2 文献综述、全文与元分析

对于文献综述、合法全文获取、专家审稿、写作审查和元分析，优先在对话中说明目标。PsyClaw 会在需要网络访问、机构登录、外部工具、长文献核验或生成 DOCX 前说明成本并请求确认。它不会绕过付费墙、验证码或机构认证。

元分析只生成或委托真实 effect-size 数据与统计运行；没有满足数据契约时，系统只能报告缺口与下一步，不能虚构 I2、Egger 检验或森林图结论。

### 7.3 手稿与引用

写作的原则是证据先于正文。需要稿件、引用或 DOCX 时，先明确来源、引用格式和目标期刊要求；每个文内引用需要记录 DOI、引用理由与所在语境。生成 DOCX 前应先审阅 Markdown 分析稿，并由研究者确认格式需求。

## 8. 更新、版本与开发

### 8.1 检查更新

```powershell
psyclaw check-updates
```

该命令只检查版本和生态状态，不修改本地环境。

### 8.2 更新 PsyClaw 和内置 Pi

```powershell
psyclaw update
psyclaw update --check
```

`psyclaw update` 默认升级 PsyClaw 整包，同时安装该版本锁定、验证过的内置 Pi，并在同一回执中报告两者的更新结果。只想查看更新计划时使用 `--check`。它不会影响系统中单独安装的 Pi，也不会自行组合未经 PsyClaw 版本验证的 Pi。源码仓库中会拒绝自覆盖，开发者应通过 Git 同步后重新构建。旧的 `--yes` 参数仍兼容，但不再需要。

### 8.3 手动升级 PsyClaw

```powershell
npm install -g psyclaw@latest
```

国内镜像：

```powershell
npm install -g psyclaw@latest --registry=https://registry.npmmirror.com
```

### 8.4 从源码开发

```powershell
git clone https://github.com/Exekiel179/psyclaw.git
cd psyclaw
pnpm install
pnpm build
npm link
psyclaw --help
```

开发阶段直接修改源码并构建；不要使用 `psyclaw update` 试图同步仓库代码。

## 9. 常见问题

### `psyclaw` 找不到

确认 `npm install -g` 已成功，关闭并重新打开终端，再运行 `npm prefix -g` 检查全局 npm 目录。Windows 通常需要将该目录加入 PATH。

### 出现旧 Python 的 `ModuleNotFoundError`

PATH 中可能仍优先指向旧版 Python `psyclaw.exe`。运行以下命令查看解析顺序：

```powershell
Get-Command psyclaw -All
where.exe psyclaw
```

确保 npm 的 `psyclaw.cmd` 位于前面，再重新打开终端并执行：

```powershell
npm uninstall -g psyclaw
npm install -g psyclaw@0.26.0
psyclaw --help
```

若 Python 卸载器提示没有可卸载文件，不要删除不明目录；先用上面的定位结果确认旧 `psyclaw.exe` 所属环境，再在该环境中处理。

### 横幅显示不完整或出现 `wideBannerVariants` 重复声明

升级到 `psyclaw@0.26.0`。该版本的横幅重写器是幂等的，重复构建不会追加同名声明；窄终端自动选择完整、不并排吉祥物的布局。

### 是否应运行 `psyclaw update`

全局安装用户直接运行 `psyclaw update` 即可升级 PsyClaw 和内置 Pi；`npm install -g psyclaw@latest` 仅作为手动备选方式。本地开发者通过 Git 同步源码并重新构建。

## 10. 可信使用清单

在把结果用于研究决定、论文或对外沟通前，确认：

1. 研究目标、范式、样本与伦理边界已由研究者确认。
2. 每条事实性 Claim 有来源、等级与可定位依据；不确定内容已明确标注。
3. 数据处理、剔除、变量映射和模型规格均已记录并经人工复核。
4. 统计数值来自真实脚本或外部软件运行，不是模型生成。
5. 每项外部写入、下载、安装或发表行为有审批与 receipt。
6. 手稿中的引用、图表和结论由作者最终负责并完成复核。

---

PsyClaw v0.26.0 · MIT License · https://github.com/Exekiel179/psyclaw
