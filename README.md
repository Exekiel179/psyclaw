# PsyClaw

> 心理学研究**编排** Agent CLI —— 把研究全流程(澄清→文献→设计→写作→评审→门禁)编排起来。
> **统计计算交给外部成熟库/MCP,本体不内置统计**(纯 stdlib 核,学术规范门禁内置)。

PsyClaw 不替你算统计,而是帮你**把研究流程跑顺**:按研究类型路由到不同流程,
每一步都有 harness 约束(澄清不完不开工、效应量+CI 必报、确证须先预注册),
统计这一环生成**可复现脚本**(pingouin/statsmodels)交外部库跑,或走 MCP 统计后端。

架构详解见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md);命令地图见 [`docs/COMMANDS.md`](docs/COMMANDS.md)。

---

## 30 秒上手

```bash
python -m psyclaw guide        # 上手介绍:是什么 + 心智模型(每类研究一条 loop)+ 60 秒上手
python -m psyclaw setup        # 项目脚手架:建目录 + 据澄清生成项目概览/记忆 + 装能力依赖
python -m psyclaw clarify      # 研究澄清(17 槽位;不澄清完,loop 不放行)
python -m psyclaw lit-loop "正念干预能否降低大学生焦虑"   # 选一条对应你研究类型的 loop 起跑
```

无 API key 也能跑(provider 自动降级 mock);装统计栈用 `psyclaw setup --online` 或 `pip install "psyclaw[stats]"`。

---

## 心智模型:每类研究走一条 *loop*

```bash
psyclaw loop "任意研究/写作任务"         # 通用编排回路(planner→执行→critic→修复),不绑类型
psyclaw lit-loop "拖延的干预手段"        # 文献综述:澄清→检索→PRISMA筛选→合成综述→评审
psyclaw meta-loop effects.csv           # 元分析:校验效应量→生成脚本(statsmodels)→写→评审
psyclaw analysis-loop data.csv          # 实证分析:画像→设计→推荐分析+脚本(pingouin)→写→评审
psyclaw qual-loop interviews/           # 质性研究:转录稿→设计→主题分析(LLM辅助)→COREQ→评审
```

每条流程 = 一串带门禁的步骤,可中断、可续跑、可单步;产物落 `notes/` 与 `outputs/`。
`research` 是不分类型的固定全流程编排(沿用旧 pipeline)。

---

## 工作样例

### 样例 1 —— 实证分析:`analysis-loop` 在真实数据上做什么

数据 `retention.csv`(铁保留率 × 处理组,来自公开统计基准):

```bash
psyclaw analysis-loop retention.csv     # (需先 psyclaw clarify;门禁会拦未澄清的研究)
```

它**自动选对检验 + 生成 pingouin 脚本 + 由外部库算出结果(含效应量/CI/前提诊断)**:

```
① 画像:32 行 · 连续列 FeRetention · 分类列 Fe(2水平)、Zn(2水平)
② 推荐:独立样本 t 检验(Fe 两组比 FeRetention)
③ 生成 outputs/analysis.py(委托 pingouin)
④ 跑出来:
   正态性    → Low/High 都不正态(p < .05)
   方差齐性  → 不齐(Levene p = .027)
   t 检验    → T = -8.77, df = 30, Cohen's d = 3.10, power = 1.0, BF10 = 7.5e6
```

连**前提诊断**都随报——这里正态/方差齐性都不满足,会提示考虑稳健替代。
统计**不在 PsyClaw 里算**:`outputs/analysis.py` 是委托 pingouin 的可复现脚本,
你在装了 `[stats]` 的环境跑(`python outputs/analysis.py`)或交 MCP 统计后端。

### 样例 2 —— 元分析:`meta-loop` 生成可复现元分析脚本

效应量表 `effects.csv`(列含 `study, d, se`):

```bash
psyclaw meta-loop effects.csv
```

生成 `outputs/meta_analysis.py`(委托 statsmodels):随机效应 DerSimonian-Laird +
I²/τ²/Q 异质性 + Egger 发表偏倚 + 森林图。跑出:`合并效应 0.347 · I²=27% · Egger p=.008`。

### 样例 3 —— 文献综述:`lit-loop`

```bash
psyclaw lit "mindfulness anxiety intervention"    # 先检索(多源 OA + PRISMA 计数)
psyclaw lit-loop "正念干预对焦虑的影响"            # 澄清→检索→筛选→合成综述→评审
```

产出 `notes/lit_review.md`(据真实命中合成的有据综述)+ `notes/prisma_flow.md`(PRISMA 计数)+ 证据图谱。

---

## 命令一览(`psyclaw commands` 看全部 ★ 标常用)

**研究流程 / 编排回路**
`loop` · `lit-loop` · `meta-loop` · `analysis-loop` · `qual-loop` · `research`

**研究前规划 / 预注册**
`clarify`(grill-me 式澄清,门禁) · `declare-test`(声明单个分析) · `preregister`(OSF/AsPredicted 模板) · `jars`(JARS 清单)

**知识参考(只读查阅)**
`scale`(量表库) · `norms`(中文常模) · `assume`(前提假设) · `method`(复杂方法目录) · `design`(实验设计目录) · `cite`(方法学背书) · `ethics`(伦理提示)

**数据 / 文献 / 写作**
`score`(量表计分) · `lit`(文献检索+OA全文) · `export`(APA7/心理学报/心理科学) · `review`(审稿模拟) · `figures`(图表诚实性)

**工作 / 记忆 / 系统**
`goal` · `plan` · `tasks` · `memory`(三层记忆) · `gates`(学术门禁) · `config` · `setup` · `doctor` · `mcp` · `skills` · `serve`/`notify`(消息端) · `auth`(机构权限) · `guide` · `commands`

---

## 统计去哪了?

统计计算(描述/相关/t/ANOVA/回归/GLM/因子/SEM/生存/信度/功效/元分析/中介…)**已整体外移**,三条途径:

1. **外部成熟库** —— `pip install "psyclaw[stats]"`(pingouin/scipy/statsmodels/lifelines/factor_analyzer/semopy),跑 loop 生成的 `outputs/*.py`。
2. **MCP 统计后端** —— `psyclaw mcp --serve {mne,spss,mplus,stata}`,以 stdio MCP 跑专业统计工具(可挂 Claude Desktop)。
3. **REPL 自然语言** —— `psyclaw repl` 里直接提统计需求,ARS 学术规范已注入上下文。

PsyClaw 只负责编排研究流程 + 生成可复现脚本/规范门禁,统计交给上面三者。

---

## Provider 与消息端

- **多 provider**:Anthropic / OpenAI 兼容中转 / 本地(ollama/lmstudio)/ opencode 后端 / mock 兜底;`psyclaw config` 配置 key 与模型,密钥存 `~/.psyclaw/`(不入仓库)。
- **消息端**:`psyclaw serve telegram` / `serve wechat`(走微信 iLink 网关)双向 bot;`psyclaw notify "<消息>"` 单向推送(HITL 审批提醒)。

---

## 血统

claude-code(REPL/命令/Tool 抽象)· codex(exec/审批)· OpenClaw(provider)·
AutoResearchClaw(pipeline/skills/MCP)· learn-harness-engineering / learn-hermes-agent(harness/loop 工程实践)。
