# PsyClaw 命令地图与选择指南

> 入口 `python -m psyclaw <命令>`。本文件是**命令清单 + 重合点厘清**：
> 哪些命令做什么、功能相近的几组该怎么选、彼此边界在哪。
> 命令注册真源是 `psyclaw/cli.py`。

> **渐进式披露**：命令很多，但默认 `psyclaw --help` 只显示 ~23 个**常用命令**（降低上手门槛）；
> 进阶/专门命令照常可调用，完整分类清单运行 **`psyclaw commands`**（★ 标常用）。
> 常用集定义在 `cli.py` 的 `CORE_COMMANDS`，改一处即可调整——隐藏 ≠ 删除，不破坏任何命令契约。

---

## 1. 命令总览（按职能分组）

### 环境 / 系统
| 命令 | 作用 |
|---|---|
| `repl` | 交互式 REPL（缺省命令） |
| `version` / `doctor` | 版本 / 环境自检（配置·MCP·Gates） |
| `config` / `setup` | 配置向导 / 能力选装（按组装依赖） |
| `skills` / `mcp` | 列出 skills / 运行内置 MCP（mne·spss·mplus·stata） |
| `gates` | 跑学术规范门禁自检 |

### 只读知识目录（查阅，不算数）
| 命令 | 查什么 |
|---|---|
| `scale` | 量表库（DASS/PHQ-9/GAD-7/TIPI…） |
| `norms` | 中文量表常模（截断值 + 中国样本 M/SD） |
| `assume` | 各检验的前提假设 |
| `method` | 复杂方法目录（SEM/MLM/LPA/网络/交叉滞后…） |
| `design` | 实验设计目录（被试间/内/混合/纵向/ESM…） |
| `cite` | 每个设计决策的文献背书 |

### 数据准备 / 量表处理
| 命令 | 作用 |
|---|---|
| `score` | 量表自动计分（反向题翻转 + 子量表总分/均值） |
| `screen` | 草率作答筛查（longstring/IRV/直线作答） |
| `ethics` | 量表伦理审查提示（IRB / 危机转介 / 敏感条目） |
| `missing` | 缺失数据报告（Little MCAR / 插补推荐） |

### 研究前规划 / 预注册
| 命令 | 作用 |
|---|---|
| `clarify` | grill-me 式研究澄清（17 槽位，不澄清完不开工） |
| `declare-test` | 预注册**单个**计划分析（研究者自由度门禁） |
| `power` | 先验功效分析（G\*Power 对标：t/ANOVA/相关/回归/SEM/中介） |
| `preregister` | OSF/AsPredicted 预注册模板（**内嵌 `power`**） |
| `jars` | APA JARS 检查清单（quant/qual/mixed） |

### 工作流 / 编排
| 命令 | 作用 |
|---|---|
| `goal` / `plan` / `tasks` | 设目标 / 出 plan.md+任务看板 / 任务看板 |
| `research` | 一句话端到端流水线：文献→设计→统计→写作→评审→门禁；`--freeform` 改走通用 HITL 回路 |
| `review` | 审稿模拟（EIC+3 审稿人+Devil's Advocate） |
| `stat` | **自动选检验** + 诊断 + APA7 + 复现脚本（见 §2.5） |

### 记忆 / 消息 / IO
| 命令 | 作用 |
|---|---|
| `memory` | 三层记忆（画像/决策惯性/教训卡） |
| `serve` / `notify` | 对接 telegram/wechat / 推送通知 |
| `lit` | 文献检索 + 合法 OA 全文（PRISMA 计数） |
| `auth` | 机构权限（EZProxy/LibKey） |
| `export` | 格式化输出（APA7 / 心理学报 / 心理科学） |
| `figures` | 图表主题层 + FIG.honest 诚实性核查 |

### 统计分析（核心）
| 子族 | 命令 |
|---|---|
| 描述 / 相关 | `describe`（含 `--corr` 相关矩阵）·`partial-corr`·`compare-corr` |
| 均值比较 | `ttest`·`anova`·`anova2`·`rm-anova`·`mixed-anova`·`ancova` |
| 非参 / 分类 | `chi2`·`nonpar`·`paired-cat` |
| 回归 / GLM | `regress`·`hreg`·`logit`·`poisson`·`negbin`·`ordinal`·`multinom`·`mlm` |
| 因子 / SEM | `efa`·`cfa`·`invariance` |
| 专门方法 | `survival`·`irr`·`roc`·`meta`·`mediation`·`moderation`·`tost`·`bayes`·`sensitivity` |
| 工具 | `effect-size`·`correct-p`·`check` |

---

## 2. 选择指南（功能相近时怎么选）

### 2.1 相关分析走哪条
相关分散在多个命令，按目的选：

| 你要做的事 | 用 |
|---|---|
| 一批变量的 Pearson 相关矩阵（含 CI、显著性星标） | `describe --corr` |
| 控制协变量后的（偏/半偏）相关、偏相关矩阵 | `partial-corr`（`--matrix` 出矩阵） |
| 等级/非正态数据的 Spearman ρ | `nonpar --test spearman` |
| 两个相关系数**是否显著不同** | `compare-corr` |
| 相关的贝叶斯证据强度（BF） | `bayes --test correlation` |
| 相关的先验功效 / 所需样本量 | `power r` |

> 没有独立的 `correlate` 命令——单变量对/矩阵的 Pearson 相关都在 `describe --corr` 里。

### 2.2 ANOVA 五命令怎么选（按设计）
| 设计 | 用 |
|---|---|
| 一个被试间因子 | `anova` |
| 两个被试间因子（含交互） | `anova2` |
| 一个被试内因子（重复测量） | `rm-anova` |
| 被试间 × 被试内（混合） | `mixed-anova` |
| 被试间因子 + 连续协变量 | `ancova` |

它们不冗余（设计不同），但都产 F / η² / ω² / 事后检验（Holm）。

### 2.3 同一组比较的三种推断框架
两组/两条件的均值比较，按你要回答的问题选框架：

| 问题 | 用 |
|---|---|
| 两组**有没有差异**（NHST） | `ttest` |
| 两组**是否等价/可视作无差异**（接受 H₀） | `tost` |
| 证据**强度**多大（支持 H₁ 还是 H₀） | `bayes --test ttest` |

### 2.4 回归 / GLM 选型（按因变量类型）
| 因变量 | 用 |
|---|---|
| 连续 | `regress`（单层）/ `hreg`（分块逐步，出 ΔR²） |
| 二元 0/1 | `logit` |
| 计数 | `poisson`（等离散）/ `negbin`（过度离散） |
| 有序多分类 | `ordinal` |
| 无序多分类 | `multinom` |
| 连续 + 嵌套/聚类结构 | `mlm` |

> 中介/调节是回归的特例：`mediation`（Bootstrap 间接效应）、`moderation`（交互 + 简单斜率 + Johnson-Neyman）。`hreg` 就是分块跑的 `regress`。

### 2.5 `stat`（自动）vs 专用命令（手动）
- **`stat`**：你不确定该用哪种检验时用它。据参数自动选检验族——
  `--group`→t/ANOVA、`--with`→相关、`--paired`→配对 t、`--cluster`→ICC/MLM 提示——
  并附假设诊断、APA7 结果段、**可复现 `.py` 脚本**。`--method` 走 R 后端（cfa/sem/mlm/omega/invariance）。
- **专用命令**（`ttest`/`anova`/`regress`/…）：你已确定方法、要全套参数与报告控制时用。

> **数值一致性**：`stat` 与专用命令的统计量/ p 值都统一经
> `stats_core`（内封 scipy）与 `diagnostics` 计算，**同源不双写**；
> `tests/test_stat_engine_consistency.py` 是把两条路径 + scipy 金标准三方钉死的回归门禁。

### 2.6 研究前规划三件套（粒度递进）
| 命令 | 粒度 |
|---|---|
| `clarify` | 把研究问题问清楚（17 槽位澄清，最上游） |
| `declare-test` | 锁定**一个**确证性分析（防 p-hacking 的自由度门禁） |
| `preregister` | 出 OSF/AsPredicted 完整模板（内嵌 `power` 功效分析） |

### 2.7 编排回路
- `research`：一句话主题 → 固定四象限全流程（含 `--revise` 闭合写作→评审→修复）。
- `research --freeform`（旧 `research-loop`）：改走通用 HITL 回路 planner→执行→critic→修复，不按固定四象限——适合非论文型/自定义任务。
- `review --revise`：单独对一份稿子跑评审→修复闭环（与 `research --revise` 是同一闭环的不同入口）。
- `plan`/`goal`/`tasks`：拆解与看板，喂给上面的回路。

> `research`(固定流水线) 与 `research --freeform`(通用回路) 同源：前者搭在后者的 planner/executor 积木之上。两个旧命令已于命令面合并为一个 `research` + 模式开关。

---

## 3. 功能重合速查（维护者视角）

| 重合点 | 性质 | 处置 |
|---|---|---|
| `stat` 自动路由 vs `ttest`/`anova`/… | 统计量曾各写一份 | **已收敛**：统一经 `stats_core`(scipy)；加一致性门禁锁死 |
| `preregister` 复制 `power` 全部参数 | 接口复制（逻辑已复用） | 可接受；改 `power` 签名时记得同步参数面 |
| 相关分散 6 处（§2.1） | 目的不同 | 保持；本文件作发现入口 |
| ANOVA 五命令（§2.2） | 设计不同 | 保持 |
| 回归族 + mediation/moderation/hreg（§2.4） | GLM 同族特例 | 保持 |
| ttest/tost/bayes（§2.3） | 三种推断框架 | 保持 |
| `research --revise` ≈ `review --revise` | 同一闭环不同入口 | 保持；本文件标注 |
| `check` vs 命令内置诊断 | 共享 `diagnostics` 模块 | 复用非重复 |
| 知识目录 6 命令（scale/assume/method/design/cite/norms） | 同构（id 参数，留空列全部） | 保持（可选未来合并为 `kb`） |

> 结论：除 `stat` 双引擎（已收敛）外，其余"相近"命令都是正当的方法学分工，按 §2 各取所需即可。
