# PsyClaw — 心理学研究全流程 Agent CLI · 设计稿 v0.1（历史）

> ⚠️ **重定位说明（2026-06，务必先读）**
> 本文件是 **v0.1 历史设计稿**，记录的是**重定位前**的愿景（把统计计算当作核心内置能力）。
> **现状已变**：PsyClaw 已从「全流程统计 CLI」重定位为「纯研究**编排** harness」——
> **统计计算整体外移到成熟库/MCP，本仓不内置、不 import 任何统计库，也不重实现任何统计算法**。
> 因此下文中一切「内置统计 / ARS-Stat 跑分析 / r-mcp·pystat 主路径内算 / `/stat` 自动跑检验」
> 的描述**均已作废**——统计改为由 meta/analysis 流程**生成委托 scipy/pingouin/statsmodels 的
> 可复现脚本**（交 `[stats]` 环境或 MCP 运行），或直接用 SPSS/MNE/Mplus/Stata 等 MCP 服务器。
> 架构层次、HITL 回路、Gates、图表规范、项目布局等**非统计**设计仍大体有效。
> **当前真源**：状态 = `feature_list.json`；人读快照 = `progress.md`；计划 = `TODO.md`；命令集 = `docs/COMMANDS.md`。

> **一句话定位（原）**：把 AutoResearchClaw 的自主研究流水线，特化成一个**心理学研究专用、可复现优先、质量检查内置**的交互式命令行智能体。
>
> Chat an idea → 文献调研 · 实验设计 · 统计分析 · 论文写作，全程受 `PSYCLAW.md` 学术规范约束。
> （注：「统计分析」现指**编排 + 生成可复现脚本**，不在本仓内计算。）

本文件是**设计稿**，不含实现逻辑。配套交付一个**可运行的最小骨架**（见 `README.md` 与 `psyclaw/`）。

---

## 0. 设计契约（已与你逐条确认）

| # | 决策点 | 结论 | 理由 |
|---|--------|------|------|
| 1 | 代码基座 | **Fork AutoResearchClaw（Python）** | 已有 OpenClaw 集成、MCP 层、skills 加载器、pipeline、HITL、config —— 复用最大化 |
| 2 | ARS 的含义 | **Academic Research Skill** = 端到端学术研究 skill（文献→设计→统计→写作总编排） | 不是单纯统计，也不是整条 pipeline，而是可被 REPL 调用的研究总管 |
| 3 | 统计后端 | **R/Python 主路径，SPSS/Mplus/Stata 为可选插件** | 开源栈保证人人可复现；商业软件检测到本地安装才启用 |
| 4 | 交互骨架 | **REPL 对话为主 + pipeline 作为 `/research` 命令** | 既能 claude-code 式对话，又能一键跑完整研究 |
| 5 | 学术规范 | **`PSYCLAW.md` 规范 + 机器可执行的质量检查（gates）** | 规范不只是文档，也能自动标记不合规输出 |
| 6 | 本轮交付 | **设计文档 + 可运行最小骨架** | 先验证骨架，再填实现 |

---

## 1. 同类系统的取舍（为什么这样设计）

| 参考系统 | 我们借鉴什么 | 我们不照搬什么 |
|----------|--------------|----------------|
| **Claude Code**（TS/Bun/Ink 快照） | REPL 架构、slash 命令、Tool/Skill 抽象、`@文件` 引用、流式输出、`/init` 引导、hooks | 不用 TS/Bun —— 心理学统计生态在 Python/R，跨语言桥接成本太高 |
| **Codex CLI** | 非交互 `exec` 模式、审批策略（auto/suggest）、沙箱执行 | 不做代码托管侧的全自动提交 |
| **OpenClaw / OpenCode** | provider 抽象、`opencode` 后端复用（ARS 已集成）、本地优先 | —— |
| **AutoResearchClaw** | 23 阶段 pipeline、skills 加载器、MCP registry、HITL gate、config.yaml | 通用科研 → 收窄为心理学；学术规范从「建议」升级为「自动质量检查」 |
| **Hermes（函数调用/工具规范）** | 统一的工具调用协议、结构化 schema | —— |

**核心差异化**：通用科研 Agent 给你「一篇能跑的论文」；PsyClaw 给你「一篇**经得起心理学审稿**的论文」—— 预注册、效应量、可复现脚本、APA7、不 p-hacking，全部纳入机器质量检查，不达标就明确报告。

---

## 2. 总体架构

```
┌─────────────────────────────────────────────────────────────────┐
│  psyclaw  (entry point)                                          │
│  ┌──────────────┐   ┌──────────────────────────────────────────┐ │
│  │ REPL (默认)  │   │ 非交互子命令                              │ │
│  │ 对话式终端   │   │ run / research / doctor / config / mcp …  │ │
│  └──────┬───────┘   └──────────────────┬───────────────────────┘ │
│         │  slash 命令 / @文件 / skill 触发                        │
│  ┌──────▼──────────────────────────────────────────────────────┐ │
│  │                  Agent Core (Orchestrator)                   │ │
│  │   QueryEngine · ToolRegistry · SkillRouter · ContextManager  │ │
│  └──┬──────────┬───────────┬───────────┬───────────┬───────────┘ │
│     │          │           │           │           │             │
│  ┌──▼───┐ ┌────▼────┐ ┌────▼─────┐ ┌───▼────┐ ┌────▼──────┐      │
│  │Skills│ │  MCP    │ │ Gates    │ │ Config │ │ Providers │      │
│  │ 层   │ │ 层      │ │ 质检层   │ │ 向导   │ │ (LLM)     │      │
│  └──┬───┘ └────┬────┘ └──────────┘ └────────┘ └───────────┘      │
│     │          │                                                 │
│  ┌──▼──────────▼─────────────────────────────────────────────┐  │
│  │  ARS — Academic Research Skill (端到端研究总编排)          │  │
│  │  literature → design → stats(ARS-Stat) → writing          │  │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  全程被 PSYCLAW.md 规范约束，Gates 在每个产出点校验             │
└─────────────────────────────────────────────────────────────────┘
```

### 2.1 模块清单（fork 后的目录）

```
psyclaw/
├── __main__.py          # python -m psyclaw 入口
├── cli.py               # 命令注册 + REPL 启动（复用 ARS argparse 骨架）
├── repl.py              # 交互式终端（slash 命令、@文件、流式）  [fork claude-code REPL 思路]
├── config.py            # 交互式环境变量/配置向导（复用 ARS config + wizard）
├── providers/           # LLM provider 抽象（复用 ARS llm/，OpenClaw 后端）
├── agent/               # QueryEngine / ToolRegistry / ContextManager（复用 ARS pipeline core）
├── skills/
│   ├── loader.py        # agentskills.io 兼容加载器（直接复用 ARS skills/loader.py）
│   ├── router.py        # 描述匹配触发（复用 ARS matcher.py）
│   └── ars/             # ★ 内置 ARS skill（本项目灵魂）
│       ├── SKILL.md
│       └── subskills/   # literature / design / stat / writing 子技能
├── mcp/
│   ├── registry.yaml    # ★ 心理学 MCP 服务器目录（SPSS/Mplus/Stata/Zotero/文献搜索）
│   ├── client.py        # MCP 客户端（复用 ARS mcp/client.py）
│   └── manager.py       # 启用/禁用/健康检查/能力探测
├── gates/
│   ├── PSYCLAW.md       # ★ 统一学术智能体规范（人读 + 机器读）
│   ├── rules.yaml       # 质量规则（结构化，机器校验）
│   └── checker.py       # 质量检查执行器（lint 产出、标记违规）
└── commands/            # slash 命令实现（/research /stat /lit /design /write /init …）
```

带 ★ 的是相对 ARS 的**新增/重写**部分；其余是**直接复用或薄改**。

---

## 3. 命令集（兼容 claude code / codex 主流命令）

REPL 内用 `/前缀`，shell 里用子命令。两套等价。

### 3.1 通用命令（对齐 claude-code / codex）

| 命令 | claude-code/codex 对应 | 作用 |
|------|----------------------|------|
| `psyclaw`（无参） | `claude` | 进入 REPL 交互模式 |
| `psyclaw "<prompt>"` | `claude "<p>"` | 单轮非交互执行 |
| `psyclaw exec <prompt>` | `codex exec` | 脚本/CI 模式，无 TTY |
| `/init` | `/init` | 扫描当前研究项目，生成 `PSYCLAW.md` 项目规范 |
| `/help` | `/help` | 命令与 skill 列表 |
| `/model` | `/model` | 切换 LLM provider/模型 |
| `/skills` `/skill <name>` | `/skills` | 列出 / 调用 skill |
| `/mcp` | `/mcp` | MCP 服务器状态与开关 |
| `/clear` `/compact` | 同名 | 清空 / 压缩上下文 |
| `/cost` | `/cost` | token 与花费统计 |
| `@<file>` | `@<file>` | 把数据集/PDF/脚本拉进上下文 |
| `--approval suggest\|auto` | codex 审批策略 | 工具执行的人工审批级别 |

### 3.2 心理学研究专属命令

| 命令 | 作用 | 背后 |
|------|------|------|
| `/research <topic>` | 跑完整 ARS 流水线（文献→设计→统计→写作） | ARS skill 总编排 |
| `/lit <query>` | 文献检索 + 筛选 + 知识抽取（PRISMA 流程） | 文献 MCP + lit 子技能 |
| `/design` | 实验设计（被试间/内、功效分析、样本量、预注册草案） | design 子技能 |
| `/stat @data.csv` | ~~**ARS-Stat**：自动选检验→跑分析→APA7 结果~~ **（已作废：不在仓内算）** → 现由 analysis/meta 流程**生成**委托 pingouin/statsmodels 的可复现脚本 | 外部 `[stats]`/MCP |
| `/write <section>` | 按 APA JARS 写作（intro/method/results/discussion） | writing 子技能 |
| `/preregister` | 生成 OSF/AsPredicted 预注册模板 | gates + design |
| `/reproduce` | 从产出脚本一键复跑，核对结果一致性 | gates checker |
| `/cite` | Zotero 引文核对、撤稿检查 | Zotero MCP + scite |

---

## 4. ARS — Academic Research Skill（项目灵魂）

ARS 是一个 **agentskills.io 兼容的 SKILL.md**，但内部是一个**子技能编排器**，对应心理学研究四象限：

```
ARS (Academic Research Skill)
├── literature  文献调研   →  检索策略 · PRISMA 筛选 · 知识抽取 · 综述
├── design      实验设计   →  假设 · 变量 · 设计类型 · 功效分析 · 样本量 · 预注册
├── stat        统计分析   →  ARS-Stat：选检验 · 假设检查 · 跑分析 · APA7 · 复现脚本
└── writing     论文写作   →  APA JARS 结构 · 图表 · 引文 · 审稿模拟
```

### 4.1 ARS-Stat 子技能（统计是心理学的命门）

> ⚠️ **本节已作废（统计外移）**：PsyClaw **不在仓内跑分析**。下述「跑分析（pingouin/statsmodels/
> lavaan/lme4）」的决策流仅存为历史设计;现状是 analysis/meta 流程**只生成**委托这些外部库的
> **可复现脚本**（交 `[stats]` 环境或 MCP 运行、结果回填），本仓零统计库依赖。假设诊断/效应量+CI/
> 复现脚本等**规范质量检查仍在**（供写作产出与外部统计结果对照）。

输入：数据集 + 研究假设。输出：APA7 结果段 + 图 + **可独立运行的复现脚本**（`.R` / `.py`）。

决策流（受 PSYCLAW gates 约束）：

```
数据 + 假设
  → 测量层级/分布诊断（正态、方差齐性、缺失、异常值）
  → 自动建议检验族（t / ANOVA / 回归 / 混合模型 / SEM / 中介调节）
  → [GATE] 假设检查未过 → 提示稳健替代（Welch / 非参 / bootstrap），不静默套用
  → 跑分析（主路径 Python pingouin/statsmodels + R lavaan/lme4）
  → 必跑效应量 + 置信区间（Cohen's d / η² / r / OR …）  ← 机器质量检查强制
  → APA7 格式化结果 + 图（matplotlib/seaborn 或 ggplot）
  → 输出复现脚本 + 数据指纹（hash），供 /reproduce 核验
```

商业软件可选路径：检测到本地 `mplus` → SEM 走 Mplus；检测到 SPSS/Stata → 生成对应语法并可驱动执行。未检测到则透明回落开源栈。

### 4.2 SKILL.md 规格（骨架已落地于 `psyclaw/skills/ars/SKILL.md`）

遵循 ARS 现有 schema：`name` / `description`（触发匹配用）/ `category: domain` / `metadata`（子技能映射、所需 MCP、关联 gates）。

---

## 5. MCP 层（心理学工具目录）

`psyclaw/mcp/registry.yaml` 定义可插拔 MCP 服务器。**交互式启用**：`psyclaw config` 向导逐个询问是否启用并采集所需环境变量。

| MCP | 类别 | 启用条件 | 提供能力 |
|-----|------|----------|----------|
| **spss-mcp** | 统计（可选） | 检测到本地 SPSS | 跑 .sav、生成语法、输出表 |
| **mplus-mcp** | 统计（可选） | 检测到本地 Mplus | SEM / CFA / 潜变量 / 增长模型 |
| **stata-mcp** | 统计（可选） | 检测到本地 Stata | 面板/计量、do 文件 |
| ~~**r-mcp / pystat**~~ | 统计 | **已作废：非内置** | 统计外移后无「内置统计主路径」;脚本交外部 `[stats]`/MCP 跑 |
| **zotero-mcp** | 文献管理 | Zotero API key | 文库检索、引文、撤稿检查（scite） |
| **lit-search-mcp** | 文献检索 | 可配多源 | PubMed / PsycINFO / Semantic Scholar / OpenAlex / arXiv |
| **osf-mcp** | 开放科学（可选） | OSF token | 预注册、数据托管 |

> 你环境里已连接的 `zotero` MCP（含 scite 撤稿检查、语义检索）可直接挂进来作为 zotero-mcp 实现。

### 5.1 交互式环境变量设置

`psyclaw config`（或 REPL 内 `/config`）启动向导：

```
$ psyclaw config
PsyClaw 配置向导
─────────────────
LLM Provider [openclaw/anthropic/openai/custom]: anthropic
  API Key: ******** (写入 ~/.psyclaw/.env，不入库)
启用 Zotero MCP? [Y/n]: Y
  ZOTERO_API_KEY: ********
  ZOTERO_LIBRARY_ID: 123456
启用 文献检索 MCP? [Y/n]: Y
  数据源 [pubmed,semantic-scholar,openalex]: openalex,semantic-scholar
检测本地统计软件… 找到 Mplus ✓ / 未找到 SPSS / 未找到 Stata
  启用 Mplus MCP? [Y/n]: Y
配置已写入 ~/.psyclaw/config.yaml  ·  密钥写入 ~/.psyclaw/.env
运行 `psyclaw doctor` 自检。
```

层级：环境变量 > `~/.psyclaw/.env` > `~/.psyclaw/config.yaml` > 项目 `./psyclaw.yaml`。

---

## 6. PSYCLAW.md — 统一学术智能体规范 + 机器质量检查

两层结构：

1. **`gates/PSYCLAW.md`** —— 人读规范 + 注入 agent 的 system 约束（研究诚信原则）。
2. **`gates/rules.yaml`** —— 机器可校验规则；`gates/checker.py` 在每个产出点执行，不达标**阻断**并给修复建议。

质量检查示例（详见骨架文件）：

| Gate ID | 触发点 | 规则 | 不过怎么办 |
|---------|--------|------|-----------|
| `STAT.effect_size` | 统计产出 | 每个显著性检验必须报告效应量 + CI | 阻断，自动补算 |
| `STAT.assumptions` | 跑检验前 | 正态/方差齐性/独立性已诊断 | 阻断，提示稳健替代 |
| `STAT.no_phack` | 分析过程 | 禁止未声明的多重比较/择优报告 | 警告 + 记录到审计日志 |
| `DESIGN.power` | 实验设计 | 样本量由先验功效分析得出 | 阻断，要求功效分析 |
| `DESIGN.prereg` | 确证性研究 | 有预注册或明确标注探索性 | 阻断或强制改标探索性 |
| `WRITE.apa7` | 论文产出 | 引用/数字/表格符合 APA7 | 阻断，自动修正 |
| `LIT.prisma` | 文献综述 | 检索/筛选符合 PRISMA 流程图 | 提示补全流程 |
| `REPRO.script` | 任何统计结论 | 附可独立运行的复现脚本 + 数据指纹 | 阻断 |

`psyclaw gates check <artifact>` 可单独运行质量检查；CI 中作为质量检查步骤。

---

## 7. HITL 回路 + 多智能体协作

> 直接吸收你 `A_便携分析包/01_HITL工作流` 的成熟模式，升级为 PsyClaw 一等公民。

### 7.1 三智能体分工（职责隔离 = 质量保证）

| Agent | 职责 | 红线 |
|-------|------|------|
| **planner** | 把研究目标拆成可审计的执行计划：任务/输入/输出/依赖/审批节点/停止条件/最小可交付 | 不写代码；先诊断数据质量再做正式分析；标注可并行步骤 |
| **executor** | 写脚本、跑分析、出表图、记日志 | 不碰原始 `data/`；脚本 `scripts/stepN_*.py`、结果 `outputs/stepN_*`；需排除/重编码先写 `decision_request.md` 并停 |
| **critic** | 只找问题，不美化：数据口径、越界解释（相关≠因果）、误导图表、复现缺失、效应量夸大、多重比较、大样本过度解读 | 输出分 Blocking / Warning / Approved；零 blocking 才算过 |

定义文件落在每个研究项目的 `.psyclaw/agents/{planner,executor,critic}.md`（骨架已附三份）。PsyClaw 通过子智能体调用（fork ARS 的 agent 编排 + claude-code Task 工具思路）。

### 7.2 HITL 主回路（`/research-loop` 命令）

```
① 初始化   读 PSYCLAW.md / goal.md / data/ 结构，确认数据可用
      │
② 规划     planner → notes/plan.md  ──[人工确认计划]── 否→停
      │ 是
③ 执行     executor 按 plan 逐步；每步写 logs/run_log.md
      │      └─ 触发数据排除/重编码？→ 写 decision_request.md → 停等批准
      │
④ 审查     critic → notes/review.md（Blocking / Warning / Approved）
      │
⑤ 修复环   有 Blocking？→ 只修 Blocking → 回 ④   （循环至零 Blocking）
      │ 无
⑥ 审批门   任何需人工批准处 → decision_request.md（理由/影响/替代方案）→ 停等"批准"
      │
⑦ 交付     outputs/report.md（只引用已存在的表图） + notes/repro_manifest.md（复现清单）
```

**紧急停止条件**（硬编码，任一触发即停并通知人）：原始数据缺必要字段 · 需删除/重编码但无批准 · critic 有无法自动修复的 blocking · 脚本超时/OOM。

### 7.3 与 Gates 的关系

HITL 是**流程层**（什么时候停、谁审、人批不批），Gates 是**内容层**（产出物本身合不合规）。两者叠加：critic 跑 `gates check` 作为审查的客观依据，人工审批门处理 gates 无法判定的价值判断（如「这个异常值该不该删」）。

---

## 8. 项目组织结构（每个研究项目的标准布局）

PsyClaw 在 `/init` 时为每个研究项目铺设此结构（吸收 `01_HITL工作流` 布局 + 硬规则）：

```
my-study/
├── PSYCLAW.md              # 项目级规范（项目目标、数据说明、硬规则、技术环境、方法计划）
├── .psyclaw/
│   ├── agents/             # planner / executor / critic（可项目内覆盖默认）
│   ├── commands/           # research-loop 等项目级 slash 命令
│   └── config.yaml         # 项目级配置（覆盖全局）
├── data/                   # 原始数据（只读，禁止 agent 修改）
│   └── <dataset>/{data.csv, codebook.txt}
├── scripts/                # 分析脚本  stepN_描述.py / .R
├── outputs/                # 表、图、报告（report 只能引用这里的产物）
├── figures/                # 图片产出（受图片风格规范约束，见 §9）
├── logs/                   # run_log.md（命令/时间/输出/状态）
└── notes/                  # goal.md · plan.md · review.md · decision_request.md · repro_manifest.md
```

**硬规则**（写入项目 PSYCLAW.md，agent 必守）：不改原始 `data/`，只产 derived outputs；每次运行记 `logs/run_log.md`；删除/重编码/剔异常值先写 `decision_request.md` 等人批；报告只引用 `outputs/` 已存在的表图；critic 通过前不写最终结论。

---

## 9. 图片风格规范（图表是审稿第一眼）

所有图由 executor 生成、受 `gates/figure_style.yaml` 约束，目标是**出版级、一致、不误导**。详见骨架 `psyclaw/gates/figure_style.yaml`。

| 维度 | 规范 |
|------|------|
| **期刊风格** | 默认 APA7 figure 风格：无顶/右边框、无背景网格阴影、Sans-serif（Arial/Helvetica）、字号≥8pt |
| **配色** | 色盲友好（Okabe-Ito / viridis）；灰度可辨；不用红绿对比承载唯一信息 |
| **诚实性检查** | y 轴默认从 0 起；截断必须显式标注；误差棒注明含义（SD/SE/95%CI）；不选择性裁剪 |
| **分辨率/格式** | 矢量优先（PDF/SVG）；位图 ≥300 DPI；论文图导出 TIFF/PDF |
| **可复现** | 每张图附生成脚本 + 数据源；图注含 N、统计量、显著性标注规则 |
| **风格切换** | `nature` / `apa7` / `frontiers` / `minimal` 预设；项目内可锁定统一风格 |

实现：统一的 `psyclaw.figures` 主题层（matplotlib rcParams + seaborn 主题 + ggplot theme 对照），所有子技能出图走同一入口，保证全项目视觉一致。

---

## 10. 路线图

| 里程碑 | 内容 | 验收 |
|--------|------|------|
| **M0（本轮）** | 设计稿 + 可运行最小骨架 | `python -m psyclaw --help/doctor/gates` 跑通 |
| **M1** | Fork ARS，接通 REPL + provider，`/help /model /skills` 可用 | 能对话、能列 skill |
| **M2** | ARS-Stat 主路径（pystat/R），`/stat @data.csv` 出 APA7 + 复现脚本 | 一份样例数据端到端 |
| **M3** | Gates 全量上线，PSYCLAW.md 注入 + checker 阻断 | 违规输出被拦 |
| **M4** | MCP 全接（Zotero/文献/Mplus），`config` 向导完善 | `doctor` 全绿 |
| **M5** | `/research` 全流水线打通，审稿模拟 | 跑出一篇通过质量检查的心理学稿 |

---

## 8. 开放问题（留给下一轮）

1. REPL 用 `prompt_toolkit`（功能全）还是 `rich.prompt`（轻）？骨架先用 stdlib，便于零依赖运行。
2. ARS 子技能是独立 SKILL.md 还是单文件多 section？当前设计为独立子技能 + ARS 总编排。
3. 是否复用环境里已装的 `academic-research-skills` 插件作为 writing 子技能后端，避免重造？建议 M2 评估。
4. 商业统计软件 MCP 由谁实现/维护？先定接口契约，实现可后置。
