# PsyClaw

> 心理学研究全流程 Agent CLI —— 文献调研 · 实验设计 · 统计分析 · 论文写作，规范门禁内置。
>
> Fork 自 AutoResearchClaw，特化为心理学方向：可复现优先，APA7 + 预注册 + 效应量 + 不 p-hacking 全部是机器门禁。

**当前进度:M1 已完成**(REPL + Provider + 心理学模块)。完整设计见 [`DESIGN.md`](DESIGN.md),心理学优化见 [`docs/PSYCH_OPTIMIZATIONS.md`](docs/PSYCH_OPTIMIZATIONS.md)。统计计算复用成熟库(scipy/pingouin/statsmodels/lifelines/factor_analyzer/semopy),配置时安装为硬依赖。

## 快速试跑（无需安装）

```bash
cd psyclaw
python -m psyclaw                 # 进入 REPL(对话+slash命令+@file,无key用mock)
python -m psyclaw config          # 配置 provider(anthropic/openai兼容中转/mock)+ API key
python -m psyclaw doctor          # 配置 / MCP / Gates 自检
python -m psyclaw scale dass-42   # 量表库查询(DASS/PHQ-9/GAD-7/TIPI/RSES/PSS)
python -m psyclaw screen data.csv # 草率作答筛查(longstring/IRV/直线作答)
python -m psyclaw assume anova-rm # 前提假设知识库(16 检验族:检查方法+违反对策)
python -m psyclaw method clpm     # 复杂方法目录(13 方法卡:SEM/MLM/LPA/网络/RI-CLPM…)
python -m psyclaw design within   # 实验设计目录(12 设计卡:效度威胁+抵消平衡+分析映射)
python -m psyclaw check d.csv --dv 分数 --group 组别  # 可运行诊断:正态/Levene/经典F+Welch F
python -m psyclaw gates           # 11 条学术规范门禁自检
python -m psyclaw skills mcp      # skills 与 MCP 目录
```

REPL 内:直接对话(注入 PSYCLAW 学术规范),`@文件` 引用数据,`/help` 看全部命令。

**Provider 预设(11 个,模型名经官方文档核实 2026-06)**:

| 预设 | 默认模型 | 备选 |
|------|----------|------|
| anthropic | claude-sonnet-4-6 | claude-opus-4-8, claude-fable-5 |
| openai | gpt-5.5 | gpt-5.5-pro |
| deepseek | deepseek-v4-flash | deepseek-v4-pro(deepseek-chat 2026-07-24 弃用) |
| qwen | qwen3.6-plus | qwen3.7-max, qwen3.6-flash |
| zhipu | glm-5 | glm-5.1, glm-5-turbo |
| moonshot | kimi-k2.6 | kimi-k2.5 |
| ollama / lmstudio | qwen3:8b 等 | 本地,免 API key |
| **opencode** | — | **OpenCode CLI(Go/TS)作为本地 agent 执行后端,模型由 opencode 自管** |
| custom / mock | — | 任意 OpenAI 兼容中转站 / 离线 |

**界面(仿 claude-code)**:输入 `/` 即时弹出命令联想(↑↓选择 · Tab 补全 · Esc 关闭,
Windows msvcrt / Unix termios 双实现,管道调用自动降级);LLM 回复流入**圆角渲染块**;
ANSI 配色全局统一,`NO_COLOR=1` 降级纯文本。

**消息端**:

- `psyclaw serve telegram` — 双向 Telegram bot(白名单、/clear)
- `psyclaw serve wechat` — **个人微信双向 bot,走微信 iLink 网关**
  (Hermes Agent / OpenClaw 同款官方通道,支持语音转写、"正在输入"状态)。
  两种形态:独占直连 `ilinkai.weixin.qq.com`;或把 `ILINK_BASE_URL` 指向
  [HermesClaw](https://github.com/AaronWong1999/hermesclaw) 代理端口,
  与 Hermes/OpenClaw **同一微信号共存**。token 从已登录的 openclaw-weixin /
  hermes gateway 账号文件提取(`ILINK_TOKEN`),或 `serve wechat --login` 扫码
- `psyclaw notify "<消息>"` — 企业微信群机器人 webhook + Telegram 单向推送(HITL 审批提醒)

## 这一轮已落地

| 模块 | 文件 | 状态 |
|------|------|------|
| 设计稿 | `DESIGN.md` | ✅ 完整（架构/命令集/MCP/ARS/规范/HITL/多智能体/图片风格/路线图） |
| CLI 骨架 | `psyclaw/cli.py` | ✅ 可运行，命令契约即最终契约 |
| 配置向导 | `psyclaw/config.py` | ✅ 交互式环境变量设置 |
| ARS skill | `psyclaw/skills/ars/SKILL.md` | ✅ 端到端研究总编排（4 子技能） |
| MCP 目录 | `psyclaw/mcp/registry.yaml` + `manager.py` | ✅ SPSS/Mplus/Stata/Zotero/文献检索 |
| 学术规范 | `psyclaw/gates/PSYCLAW.md` + `rules.yaml` | ✅ 人读规范 + 9 条机器门禁 |
| 图片风格 | `psyclaw/gates/figure_style.yaml` | ✅ APA7/nature/frontiers + 诚实性门禁 |
| 门禁执行器 | `psyclaw/gates/checker.py` | ✅ 自检通过；产出校验接口契约 |
| 多智能体 | `psyclaw/agents/{planner,executor,critic}.md` | ✅ 职责隔离 |
| HITL 回路 | `psyclaw/commands/research-loop.md` | ✅ 规划→执行→审查→修复→审批→交付 |

## M1 新增（已验证可运行）

| 模块 | 文件 | 说明 |
|------|------|------|
| Provider 层 | `psyclaw/providers/` | Anthropic + OpenAI 兼容双协议,SSE 流式,base_url 可配,mock 兜底 |
| REPL | `psyclaw/repl.py` | 对话+流式输出+slash 命令+@file 引用+成本统计,PSYCLAW 规范自动注入 |
| 量表库 | `psyclaw/psych/scales.yaml` | DASS-42/21、PHQ-9、GAD-7、TIPI、RSES、PSS-10(条目映射/反向题/坑位注记) |
| 草率作答筛查 | `psyclaw/psych/careless.py` | longstring / IRV / 直线作答,纯 stdlib,标记≠剔除(走 HITL 审批) |
| 信度 | `psyclaw/psych/reliability.py` | Cronbach's α + 逐题删除 α + 解释规则 |
| 新门禁 | `gates/rules.yaml` | +DATA.careless、MEASURE.reliability(共 11 条) |

## M2 前半场新增（已数值校准)

| 模块 | 命令 | 说明 |
|------|------|------|
| 前提假设知识库 | `assume` | 16 检验族,每条假设:检查方法→违反对策→现代默认(Welch/bootstrap/HC3) |
| 可运行诊断 | `check` | 偏度峰度 z 检验、Brown-Forsythe Levene、经典 F + Welch F(自实现 F 分布,对照查表误差<.0005) |
| 复杂方法目录 | `method` | 13 方法卡:SEM/双因子/不变性/MLM/IRT/LPA/网络/RI-CLPM/LGCM/元分析/贝叶斯/TOST |
| 实验设计目录 | `design` | 12 设计卡:效度威胁、抵消平衡、功效要点、分析映射 |

## M2c 新增:澄清门禁·APA7 引擎·背书库·自进化记忆

| 模块 | 命令 | 说明 |
|------|------|------|
| 强制澄清(grill-me 式) | `clarify` | 17 槽位澄清卡;**不澄清完,`research` 拒绝启动**(CLARIFY.complete 门禁实测拦截) |
| APA7 输出引擎 | `export` | 零依赖直写 OOXML:Word docx + md 双输出,确定性模板(TNR 12pt/双倍行距/三级标题/悬挂缩进/页码),样例见 `examples/` |
| 方法学背书库 | `cite` | 26 个设计决策 × 经典文献(Welch→Delacre 2017;RI-CLPM→Hamaker 2015…),DESIGN.evidence 门禁要求决策必有引用 |
| 三层自进化记忆 | `memory` | 画像(显式)+决策惯性(自动学习,90 天半衰期,预填可推翻)+教训卡(critic/用户纠正→**HITL 确认后才生效**);只存方法学偏好不存数据 |

门禁累计 **13 条**。REPL 对话自动注入:学术规范 + 记忆 + "澄清先行"硬规则。

## M3 新增:内置 MCP · 长上下文 · 严谨性 · 研究回路

| 模块 | 命令/文件 | 说明 |
|------|-----------|------|
| **内置 MCP** | `psyclaw mcp --serve mne\|spss` | MNE(ERP 成分规范/预处理脚本/簇置换检验)+ SPSS(语法生成含 Welch/eta²/VIF,批处理执行);标准 stdio MCP,可挂 Claude Desktop |
| **长上下文** | `psyclaw/context.py` | 知识按需注入(30k→~200字符);历史滚动压缩留决策备忘;`@file` 智能摘录(CSV 79KB→240字符) |
| **严谨性协议** | `gates/rigor.md` + `STAT.rigor` | 蒸馏 psycho-vibe:先质疑识别假设、信息不足就停、强制 Step0-6、限定措辞 |
| **研究回路(真跑)** | `psyclaw research --freeform` | planner→确认→executor→critic→修复环→审批门→交付,产物全落盘(旧 `research-loop` 已并入 `research`) |

门禁累计 **14 条**。

## M4 新增:Plan 模式 · 任务追踪 · 上下文召回 · 审计 agent

| 模块 | 命令 | 说明 |
|------|------|------|
| **Plan 模式** | REPL `/plan [目标\|on\|off]`、`psyclaw plan [目标]` | 只规划不执行;计划末尾 `## TASKS` 复选框由机器**自动抽取为任务**,落 `notes/plan.md` |
| **目标(goal)** | `/goal [文本]`、`psyclaw goal` | 真源 `notes/goal.md`,与 research-loop 共用;`/plan <文本>` 顺带设目标 |
| **任务看板** | `/tasks`、`psyclaw tasks` | 真源 `.psyclaw/tasks.json` + 人读镜像 `notes/tasks.md`;`add/start/done/block/sync/clear`;歧义引用不猜 |
| **进度追踪** | 行首 `TASK_DONE: <任务>` | executor 标记、critic **过审后才生效**(不虚报);回路交付时打印进度条 |
| **上下文召回** | `/recall [查询]` | 每轮对话**全量存** SQLite(`.psyclaw/context/index.db`),固定词表+英文术语建关键词索引;调用时按查询覆盖率算相关度,**≥80% 才注入**(fail-closed) |
| **本地语义嵌入** | `psyclaw setup --groups embed` | 召回升级为**关键词+语义双通道**:model2vec 静态多语言模型(纯 numpy 无 torch,本地推理,`PSYCLAW_EMBED_MODEL` 可换模型);未装时用内置零依赖哈希 n-gram 向量兜底;语义门槛随后端走(真模型 80%/哈希 50%);`/recall reindex` 换模型后重建向量 |
| **审计 agent** | `/audit on\|off\|log` | auditor 逐轮评分(准确/相关/规范/完整);行首 `SCORE:`+`AUDIT_VERDICT:` 机器解析,解析不到按 IMPROVE;<80 自动草拟教训卡(仍需人工 confirm);记录 `.psyclaw/audits/audit_log.md` |

## M2b 新增:ARS-Stat 自动分析引擎(核心)

`psyclaw stat <data.csv> --dv 列 [--group 列 | --with 列 | --paired 列]` —— 把 `assume` 决策树变成可执行流程:

1. **自动选检验**:两组→独立样本 t · 多组→单因素 ANOVA · 两连续→Pearson · 配对→配对 t
2. **假设诊断驱动**:跑偏度/峰度 + Levene;**正态严重违反自动切 Mann-Whitney**(透明记录)
3. **效应量必报**:Cohen's d / η²+ω² / Pearson r / Cramér's V,全部带 95% CI
4. **APA7 结果段**:可直接入论文,含限定性措辞("显著≠重要""相关≠因果")
5. **可复现脚本**:生成独立 `.py`(scipy 实现)+ 数据指纹校验,落 `outputs/`

**数值全部由成熟统计库计算**(Welch/Student/配对 t、Pearson、Mann-Whitney、卡方、ANOVA 等);
分布函数(t/卡方/F/正态/非中心)统一由 scipy 提供。复现脚本独立运行结果与引擎完全一致(t=3.87/d=.83 闭环验证)。

## 统计引擎:Pingouin(默认核心)

ARS-Stat 默认用 [Pingouin](https://pingouin-stats.org/)——专为心理学设计,一个调用同时给出
**统计量 + 效应量 + 95%CI + 统计功效 + 贝叶斯因子**(scipy 只给 t/p),正好满足
PSYCLAW "效应量+CI 必报" 门禁。封装见 `psych/pingouin_backend.py`,函数选择指南见
`skills/pingouin/SKILL.md`。覆盖:独立/配对 t、单因素/重复测量(球形性+ε 校正)/混合/ANCOVA、
相关(含偏/稳健)、bootstrap 中介、信度、功效分析、FDR 多重比较——全部对照 live pingouin 验证。

> 搜遍 skill/plugin 生态,没有现成的 pingouin 心理学封装,故纳入 PsyClaw 自建。
> 统计计算统一复用成熟库——scipy/pingouin 为主干,statsmodels(回归族/GLM)、lifelines(生存)、
> factor_analyzer(EFA)、semopy(CFA/SEM)按需,均为配置时安装的硬依赖。

## 选装(开箱即用)

`psyclaw setup` 检测能力矩阵:**`stats` 核心组(pingouin+scipy+statsmodels)默认安装**;
`viz`(matplotlib/seaborn)、`eeg`(mne)、`full`(rich/prompt_toolkit)按需选装;
商业软件(R/SPSS/Mplus/Stata)只检测不分发。

## M4 新增:回路真跑分析 + R 后端

- **research-loop 自动跑 ARS-Stat**:executor 阶段自动在 `data/clean|raw` 找 CSV,
  据澄清卡猜 dv/group,跑真分析,结果+复现脚本落 `outputs/`,critic 审查真实统计产物。
  实测:回路自动产出 `t(84.3)=3.87, d=.83`,复现脚本独立运行还原一致。
- **R/lavaan 后端**(`psyclaw stat <data> --method cfa|sem|mlm|omega|invariance`):
  CFA/SEM(lavaan,MLR/WLSMV,拟合指数全报)、MLM(lme4+lmerTest,自动算 ICC)、
  ω 信度(psych,McNeish 2018 背书)、测量不变性(ΔCFI≤.010 判据)。
  R 在则真跑,不在则输出可运行脚本骨架——补上 Python 生态薄弱的 SEM/MLM/ω。

## M5 新增:文献检索 + 全文获取(合法 OA)+ Zotero

`psyclaw lit <检索式>` —— 多源检索 + **全文获取**,打通第一象限"文献调研":

- **多源检索**:OpenAlex(覆盖最广,自带 OA 状态,倒排摘要还原)、Europe PMC(心理/医学)、
  arXiv/预印本;自动去重(DOI 优先),PRISMA 计数落 `notes/prisma_search.md`(对接 LIT.prisma 门禁)
- **全文获取(只走合法 OA)**:`psyclaw lit --fulltext <DOI>` 按优先级取——
  Europe PMC OA 全文(直接给正文)→ Unpaywall 合法 OA PDF → arXiv/预印本 PDF。
  **付费墙绝不绕过**:只取摘要 + 明确标注,引导用机构权限或 Zotero
- **Zotero 文库全文**:`psyclaw lit --zotero <DOI>` 从你**自己已购**的 Zotero 文库取全文
  (付费墙文献的合法来源,你有访问权);Web API v3 直连,复用 Zotero 的 PDF 全文索引

合规原则:检索走公开学术 API;全文只走开放获取或你自己有权访问的来源,不绕过任何付费墙。

### 机构权限(统一访问层)

`psyclaw auth` —— 统一处理机构图书馆访问,**绝不存密码**:

- **配置** `psyclaw auth --set`:EZProxy 前缀 / LibKey(library id + key)/ 机构名,
  写 `~/.psyclaw/institution.json`(无密码字段)
- **全文付费墙路径**:OA → **LibKey**(机构订阅 API,DOI 直接返回有权访问的全文)→
  **EZProxy**(把链接改写成机构入口,你用已登录浏览器的 SSO 会话打开,PsyClaw 不碰密码)→
  Zotero 文库 → 仅摘要
- **认证状态记录** `psyclaw auth --verify`:连通自检(LibKey API 响应?EZProxy 可达?
  出口 IP 在校园网段?)并把方式 + 上次验证时间 + 是否在校园网写回 institution.json
- 安全红线:EZProxy/SSO 用你浏览器的已登录会话;LibKey key 是机构发现 key 非个人密码;
  不用任何凭据自动爬全文(违反图书馆 TOS)

## 下一步（路线图见 DESIGN.md §10）

~~M1~~→~~M2a~~→~~M2c~~→~~M3~~→~~M2b~~→~~M4~~→~~M5 文献检索+全文+Zotero~~ ✅。
**四象限(文献·设计·统计·写作)主干已全部打通。** 后续:审稿模拟(academic-paper-reviewer 接入)、
ARS skill 把全链编排成一句话"研究 X"、knowledge 抽取自动入综述。

## 血统

claude-code（REPL/命令/Tool 抽象）· codex（exec/审批）· OpenClaw（provider）· AutoResearchClaw（pipeline/skills/MCP）· 你的 `A_便携分析包/01_HITL工作流`（多智能体 HITL 模式）。
