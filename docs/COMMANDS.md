# PsyClaw 命令地图

> 入口 `python -m psyclaw <命令>`。命令注册真源是 `psyclaw/cli.py`。
> PsyClaw 现为**纯研究编排 harness**——统计计算已外移到成熟库/MCP,本 CLI 不含统计命令。

> 第一次用?运行 **`psyclaw guide`**(上手介绍 + 心智模型 + 60 秒上手)。
> `psyclaw --help` 暴露**全部**顶层命令;**`psyclaw commands`** 按职能分类列出(★ 标上手常用)。

---

## 命令总览(39 条)

### 环境 / 系统
| 命令 | 作用 |
|---|---|
| `repl` | 交互式 REPL(缺省命令) |
| `version` / `doctor` | 版本 / 环境自检(配置·MCP·Gates) |
| `config` | 配置向导(API key/模型/环境变量) |
| `setup` | 项目脚手架+能力选装:建目录 + 据 clarify 生成概览/项目记忆 + 装能力依赖(`--online`)+ 列 MCP/skill |
| `skills` / `mcp` | 列出 skills(内置 + 发现 `.claude/skills`/`PSYCLAW_SKILLS_PATH` 下 AcademicForge/AJS 等技能包;`--for <研究类型>` 按类型推荐)/ 运行内置 MCP(mne·spss·mplus·stata) |
| `gates` | 学术规范门禁自检 |
| `commands` | 按职能分类列出全部命令 |

### 只读知识目录(查阅,无计算)
| 命令 | 查什么 |
|---|---|
| `scale [id]` | 量表库(DASS/PHQ-9/GAD-7/TIPI…) |
| `norms [id]` | 中文量表常模(截断值 + 中国样本 M/SD) |
| `assume [id]` | 各检验的前提假设知识库 |
| `method [id]` | 复杂方法目录(SEM/MLM/LPA/网络/交叉滞后…) |
| `design [id]` | 实验设计目录(被试间/内/混合/纵向/ESM…) |
| `cite [id]` | 方法学背书库:每个设计决策的文献支撑 |
| `ethics <id>` | 量表伦理审查提示(IRB / 危机转介 / 敏感条目) |
| `journal [id]` | 期刊画像(心理学报/心理科学/Psych Science/JPSP/Psych Bulletin…引用风格/报告标准/退稿红线;供 cite-check/provenance `--journal` 取判据) |

### 量表 / 数据准备
| 命令 | 作用 |
|---|---|
| `score <data> --scale` | 量表自动计分(反向题翻转 + 子量表总分/均值;信度计算请用外部库) |

### 研究前规划 / 预注册
| 命令 | 作用 |
|---|---|
| `clarify` | grill-me 式研究澄清,17 槽位,不澄清完不开工(`--status` 看进度) |
| `declare-test --dv --test` | 预注册单个计划分析;研究者自由度门禁 |
| `preregister` | OSF/AsPredicted 双格式预注册模板(据澄清卡抽取;样本量依据填澄清卡 power 槽位) |
| `jars <draft>` | APA 2018 JARS 检查清单(quant/qual/mixed) |
| `cite-check <稿件.md>` | 引用保真核查:文内引用逐条溯源到检索命中,孤儿引用=疑似杜撰(反杜撰);`--journal` 附引用风格核对 + 退稿红线 |

### 研究流程 / 编排回路
| 命令 | 作用 |
|---|---|
| `auto-loop` | 自主科研回路(Ralph 式自循环):每轮自动发现待办→派发对应 `<type>-loop`→**独立验收**(只读落盘产物)→记 `notes/autoloop_state.json`→决定下一步(`--max-iters` / `--auto`) |
| `loop [主题]` | 通用流程编排回路(类 Claude Code 的 agentic loop:planner→执行→critic→修复),不绑研究类型 |
| `lit-loop <主题>` | 文献综述:澄清→检索→筛选(PRISMA)→合成综述→评审 |
| `meta-loop <effects.csv>` | 元分析:校验效应量表→生成可复现脚本(委托 statsmodels)→写→评审 |
| `analysis-loop <data.csv>` | 实证分析:画像数据→设计→推荐分析+生成可复现脚本(委托 pingouin/scipy)→写→评审 |
| `qual-loop <转录稿>` | 质性研究:载入转录稿→设计→主题分析(LLM 辅助,研究者复核)→写 COREQ 报告→评审 |
| `research [topic]` | 不分类型的固定全流程:文献→设计→写作→评审→总验收 |

> 见 `docs/ARCHITECTURE.md`。命名约定:**每个流程都是一个 "loop"**——`loop` 是通用编排器,
> `<type>-loop` 是预置的具体研究流程;子功能可单用/可拼装。

### 工作流 / 编排
| 命令 | 作用 |
|---|---|
| `goal [text]` | 查看/设定研究目标 |
| `plan [topic]` | planner 产出 notes/plan.md + 任务看板 |
| `tasks [...]` | 任务看板(list/add/start/done/block/sync/clear) |
| `review [draft]` | 审稿模拟(EIC+3 审稿人+Devil's Advocate;`--revise` 闭环修复) |

### 记忆 / 消息 / IO
| 命令 | 作用 |
|---|---|
| `memory [...]` | 三层记忆(画像/决策惯性/教训卡) |
| `session [list\|search\|rename\|delete]` | 会话持久化管理:跨会话对话存 SQLite,FTS5 全文检索(无 FTS5 回落 LIKE) |
| `resume [id]` | 续接历史会话进入 REPL(不给 id 续接最近一次;REPL 内亦有 `/sessions //resume //rename //search`) |
| `serve <channel>` | 对接消息端(telegram / wechat 双向 bot) |
| `notify <msg>` | 推送通知(企业微信 webhook / Telegram) |
| `lit [query]` | 文献检索 + 合法 OA 全文(PRISMA 计数;`-s` 一键合成综述) |
| `auth` | 机构权限(EZProxy/LibKey)配置与认证状态自检 |
| `export <file>` | 格式化输出(APA7 / 心理学报 / 心理科学) |
| `figures` | 图表主题层 + FIG.honest 诚实性核查 + Okabe-Ito 调色板 |
| `provenance <产物>` | 复现溯源:给生成脚本/图打包 代码+环境+说明+决策轨迹(`<产物>.provenance.json`);`--journal` 按数据可得性要求收紧 |

---

## 统计去哪了?

统计计算(描述/相关/t/ANOVA/回归/GLM/因子/SEM/生存/信度/功效/元分析/中介…)
**已整体外移**,不在 PsyClaw CLI 内。三条途径:

1. **外部成熟库**:在装了 `psyclaw[stats]`(scipy/pingouin/statsmodels/lifelines/
   factor_analyzer/semopy)的解释器里直接写分析脚本。
2. **MCP 服务器**:`psyclaw mcp --serve {mne,spss,mplus,stata}` 以 stdio MCP 跑专业统计后端。
3. **REPL 自然语言**:在 `psyclaw repl` 里直接用自然语言提统计需求,ARS 规范已注入上下文。

PsyClaw 负责把研究流程编排起来(澄清→文献→设计→写作→评审→门禁),
统计这一环交给上面三者——这是本次重构后的明确分工(见 `CLAUDE.md` 铁律)。
