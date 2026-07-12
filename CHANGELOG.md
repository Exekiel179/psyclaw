# Changelog

## Unreleased

### 改进
- **运行行为统一**(feat-078):`run` 公开收敛到 literature/analysis/meta/qualitative 四条稳定
  workflow,默认连续执行;新增 `--confirm-each`、`--exploratory`、`--resume`。每步写原子检查点,
  恢复时校验流程定义、目标、输入和产物。`prepare` 成为研究准备公开命令。`auto` 验收失败改记
  “需要处理”,本轮避免空转、下次可重试;迭代上限按单次运行计算。旧参数和旧入口继续兼容。
- **用户术语统一**(feat-077):用户界面、CLI 帮助、研究准备清单、内置研究指令与当前文档
  不再使用生硬的直译词。研究开始前统一称“前置检查”，产出规范校验统一称“质量检查”，
  原有 17 项澄清内容统一称“研究准备项”。`gates` 命令、规则 ID 和内部字段保持兼容。
- **交互心智模型收敛**(feat-076):公开入口统一为 `chat / run / auto`。缺省 `psyclaw`
  进入 Chat;`run analysis|meta|literature|qualitative|research|task` 路由到既有 workflow/
  pipeline/loop;`auto` 复用自主回路。旧 `agent/loop/*-loop/auto-loop/research/repl` 保持
  兼容,退出默认帮助与主文档。REPL 同步提供 `/run`、`/auto`、`/approval ask|auto`、
  `/access open|safe`,旧 `/agent /research-loop /yolo /safemode` 仍可调用。
- README、教程、命令地图、架构文档、启动横幅、状态建议、文件分析提示和内置研究 skill
  已统一到三入口模型;新增共享路由 `psyclaw/modes.py`,不复制现有执行逻辑或放松质量检查。

## v0.12.0(2026-07-11)

> 主题:**自学习进 agent 模式 + 数据→结果→稿件闭环补完 + 可评测(eval harness)**。
> 把 v0.11 的错误自学习/图片渲染从 REPL 扩到 agent(toolloop),补上 v0.10 遗留的
> 「真结果回填稿件」,再给整个编排层配一套确定性离线评测;期间根据用户实测反馈
> 修了 4 个交互问题。

### 新增
- **eval harness**(feat-073):`psyclaw eval` 确定性离线评测——6 用例 28 检查覆盖
  分析/元分析编排、文献初筛诚实降级、门禁 fail-closed、错误自学习、toolloop 纪律;
  不调 LLM、不联网、不依赖统计库,秒级复跑;`--case`/`--json`,报告落
  `.psyclaw/eval_report.json`,有失败退出码 1。用例崩溃记失败 check,绝不静默。
- **replication-package 声明**(feat-074):`provenance --journal <期刊>` 遇
  `data_availability=required`(Psych Science/JPSP/Psych Bulletin)时强制生成
  replication-package 声明(脚本 sha256+数据指纹+环境清单,文本可直接放进稿件
  数据可得性节);新门禁 `REPRO.replication_package` 拦「要求却未声明」,
  非强制期刊/旧 sidecar 放行(门禁只增不删)。
- **错误自学习 + 图片渲染进 agent 模式**(feat-065):toolloop 失败工具结果当轮
  蒸馏环境教训回灌止损(只看 ok=False,防把读到的日志当本机事实),随结果返回
  `lessons` 由 REPL/CLI 落卡;`render_images_in_text` 共用,agent 出图也内联显示。
- **教训卡正向加固**(feat-066):同一环境教训再现 → active 卡强度+1(记
  `reinforced_ts`)、pending 卡 hits+1;注入按强度降序,CLI 显示再现次数。
- **@图片 引用内联渲染**(feat-069):`@路径` 是图片时终端直接显示,上下文只注入
  元信息;修掉此前把二进制乱码灌进上下文的问题。
- **pystat 元分析闭环**(feat-072):pystat MCP 新增 `pystat_meta`(DL 随机效应:
  合并效应+95%CI+I²/τ²/Q+Egger);meta 流程 best-effort 直跑落
  `outputs/meta_result.txt`;写作步把 pystat **真跑结果**注入上下文(结果节只引用
  真实数值,效应量+CI 必报);`_real_result` 守卫——「统计库未安装」的脚本骨架
  不算真结果,不制造『看着像跑过了』的假象。[stats] 数值实测:statsmodels/pingouin
  真装真跑,生成脚本与 MCP 工具输出数值一致。

### 改进 / 修复(均来自用户实测反馈)
- **确认提示自解释**(feat-067):`[Y/n/a=…]` 改
  `[回车=同意 / n=拒绝 / a=同意且本会话此类不再问]`,行为不变。
- **选择器改原地内联**(feat-068):弃 prompt_toolkit 全屏蓝色对话框(Windows 上
  突兀),Claude Code 式 `_pick_inline`:↑↓/数字/空格/回车/Esc/打字自由作答,
  ANSI 原地重画不清屏不进备用屏。
- **「全部同意」按命令前缀限定**(feat-070):对 `git status` 说 a 不再放行所有
  shell 命令——`cmd_approval_scope` 按程序/子命令归类(`git status ≠ git push`,
  复合命令不泛化);危险命令红线不变(永远逐条问)。
- **选择器看得见方案详情**(feat-071):按终端宽度截断 + 高亮项下方 2 行详情区
  给全文;系统约定选项文字自包含、方案细节先写正文。

## v0.11.0(2026-07-09)

> 主题:**REPL 交互体验大修 + 错误自学习闭环 + 图片内联渲染**。
> 起于用户一次真实的 MNE/ERP 分析实测——把「反复问 y、输入被吞、卡住等『继续』、
> 每轮重踩环境坑、图只能看路径」这些卡点逐个治本。

### 新增
- **`/dump` 导出对话**(feat-055):`/dump [路径]` 导出当前对话为 Markdown;`/dump --full`
  连同平时不展示的隐藏上下文(system 提示 / 滚动决策备忘 / 每轮持续注入的约定片段)一并导出。
  纯渲染在 `psyclaw/transcript.py`,拒写受保护的 `data/raw`。
- **`/yolo` 审批模式**(feat-056):开启后命令 / 文件覆盖 / 工具副作用**自动放行**,只有命中
  红线的危险命令(`rm -rf`、`push --force`、`DROP TABLE`…)仍问人——「只在必要时请求人介入」。
  `data/raw` 与密钥文件始终硬拒。`config approval=yolo` 设默认。
- **确认支持「全部同意」**(feat-064):非危险副作用的确认改为三态 `[Y/n/a]`——选 `a` 则
  **本会话该类**(执行 shell / 覆盖文件 / 工具副作用)不再逐条问,「确认一次、同类就统一」;
  比 `/yolo` 更细粒度。危险操作永远逐条问、不给「全部」(红线不放松)。
- **错误自学习**(feat-058):命令失败经 `distill_env_lessons` 蒸馏出可复用的**环境教训**
  (命令不存在 / 模块未装 / API 改名),记入本会话记忆**每轮注入止损**,并落 `memory` 待确认卡
  (跨会话,经 `/memory confirm` 生效)——不再每轮重踩 `python`→`python3`、缺 mne、`erpcore` 改名。
- **环境教训卡自动失效**(feat-059):环境恢复了(装上库/命令有了)就自动归档过时的负卡,别反向
  误导模型。`memory.archive_lesson` 落实「被推翻则归档」;启动秒验证命令类(`shutil.which`),
  `/memory verify` 全量再验证(含 module/attr 真跑 import);只在**确证已恢复**时失效(防误删)。
- **终端内联渲染图片**(feat-061):`/img <路径>` 手动、命令出图**自动**内联显示(分析脚本 print
  出的图直接出现在对话里)。纯 stdlib(终端解码,只 base64 字节):iTerm2 / kitty 协议,按环境探测
  iTerm2 / WezTerm / VSCode / Warp / kitty;`config image_protocol` 可强制。

### 改进 / 修复
- **自动跟进不再中途卡死**(feat-057):流式路径的命令/读取跟进改由 **no-progress 检测**停机
  (连续重复相同请求即判原地打转),低深度上限(原 3 步)降级为高位安全兜底(100,`config` 可调)。
  多步分析(下载→装依赖→跑→报错→修→重跑)一口气跑完,不再停下等人说「继续」。
  no-progress 只在**自主回合**(YOLO 自动跑 / 自动读)计数——用户在逐条确认(打 y)本身就是
  在推进,不会被误判成「原地打转」而掐断(feat-063)。
- **确认框不再与命令回显串行**(feat-056):`_ask_yn` 经 `ui_input.safe_prompt` 用 `\001\002` 包裹
  彩色码,修 readline 把 ANSI 算进光标宽度导致回显错位;超长命令单独打一行、提示只留一句短话。
- **选择器非编号输入不再被吞掉**(feat-060):单选提示「编号」时用户打了 `y` 之类会被静默丢弃、
  变死胡同;现在非编号的输入当作对该问题的**自由作答**转发给模型继续,只有回车才算跳过。

## v0.10.0(2026-07-07)

> 主题:**数据→结果端到端闭环**——analysis 流程直接经 pystat MCP 出结果。

### 新增
- **analysis 分析步接 pystat MCP**(feat-053):`psyclaw analysis <data.csv>` 的分析步此前
  只生成 `outputs/analysis.py` 让用户手动跑;现在在生成脚本后**自动经 pystat MCP 直接运行**
  推荐的分析,把结果写到 `outputs/analysis_result.txt`。`pystat_bridge` 把 `recommend_analysis`
  的检验类型 + 角色列纯映射到 pystat 工具(t 检验/方差/回归/相关/描述),经 MCP 客户端执行:
  装了 `[stats]` 则回带**效应量 + 95% CI** 的真结果,未装则回 pystat 的降级脚本——无论哪种都多
  一个具体产物。全程 fail-safe:pystat 不可用/异常绝不阻断流程(生成的脚本仍在)。
  至此「数据 → 画像 → 推荐分析 → pystat 出结果」端到端闭环:v0.5 让 agent 能调 MCP、v0.8 建了
  pystat 后端、本版把 workflow 也接上。

## v0.9.0(2026-07-07)

> 主题:**一键配置基础环境**。

### 新增
- **`psyclaw setup --env`**(feat-051):一条命令诊断并配好跑 psyclaw 所缺的基础环境——
  检查 ① 配置文件是否已建 ② LLM provider 是否配了 API key(否则只能走 mock 占位)
  ③ `stats` 组(pingouin/pandas/scipy:pystat 真算、跑生成的统计脚本)④ `full` 组
  (prompt_toolkit/rich:REPL 实时联想)。每项给 ✓/✗ + 确切修法 + 能否自动装;
  加 `--online` 则一键 pip 装可自动修的缺失组(stats/full),不能自动的(API key)列为待手动。
  装失败如实报告、不阻断。

## v0.8.0(2026-07-07)

> 主题:**闭环「统计外移到 MCP」**——agent 现在能直接调用统计后端。

### 新增
- **pystat MCP 服务器**(feat-049):`psyclaw/mcp/servers/pystat_server.py`,委托
  pingouin/pandas 的常规统计后端(描述统计、t 检验、相关、单因素方差、多元回归、选检验指引)。
  照既有 MCP 惯例:统计库在则真跑并返回带**效应量 + 95% CI**的结果(符合门禁),不在则返回
  可直接运行的脚本骨架(不假装算结果)。本体顶层零统计 import——统计只在工具被调时惰性发生。
- registry 早已声明 `pystat` 却一直缺 server 文件与 `command`,导致 v0.5 的 agent-MCP 接入
  (feat-040)浮不出它;本版补齐后,`agent`/REPL 的工具集自动多出 6 个 `mcp__pystat__*` 工具——
  **agent 可在多步推理里把 t 检验/方差/回归直接委托给 pystat**,「统计外移到 MCP」自此闭环。

## v0.7.0(2026-07-07)

> 主题:**REPL 交互体验**——修方向键/历史/光标(用户报告的 `^[[A` 问题)。

### 修复
- **REPL 方向键/历史/光标**(feat-047):此前在未装 `prompt_toolkit` 的环境(如 `uv tool`
  默认装的解释器)里,REPL 按方向键会漏出 `^[[A`、没有命令历史、光标不能左右移动——根因是
  非 prompt_toolkit 的 TTY 落到了自研逐键 raw reader。现改为优先走 stdlib **readline** 后端:
  ↑↓ 翻历史、←→ 移光标、Ctrl-A/E/K 等键位、以及 `/` 命令 Tab 补全全部可用;readline 缺失
  (Windows 等)再退回原 raw reader。装了 `psyclaw[full]` 的仍走 prompt_toolkit(实时联想下拉)。

## v0.6.0(2026-07-07)

> 主题:**多轮对话 + 工具调用稳**。审计工具循环、实测复现真实故障点后逐个加固。

### 工具调用健壮性(多轮不出问题)
- **参数规范化**(feat-043):模型把 args 写成 `list` 或双重编码 JSON 字符串
  (`"args":"{...}"`)时,此前内置工具 `a.get()` 崩且被**误标成功**——现统一规范化
  (JSON 对象字符串自动解析、非对象报错引导模型重发),`name` 须非空字符串,工具异常如实标失败。
- **无进展检测**(feat-044):模型反复用相同参数调同一工具、或返回空回复,不再空转到迭代
  上限——有限追问后 `stopped=no_progress` 收敛,不静默、不卡死。
- **消息序列不变量**(feat-045):每次调 provider 前规整消息(去空 content、合并连续同角色、
  首条必为 user),防多轮回灌拼出非法序列触发 Anthropic/OpenAI 的 400。
- **多轮集成测试**:一段贯穿正常调用→畸形 args 自纠→截断续写→未知工具→重发→答案的真实
  序列,断言全程工具不崩、失败如实上报、provider 只收到合法消息。

## v0.5.0(2026-07-07)

> 主题:**编排纵深——agent 真正会用 MCP** + provider 健壮性 + agent 可观测。
> (含此前未单独发版的 v0.4 工件:feat-036/037/038。)

### 编排纵深:agent 接入 MCP(统计外移从"目录"兑现成"可调用")
- **MCP stdio 客户端**(feat-039):`psyclaw/mcp/client.py`——JSON-RPC over stdio,
  惰性起子进程 + initialize 握手 + 超时 fail-safe;进程异常/坏 JSON/服务器报错优雅降级不抛。
- **agent 循环接入 MCP 工具**(feat-040):`agent`/REPL 的工具集自动并入**已启用+健康**的 MCP
  服务器工具(`mcp__<server>__<tool>` 前缀、fail-closed 批准、客户端进程级复用、连接失败不拖垮)。
  例:装了 MNE 的机器上 agent 可直接调 `mne_info`/`erp_components` 等做 EEG/ERP 分析。
  `PSYCLAW_MCP_TOOLS=0` 可整体关闭。

### 长会话可靠性
- **compact_history LLM 蒸馏**(feat-041):超预算压缩时,有 key 的 provider 会把被移出上下文的
  早期轮次蒸馏成**结构化决策备忘**(比规则截断保真);无 key/异常/离线 → fail-safe 回落规则蒸馏。

### provider 健壮性 + agent 可观测(v0.4 工件)
- **provider 网络重试**(feat-036):429/5xx/网络异常首字节前指数退避重试(≤3 次);HTTP 错误读
  响应 body 显性化;流开始后不重试(防重复消费)。
- **agent 运行痕迹**(feat-037):每次 agent 运行落 `.psyclaw/agent_runs.jsonl`,
  `psyclaw agent --history [n]` 回看最近 n 次。

### 其他
- 版本号 0.3.0 →(跳过未发版的 0.4)→ **0.5.0**(pyproject + `__version__`)。
- 全量测试 1242 passed。

## v0.3.0(2026-07-07)

> 主题:**agent 执行面安全加固 + 长会话可靠性**(「对话长期维持、不中途停」)。

### 长会话可靠性
- **截断防护**(feat-030):provider 输出被 max_tokens 截断时,未闭合的 ```tool 块不再被
  误判为最终答案——检测截断并请求模型重发完整块(连续超限才停,`stopped=truncated` 不静默);
  providers 捕获 `stop_reason`/`finish_reason`(归一化);`PSYCLAW_MAX_TOKENS` 环境变量可配
  (默认 8192);`agent --max-iters` 默认 6→24。
- **上下文滚动修剪**(feat-033):toolloop 循环内旧轮次工具结果压缩为「工具名+输出首行」摘要
  (最近 3 轮保完整),长任务不再撑爆上下文;调用方历史与 assistant 回复不碰。

### 安全加固(外部安全审查 HIGH/MEDIUM 修复)
- **shell 执行 fail-closed**(feat-031):REPL 命令块里的 shell 命令**每条**须人工确认才执行,
  危险模式正则降级为确认提示里的 ⚠ 标签(拒绝清单不是安全边界);psyclaw 进程内子命令保持自动。
- **save_file 路径允许清单**(feat-032):agent 的 save_file 工具只能写项目根内;拒 `../` 逃逸、
  项目外绝对路径、软链接目标、凭据类路径(`.env`/`id_rsa`/`*.pem`/`.ssh`/`.aws` …)。

### 其他
- `normalize_type` 补 22 个中文研究类型别名(『元分析』『文献综述』『质性研究』…)——中文入口
  的技能推荐路由不再落空(feat-034)。
- 版本号统一:`pyproject.toml` 与 `__version__` 对齐 0.3.0(v0.2 发布轮 pyproject 漏改)。
- 修 2 例陈旧 MCP 测试断言(mplus/stata 改 detect: 门控后未同步)。
- 全量测试 1212 passed。

## v0.2.0(2026-07-03)

> 主题:**机制可以复杂,命令要简单**。默认三条路:`status` → `auto-loop` → `check`。

### 命令简单化
- `--help` 只列常用命令(全部命令**照常可用**,`psyclaw commands` 看完整分类,epilog 指路)。
- `psyclaw guide` 重写为决策树;新增手把手教程 `docs/TUTORIAL.md`。
- **`psyclaw status`**:一屏态势(目标/澄清/回路/等人决策直接打印/下一步建议)。
- **`psyclaw check`**:投稿前一键质检(JARS + 引用保真(+期刊风格)+ 复现溯源 + KG 溯源)。

### 用户自定义
- **命令别名**:`~/.psyclaw/aliases.yaml`(全局)/ `<项目>/.psyclaw/aliases.yaml`(项目),
  一行一条 `qc: check --journal xinlixuebao` → `psyclaw qc 稿件.md`。内置命令优先,不可劫持。
- **插件系统**:`.psyclaw/plugins/*.py` 暴露 `register(api)`——注册 agent 工具 / REPL 命令 /
  system 片段;坏插件隔离加载。`psyclaw plugins` / REPL `/plugins`。
- **用户 MCP 注册表**:`.psyclaw/mcp.yaml`(项目/全局)并入目录。
- skills / MCP / plugins 列表统一标注 **内置 / 用户·项目 / 用户·全局**。

### 内置 skill 可同步更新
- `psyclaw skills --sync [name|all]`:带 `upstream.json` 的内置 skill(ctx2skill / opid …)
  从上游仓库同步到 `<skill>/upstream/`,适配层 SKILL.md 保持薄壳。

### 研究编排与学术诚信(0.1 → 0.2 期间累积)
- **auto-loop** 自主科研回路(发现→派发→独立验收→记状态→决定;感知阶段列相关技能包)。
- **cite-check** 引用保真(孤儿引用=疑似杜撰)· **provenance** 复现溯源 · **期刊画像**(`journal`,
  cite-check/provenance `--journal` 定制)· **kg** 带引用知识图谱 · **search** 来源路由检索。
- 门禁可**用户显式跳过**(`--skip-gates`:留痕 `notes/gate_skips.md`,产出标探索性;默认 fail-closed 不变)。

### 交互与感知
- REPL:**键盘选择器**(模型给选项自动弹,方向键/编号)· **文件读取 open/safe**(默认模型可
  ```read 自动读;`/safemode` 切安全模式须 `@` 引用;`data/raw` 恒拒)· **天然保存**(说"存到 X"
  即落盘)· 会话名进提示符 · **agent 模式**(模型自主多步调工具,副作用需批准)。
- **本地项目感知**:有界目录树每轮注入(`data/raw` 只报数不列名);PDF 正文抽取(pypdf 优先,
  stdlib 兜底,乱码不入上下文)。
- **会话持久化**:SQLite+FTS5,`resume` / `session` / REPL `/sessions /rename /search`。

### 生态
- 发现并按研究类型推荐第三方技能包(AcademicForge / AJS,`skills --for <type>`)。

## v0.1.0(2026-06)

- 重定位为纯研究编排 harness:统计整体外移(删 42 手写统计模块),零统计库依赖。
- research 流水线 · 审稿模拟 · clarify 澄清 · 预注册 · 知识目录 + 量表计分 · lit + export ·
  三层记忆 · 学术门禁 gates · REPL · Workflow 引擎(四类研究流程)。
