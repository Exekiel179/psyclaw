# Changelog

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
