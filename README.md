# PsyClaw

> 心理学研究**编排** Agent CLI —— 把研究全流程(澄清→文献→设计→写作→评审→质量检查)编排起来。
> **统计计算交给外部成熟库/MCP,本体不内置统计**(纯 stdlib 核,研究质量检查内置)。

PsyClaw 不替你算统计,而是帮你**把研究流程跑顺**:按研究类型路由到不同流程,
每一步都有 harness 约束(澄清不完不开工、效应量+CI 必报、确证须先预注册),
统计这一环生成**可复现脚本**(pingouin/statsmodels)交外部库跑,或走 MCP 统计后端。

架构详解见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md);命令地图见 [`docs/COMMANDS.md`](docs/COMMANDS.md)。

---

## 安装(一键)

需要 Python ≥ 3.11。装完得到 `psyclaw` 命令。

**macOS / Linux:**

```bash
curl -fsSL https://exekiel179.github.io/psyclaw/install.sh | sh
```

**Windows(PowerShell):**

```powershell
irm https://exekiel179.github.io/psyclaw/install.ps1 | iex
```

脚本自动探测 GitHub 是否可达,**国内不通时切 gitclone.com + aliyun 镜像**;用 uv 装(自带管理 Python,无需先装好 3.11)。可选环境变量:`PSYCLAW_CN=1` 强制国内镜像、`PSYCLAW_EXTRAS=[stats]` 顺带装本机统计栈、`PSYCLAW_VERSION=v0.15.0` 指定版本。

<details><summary>手动安装(uv / pip)</summary>

```bash
# uv(推荐):
uv tool install --python 3.12 "git+https://github.com/Exekiel179/psyclaw.git@v0.15.0"
# 国内:把 URL 换成 https://gitclone.com/github.com/Exekiel179/psyclaw.git,并加 UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple/
# pip:
pip install "git+https://github.com/Exekiel179/psyclaw.git@v0.15.0"
# 带统计栈:...在包名后加 [stats]
```
</details>

## 30 秒上手

```bash
psyclaw config                # 配 LLM provider / API key
psyclaw new 我的研究           # 建一个按文件夹组织的分析,cd 进去开聊
psyclaw guide                 # 只需记住 chat / run / auto
psyclaw run literature "正念干预能否降低大学生焦虑"
```

无 API key 也能跑(provider 自动降级 mock);装统计栈用 `psyclaw setup --online` 或 `pip install "psyclaw[stats]"`。

---

## 心智模型:chat / run / auto

```bash
psyclaw                                  # chat:自然语言协作,关键操作确认
psyclaw run literature "拖延的干预手段"  # run:明确、可复现的一次流程
psyclaw run meta effects.csv
psyclaw run analysis data.csv
psyclaw run qualitative interviews/
psyclaw auto                             # auto:据项目状态持续推进
```

`run` 公开提供 `literature / analysis / meta / qualitative` 四条稳定流程。默认连续执行;
`--confirm-each` 逐步确认,`--exploratory` 以探索性身份运行并留痕,`--resume` 从最后成功步骤继续。
每步检查点落 `.psyclaw/workflows/`,产物落 `notes/` 与 `outputs/`。
**`auto`** 在它们之上再加一层自驱动:每轮从仓库状态重新发现该做什么(有目标→文献、有数据→分析、
有效应量表→元分析、有转录稿→质性),派给对应流程,**独立验收**(只信落盘产物)后记进
`notes/autoloop_state.json`,再决定下一步——直到无事可做 / 前置检查未通过 / 到迭代上限。
旧 `agent`、`loop`、`research`、`*-loop`、`auto-loop` 命令在兼容期内仍可用,但不再是主入口。

---

## 工作样例

### 样例 1 —— `run analysis` 在真实数据上做什么

数据 `retention.csv`(铁保留率 × 处理组,来自公开统计基准):

```bash
psyclaw run analysis retention.csv      # (需先 psyclaw prepare;准备项未完成时流程会暂停)
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

### 样例 2 —— `run meta` 生成可复现元分析脚本

效应量表 `effects.csv`(列含 `study, d, se`):

```bash
psyclaw run meta effects.csv
```

生成 `outputs/meta_analysis.py`(委托 statsmodels):随机效应 DerSimonian-Laird +
I²/τ²/Q 异质性 + Egger 发表偏倚 + 森林图。跑出:`合并效应 0.347 · I²=27% · Egger p=.008`。

### 样例 3 —— `run literature`

```bash
psyclaw lit "mindfulness anxiety intervention"    # 先检索(多源 OA + PRISMA 计数)
psyclaw run literature "正念干预对焦虑的影响"      # 澄清→检索→筛选→合成综述→评审
```

产出 `notes/lit_review.md`(据真实命中合成的有据综述)+ `notes/prisma_flow.md`(PRISMA 计数)+ 证据图谱。

---

## 命令一览(`psyclaw commands` 看全部 ★ 标常用)

**三种交互入口**
`chat`(缺省) · `run <类型>` · `auto`

**研究前规划 / 预注册**
`prepare`(研究准备清单;`clarify` 为兼容别名) · `declare-test`(声明单个分析) · `preregister`(OSF/AsPredicted 模板) · `jars`(JARS 清单)

**知识参考(只读查阅)**
`scale`(量表库) · `norms`(中文常模) · `assume`(前提假设) · `method`(复杂方法目录) · `design`(实验设计目录) · `cite`(方法学背书) · `ethics`(伦理提示)

**数据 / 文献 / 写作**
`score`(量表计分) · `lit`(文献检索+OA全文) · `export`(APA7/心理学报/心理科学) · `review`(审稿模拟) · `figures`(图表诚实性)

**工作 / 记忆 / 系统**
`goal` · `plan` · `tasks` · `memory`(三层记忆) · `gates`(研究质量检查) · `config` · `setup` · `doctor` · `mcp` · `skills` · `serve`/`notify`(消息端) · `auth`(机构权限) · `guide` · `commands`

---

## 统计去哪了?

统计计算(描述/相关/t/ANOVA/回归/GLM/因子/SEM/生存/信度/功效/元分析/中介…)**已整体外移**,三条途径:

1. **外部成熟库** —— `pip install "psyclaw[stats]"`(pingouin/scipy/statsmodels/lifelines/factor_analyzer/semopy),跑 `run` 生成的 `outputs/*.py`。
2. **MCP 统计后端** —— `psyclaw mcp --serve {mne,spss,mplus,stata}`,以 stdio MCP 跑专业统计工具(可挂 Claude Desktop)。
3. **Chat 自然语言** —— 直接运行 `psyclaw` 后提统计需求,ARS 学术规范已注入上下文。

PsyClaw 只负责编排研究流程 + 生成可复现脚本/执行质量检查,统计交给上面三者。

---

## Provider 与消息端

- **多 provider**:Anthropic / OpenAI 兼容中转 / 本地(ollama/lmstudio)/ opencode 后端 / mock 兜底;`psyclaw config` 配置 key 与模型,密钥存 `~/.psyclaw/`(不入仓库)。
- **消息端**:`psyclaw serve telegram` / `serve wechat`(走微信 iLink 网关)双向 bot;`psyclaw notify "<消息>"` 单向推送(HITL 审批提醒)。

---

## 血统

claude-code(REPL/命令/Tool 抽象)· codex(exec/审批)· OpenClaw(provider)·
AutoResearchClaw(pipeline/skills/MCP)· learn-harness-engineering / learn-hermes-agent(harness/loop 工程实践)。
