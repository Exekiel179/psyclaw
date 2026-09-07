# PsyClaw 使用白皮书

**版本：v0.29.13**
**发布日期：2026-09-07**
**适用对象：社会科学研究者、教师和研究助理**

## 1. 文档定位

本文是 PsyClaw 0.29.13 的用户指南，面向社会科学研究者、教师和研究助理。PsyClaw 用于组织研究目标、证据、分析委托、写作和复核过程；它不替代研究者的判断，不替代 Python、R、SPSS、Stata、Mplus 等统计工具，也不保证模型输出自动正确。

## 2. 安装与启动

运行要求：Node.js `>=22.19.0`。

```bash
npm install -g psyclaw@0.29.13
psyclaw --help
psyclaw
```

首次启动会引导配置模型服务。不要把 API Key 写入命令参数、项目文件或 Git 仓库。

## 3. 创建第一个研究项目

```bash
mkdir my-study
cd my-study
psyclaw init "社交支持与研究生心理健康的关系" --paradigm survey-observational
psyclaw
```

也可以进入对话后使用：

```text
/init 社交支持与研究生心理健康的关系
```

初始化会建立项目目录、`psyclaw.md` 和 `.psyclaw/` 状态目录。原始数据放入 `data/raw/` 后视为只读；经过确认的派生数据放入 `data/clean/`。

## 4. 三种模式

- `chat`：普通对话。可以直接用自然语言请求资料整理、分析、写作或研究建议。
- `analysis`：研究问题澄清、分析方案、可复现脚本、统计委托和分析报告。
- `academic`：文献研究、论文写作、格式完善和同行评审。

使用 `Shift+Tab` 循环切换模式；使用 `Ctrl+Shift+T` 调整思考深度。

## 5. 推荐工作流

### 5.1 明确研究问题

在 `analysis` 模式说明研究对象、研究问题、变量、数据格式、研究范式和期望产出。问题不完整时，PsyClaw 会先提出可回答的问题，而不是直接假定一个结论。

### 5.2 形成分析方案

```text
/plan new 社交支持是否与心理健康相关，以及哪些变量可能解释这种关系
/plan status
/plan confirm <分析方法>
/plan review
/plan run
```

`/plan auto` 可以跳过逐项人工确认，但由此产生的结果必须明确标记为未经人审批。

### 5.3 执行与复现

统计计算由成熟外部工具执行。PsyClaw 负责保存分析脚本、输入关系、运行环境、结果哈希和报告要求。不要把模型生成的数字当作真实统计结果。

### 5.4 核对

当模型需要用户在多个方案中选择、确认下一步或勾选项目时，应通过唤醒选项提供结构化选择：

- 单选：`mode=choice`
- 多选或核对清单：`mode=checklist`

用户也可以直接输入编号、名称或文字回应。回应应被规范化并记录原文、最终选项、上下文、时间和来源。使用：

```text
/crosscheck list
/crosscheck <id> verified
/crosscheck skip
```

只有模型实际调用核对清单工具时，才会生成对应清单记录；没有调用时，清单保持为空。

### 5.5 进入学术写作

分析完成后先生成 `analysis/HANDOFF.md`，再切到 `academic`。论文 Markdown 写入 `paper/`，脚本写入 `analysis/scripts/`，结果写入 `analysis/results/` 或 `analysis/outputs/`。

## 6. 全部可用命令

| 命令 | 用途 |
|---|---|
| `/init` | 初始化研究项目和工作区 |
| `/plan` | 创建、查看、确认、运行、推迟或交接分析方案 |
| `/crosscheck` | 管理交叉核验清单；`/verify` 是别名 |
| `/grill` | 对研究问题、设计、方法和论证进行压力测试 |
| `/review` | 运行多角色模拟同行评审，不自动改稿 |
| `/loop` | 有界推进一个研究阶段；`/loop stop` 请求停止 |
| `/agents` | 浏览或运行内置、项目级协作智能体 |
| `/panel` | 打开科研工作台 |
| `/help` | 打开使用速览 |
| `/skill` | 查看、启用、停用或安装技能 |
| `/skill:<name>` | 调用指定技能 |
| `/ars` | 切换学术模式或管理 ARS 流程 |
| `/ars-full <task>` | 启动完整学术研究流程 |
| `/mcp` | 管理外部工具服务 |
| `/plugin` | 管理扩展 |
| `/provider` | 查看或切换模型服务提供方 |
| `/pet on|off|status` | 管理启动横幅宠物 |
| `/export` | 使用内置功能导出会话 |
| `/create-skill` | 创建项目级技能，先预览再确认 |
| `/create-hook` | 创建分析生命周期 Hook |
| `/create-rule` | 创建项目级附加规则 |
| `/create-subagent` | 创建项目级协作智能体 |
| `/model` | 列出或切换模型；需开发命令启用 |
| `/handoff` | 生成交接检查点；需开发命令启用 |

## 7. 项目目录

```text
paper/                 论文和报告 Markdown
literature/pdfs/       合法取得并核验的论文全文
data/raw/              原始数据，只读
data/clean/            清洗后可分析数据
analysis/scripts/      可复现脚本
analysis/results/      数值结果与表图
analysis/HANDOFF.md    analysis 到 academic 的交接
.psyclaw/              项目状态、证据、运行、核对和审计记录
```

## 8. 证据与写作原则

- DOI 或题录只能证明文献存在，不能自动证明方法、结果或因果结论。
- 具体数值必须来自真实分析产物，不能由模型补写。
- 冲突证据必须并列披露，不能只保留有利方向。
- 探索性与确证性分析分开表述。
- 质性研究不因缺少效应量而被判定为无效，但应保留编码轨迹、反身性和反例。
- 没有定位、来源或必要产物时，使用不确定或阻断状态。

## 9. 安全边界

PsyClaw 默认发现而不执行外部 Skill、MCP 和 Plugin。启用前应检查来源、版本、引用、哈希、许可证、依赖和信任状态。系统拒绝写入原始数据、凭据、`.git` 和符号链接逃逸目标。应用层门禁不是操作系统级沙箱；敏感数据和高风险插件仍需更强隔离。

## 10. 排错

- `psyclaw --help`：确认命令入口。
- `psyclaw --continue` 或 `psyclaw -c`：续接最近会话。
- `/ars doctor`：检查学术模式入口。
- `/panel`：查看项目文件、运行快照和能力状态。
- 模型服务异常：先检查 Provider 配置和网络，再检查具体 Skill/MCP 的来源与依赖。

## 11. 不应作出的承诺

通过门禁只表示通过当前合同检查，不表示研究结论真实、因果关系成立、论文一定可发表或统计结果一定正确。正式研究仍需要研究者复核、方法学审查和适用的伦理程序。
