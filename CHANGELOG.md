# Changelog

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
