# PsyClaw 命令地图

> 入口 `python -m psyclaw <命令>`。命令注册真源是 `psyclaw/cli.py`。
> PsyClaw 现为**纯研究编排 harness**——统计计算已外移到成熟库/MCP,本 CLI 不含统计命令。

> 第一次用?运行 **`psyclaw guide`**(决策树上手),手把手教程见 **`docs/TUTORIAL.md`**。
> `psyclaw --help` 只显示常用入口;**`psyclaw commands`** 按职能列出全部兼容/高级命令。

---

## 命令总览(56 条;默认帮助只突出 3 种交互入口与基础命令)

> 三种工作方式:`psyclaw`(chat 对话)· `psyclaw run <类型>`(明确流程)·
> `psyclaw auto`(持续推进)。旧 `agent/loop/*-loop/auto-loop` 保持兼容,不再是主入口。

### 环境 / 系统
| 命令 | 作用 |
|---|---|
| `chat` / 缺省 `psyclaw` | 对话模式:边讨论边推进,工具按需使用并保留审批 |
| `run <类型> <目标>` | 运行模式:`analysis/meta/literature/qualitative`;默认连续执行 |
| `auto` | 自动模式:感知项目状态→派发流程→验收→记录→继续;强制检查未通过时暂停 |
| `repl` | `chat` 的兼容别名 |
| `version` / `doctor` | 版本 / 环境自检(配置·MCP·质量检查) |
| `config` | 配置向导(API key/模型/环境变量) |
| `setup` | 项目脚手架+能力选装:建目录 + 据研究准备清单生成概览/项目记忆 + 装能力依赖(`--online`)+ 列 MCP/skill |
| `setup --env` | **一键配置基础环境**(v0.9):诊断配置文件/LLM key/stats/full 组,每项给 ✓✗+修法;`--online` 自动 pip 装可修的缺失组 |
| `skills` / `mcp` | 列出 skills(内置 + 发现 `.claude/skills`/`PSYCLAW_SKILLS_PATH`;`--for <研究类型>` 按类型推荐)/ MCP 目录(内置 registry + 用户 `.psyclaw/mcp.yaml` 项目/全局)——**均标注 内置/用户·项目/用户·全局** |
| `plugins` | 列出插件(用户 项目 `.psyclaw/plugins/` / 全局 `~/.psyclaw/plugins/`;`register(api)` 注册 agent 工具 / REPL 命令 / system 片段) |
| `gates` | 质量规则系统自检(高级兼容命令;实际稿件用 `check`) |
| `eval` | **确定性离线评测**(v0.12):编排/质量检查/自学习契约的端到端 scorecard(6 用例 28 检查,不调 LLM/不联网/无统计库);`--case` 选用例、`--json` 机器可读;报告落 `.psyclaw/eval_report.json`,有失败退出码 1 |
| `commands` | 按职能分类列出全部命令 |
| `status` | **一屏项目态势**:目标/澄清/回路/等人决策(直接打印内容)/最近产物/下一步建议 |

`skills --sync [name]` 可同步带 `upstream.json` 的内置 skill,例如 `ctx2skill` / `opid`;
上游仓库保持在各自 skill 的 `upstream/` 目录,不打散到 PsyClaw 主代码。

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
| `prepare` | 完成 17 个研究准备项,完成后再启动正式流程(`--status` 看进度) |
| `clarify` | `prepare` 的兼容别名 |
| `declare-test --dv --test` | 预注册单个计划分析;研究者自由度检查 |
| `preregister` | OSF/AsPredicted 双格式预注册模板(据研究准备清单抽取;样本量依据取 power 项) |
| `jars <draft>` | APA 2018 JARS 检查清单(quant/qual/mixed) |
| `check [稿件.md] [--journal]` | **投稿前一键质检**:JARS + 引用保真(+期刊风格)+ 复现溯源 + KG 溯源,一屏汇总 ✓/✗/⚠ |
| `cite-check <稿件.md>` | 引用保真核查:文内引用逐条溯源到检索命中,孤儿引用=疑似杜撰(反杜撰);`--journal` 附引用风格核对 + 退稿红线 |

### Run 类型
| 命令 | 作用 |
|---|---|
| `run literature <主题>` | 文献综述:澄清→检索→筛选(PRISMA)→合成综述→评审 |
| `run meta <effects.csv>` | 元分析:校验效应量表→外部 statsmodels→写作→评审 |
| `run analysis <data.csv>` | 实证分析:画像→设计→外部 pingouin/MCP→写作→评审 |
| `run qualitative <转录稿>` | 质性分析:载入→设计→主题分析→COREQ→评审 |

统一参数:`--confirm-each` 每步确认;`--exploratory` 跳过未完成的前置检查并标记探索性;
`--resume` 从 `.psyclaw/workflows/<流程>.json` 的最后成功步骤继续。恢复时目标、输入和已有产物必须一致。

兼容命令:`agent`、`loop`、`research`、`lit-loop`、`meta-loop`、`analysis-loop`、
`qual-loop`、`auto-loop`。它们继续可调用,但新脚本与文档应使用 `run` / `auto`。

### 工作流 / 编排
| 命令 | 作用 |
|---|---|
| `goal [text]` | 查看/设定研究目标 |
| `plan [topic]` | planner 产出 notes/plan.md + 任务看板 |
| `tasks [...]` | 任务看板(list/add/start/done/block/sync/clear) |
| `review [draft]` | 审稿模拟(EIC+3 审稿人+Devil's Advocate;`--revise` 闭环修复) |

### 检索 / 知识图谱
| 命令 | 作用 |
|---|---|
| `search <query> [--type]` | 来源路由检索:据任务类型(事实/概念/趋势/回忆)路由到学术库/本地会话(主通道+兜底) |
| `kg [seed\|show <实体>\|verify\|stats]` | 带引用的知识图谱:据 evidence_map 种图;边必带来源,`verify` 复用 cite-check 核对关系溯源 |
| `lit [query]` | 文献检索 + 合法 OA 全文(PRISMA 计数;`-s` 一键合成综述) |

### 记忆 / 消息 / IO
| 命令 | 作用 |
|---|---|
| `memory [...]` | 三层记忆(画像/决策惯性/教训卡) |
| `session [list\|search\|rename\|delete]` | 会话持久化管理:跨会话对话存 SQLite,FTS5 全文检索(无 FTS5 回落 LIKE) |
| `resume [id]` | 续接历史会话进入 REPL(不给 id 续接最近一次;REPL 内亦有 `/sessions //resume //rename //search`) |
| `serve <channel>` | 对接消息端(telegram / wechat 双向 bot) |
| `notify <msg>` | 推送通知(企业微信 webhook / Telegram) |
| `auth` | 机构权限(EZProxy/LibKey)配置与认证状态自检 |
| `export <file>` | 格式化输出(APA7 / 心理学报 / 心理科学) |
| `figures` | 图表主题层 + FIG.honest 诚实性核查 + Okabe-Ito 调色板 |
| `provenance <产物>` | 复现溯源:给生成脚本/图打包 代码+环境+说明+决策轨迹(`<产物>.provenance.json`);`--journal` 按数据可得性要求收紧,`data_availability=required` 期刊强制 replication-package 声明(v0.12,声明文本可直接放进稿件) |

### Chat 斜杠命令(缺省 `psyclaw` / `psyclaw chat` 内)
| 命令 | 作用 |
|---|---|
| `/run <类型> <目标>` | 在对话中调用与 CLI 相同的共享流程路由 |
| `/auto` | 在对话中启动自主项目推进 |
| `/goal [文本]` | 查看目标;带文本时写入 `notes/goal.md`,同时作为当前对话任务立即开始执行;目标会持续注入后续轮次,输入“继续”也不丢上下文 |
| `/dump [--full] [路径]` | 导出当前对话为 Markdown;`--full` 连同不展示的隐藏上下文(system/当前目标/决策备忘/约定片段)一并导出;拒写 `data/raw` |
| `/approval ask\|auto` | 副作用逐条确认或自动放行非危险操作;危险操作始终确认 |
| `/access open\|safe` | 模型可请求读文件,或仅允许用户用 `@路径` 显式引用 |
| `/img <路径>`（`/show`） | 终端内联渲染图片(iTerm2/WezTerm/VSCode/Warp/kitty;命令出图会自动显示);`config image_protocol` 可强制 iterm2\|kitty\|none |
| `/memory verify` | 再验证环境教训卡:环境已恢复(装上库/命令有了)的自动失效归档,别再用过时的坑误导模型 |

> 错误自学习(v0.11):REPL 里命令失败会自动蒸馏「环境教训」(命令不存在/模块未装/API 改名),本会话每轮注入止损,并落 `/memory` 待确认卡跨会话复用。

---

## 统计去哪了?

统计计算(描述/相关/t/ANOVA/回归/GLM/因子/SEM/生存/信度/功效/元分析/中介…)
**已整体外移**,不在 PsyClaw CLI 内。三条途径:

1. **外部成熟库**:在装了 `psyclaw[stats]`(scipy/pingouin/statsmodels/lifelines/
   factor_analyzer/semopy)的解释器里直接写分析脚本。
2. **MCP 服务器**:`psyclaw mcp --serve {pystat,mne,spss,mplus,stata}` 以 stdio MCP 跑统计后端。
   **pystat**(v0.8,pingouin/pandas:t 检验/相关/方差/回归/描述)默认启用。
   v0.5 起 **agent 会直接调用**这些 MCP:`agent`/REPL 的工具集自动并入已启用+健康的 MCP
   服务器工具(名字带 `mcp__<server>__` 前缀,属副作用工具需批准);`PSYCLAW_MCP_TOOLS=0` 可关。
3. **Chat 自然语言**:直接运行 `psyclaw`,用自然语言提统计需求,ARS 规范已注入上下文。

PsyClaw 负责把研究流程编排起来(澄清→文献→设计→写作→评审→质量检查),
统计这一环交给上面三者——这是本次重构后的明确分工(见 `CLAUDE.md` 铁律)。
