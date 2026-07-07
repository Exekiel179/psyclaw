# PsyClaw Session Progress Log

## Current State

**Last Updated:** 2026-07-07(晚:v0.3.0 发布 + v0.4 三 feature)
**重大转向:** PsyClaw 从「全流程统计 CLI」重定位为「纯研究编排 harness」——
统计计算整体外移到成熟库/MCP,本仓删除全部手写统计实现。

> 状态真源:`feature_list.json`(机器可读)。本文件是人读的「接续上下文」快照。

## 本轮(24):v0.3.0 发布 + v0.4(provider 健壮性 + agent 可观测)——feat-031..038 done

用户定调:『完成 v0.3 开发后写新计划,然后完成每一条』。两个版本周期一口气落地:

**v0.3.0(已发布,版本号统一 0.3.0)**——主题:安全加固 + 长会话可靠性
- feat-031 shell fail-closed(外审 HIGH):REPL 命令块 shell 每条须确认,拒绝清单降级为 ⚠ 标签;
- feat-032 save_file 路径允许清单(外审 MEDIUM):项目根内+拒软链/凭据(save_path_denied);
- feat-033 toolloop 上下文滚动修剪(旧轮次工具结果压缩为「工具名+首行」,近 3 轮保完整);
- feat-034 normalize_type 补 22 个中文研究类型别名;feat-035 版本对齐+CHANGELOG v0.3 段。

**v0.4(进行中,feat-036/037 done,feat-038 本条)**——主题:provider 健壮性 + agent 可观测
- feat-036 _post_sse 网络重试(首字节前 429/5xx/网络异常指数退避 ≤3 次;HTTP 错误读 body
  显性化;流开始后不重试防重复消费);
- feat-037 agent 运行痕迹持久化(.psyclaw/agent_runs.jsonl + `psyclaw agent --history [n]`,
  CLI/REPL 双入口自动落痕;live e2e 验证);
- feat-038 docs 同步(COMMANDS agent 行 v0.3/v0.4 特性、TUTORIAL 加「shell 命令逐条确认」行)。

全量 **1222 passed**(uv python 3.12)。本机开发环境:`uv tool install --editable .` 已把
psyclaw 注册为命令(0.3.0);测试统一 `uv run --python 3.12 --with pytest python -m pytest -q`。

## 本轮(23):toolloop 截断防护 ——feat-030 done(修「工具调用中途提前停止」)

用户痛点:『对话不能长期维持,AI 在工具调用过程中提前停止』。根因诊断+修复:

- **根因**:provider 输出被 max_tokens 截断 → ```tool 块未闭合 → parse_tool_calls
  解析不出调用 → run_tool_loop 误判为最终答案 → **静默提前终止**。叠加:providers
  完全忽略 stop_reason/finish_reason;anthropic max_tokens 硬编码 4096;agent 默认 6 轮上限。
- **修复**:`toolloop.py` has_truncated_tool_block + _TRUNC_NUDGE 续写(连续 >2 次才停,
  stopped=truncated 不静默;完整调用+尾部残块 → 执行并告知);`providers/base.py`
  last_stop_reason;anthropic 捕获 message_delta.stop_reason,openai 系归一化 length→
  max_tokens;PSYCLAW_MAX_TOKENS 可配(默认 8192);agent --max-iters 6→24。
- **测试**:test_toolloop +6 例;另修 test_mcp_servers 2 例陈旧断言(3d9b183 改 detect:
  门控后未同步)。全量 **1190 passed**(uv python 3.12;本机无 3.11+ 系统解释器,用 uv)。
- **全流程冒烟(六环节)**:① status 环境感知 ✓ ② agent 工具循环 live 实跑
  (2 轮 1 调用收敛)✓ ③ ContextArchive 记忆写入+召回 ✓ ④ auto-loop 感知→决策→收尾
  (非 TTY fail-closed 不挂起)✓ ⑤ gates 门禁自检 ✓ ⑥ 技能发现 39 个+类型路由推荐 ✓。
- 已知小坑:recommend_skills 的 normalize_type 不识别中文『元分析』(英文 meta 可);
  本机(macOS)只有 python3.9,测试统一走 `uv run --python 3.12`。

## 本轮(22):v0.2 发布 ——feat-029 done

用户定调:『机制可以复杂,但命令要简单化;支持用户自定义;内置 skill 能同步更新;出 v0.2』。

- **命令简单化**:`--help` 收敛到 CORE_COMMANDS(全部命令**照常可调用**,epilog 动态指路
  `psyclaw commands`/guide/TUTORIAL;test_cli_help 契约随之更新为『帮助只列常用、全部可调』)。
- **用户别名**:`psyclaw/aliases.py`——`~/.psyclaw/aliases.yaml`(全局)+ `<项目>/.psyclaw/
  aliases.yaml`(项目覆盖全局),`qc: check --journal xinlixuebao` → `psyclaw qc 稿件.md`。
  shlex 解析、**内置命令优先不可劫持**、异常 fail-safe;`commands` 底部列别名。
- **内置 skill 同步**:纳入另一会话实现的 `skills --sync`(upstream.json → `<skill>/upstream/`,
  ctx2skill/opid 薄壳适配)+ 其测试,一并入 v0.2 提交。
- **版本**:`__version__` 0.1.0→**0.2.0**;新增 `CHANGELOG.md`(v0.1→v0.2 全量变更)。
- 验证:+6 别名测试 + 帮助收敛契约改写;全量 **1163 passed**;e2e:`--help` 尾行
  『只列 31 条…全部 51 条』、`version`=0.2.0、别名 qc 展开实跑。

## 本轮(21):REPL 交互升级 + 插件系统 + 统一 scope ——feat-027 / feat-028 done

用户连发四个实测痛点/需求,全部落地:

**feat-027 REPL 交互升级**:
- **键盘选择器**(痛点:模型列『• [ ] 研究1a…』复选清单但只能打字):`choices.py`——模型输出
  ```choices JSON 块(system 约定)或自发复选清单(启发式)→ 弹选择器(ptk 对话框方向键+空格
  → 编号输入兜底 → 非 TTY 不弹),选完**自动回传续聊**。
- **文件读取权限**(痛点:模型说"我无法读取CSV"要用户 @;用户定调:默认放开,安全模式才要求 @):
  open(默认)=模型输出 ```read 块 REPL 自动读取注入(CSV 结构+样例/PDF 抽正文;**data/raw 恒拒**;
  每轮≤4 文件、自动跟进深度≤3 防打转);`/safemode` 切 safe=一切读取须 @ 显式引用。
- **会话名可见**(痛点:/rename 后看不出来):会话名进提示符 `psyclaw·测试 ❯`,plan/agent/safe
  模式同显;resume 带回名字。

**feat-028 插件系统 + 统一 scope**(用户要求):
- 插件=`<项目>/.psyclaw/plugins/*.py` 或 `~/.psyclaw/plugins/*.py` 暴露 `register(api)`:
  add_tool(进 agent 工具循环)/add_command(进 REPL slash+补全)/add_system。逐插件隔离加载
  (坏插件不拖垮宿主);内置同名优先不被劫持。`psyclaw plugins` + `/plugins`。
- **skill/MCP/plugins 统一标注 内置/用户·项目/用户·全局**:skills 按根归类(顺手修真 bug:
  字符串前缀误判 F:/proj-data∈F:/proj → 改 is_relative_to);MCP 支持用户注册表
  `.psyclaw/mcp.yaml`(项目/全局,内置优先防劫持);plugins 项目/全局。
- 验证:+20 测试(choices_reads 12 / plugins_scope 8);全量 **1154 passed**;命令 45 条。

## 本轮(20):易用性收敛套件 ——feat-026 done

对整项目做易用性审查(用户定调:易用性/降认知成本为主,准确性次;门禁可跳但**须用户显式要求**)。
审查结论:准确性强、易用性欠债——42 命令、8 编排入口、4 种搜索、状态散落 8 文件、模型看不见本地目录。
一揽子落地五件:

- ① **`psyclaw status`**:一屏态势(目标/澄清/回路/**等人决策直接打印内容**/最近产物/下一步建议,
  复用 discover_backlog)。`psyclaw/status.py`。
- ② **本地项目感知**(用户实测痛点"psyclaw 感知不到文件夹"):`project_sense.py` 有界目录树
  (限深限条跳噪声;**data/raw 只报文件数不列名**)每轮注入 REPL system;agent 工具集加 `list_dir`。
- ③ **门禁用户跳过**(用户决定:不分级,显式要求即跳):`run_workflow(skip_gates)` + auto-loop/四
  type-loop `--skip-gates`;跳过留痕 `notes/gate_skips.md` + 总验收 `gates_skipped`/`exploratory` 标注;
  **默认 fail-closed 行为不变**(测试锁死)。
- ④ **`psyclaw check`** 投稿前一键质检:JARS + 引用保真(+期刊风格)+ 复现溯源 + KG 溯源,
  一屏 ✓/✗/⚠,每项独立 fail-safe。`psyclaw/checkup.py`。
- ⑤ **入口收敛**:guide 重写为"默认三条路径(status→auto-loop→check)+ 按需分支"决策树;
  session 帮助淡出 search 子动作(统一检索入口 = `psyclaw search`)。
- 验证:+20 测试(status_sense 10 / gate_skip 4 / checkup 6);全量 **1135 passed**;end-to-end:
  status 亮出 blocker、check 抓出 JARS 缺项+杜撰引用、guide 出决策树、raw 文件名不泄。

## 本轮(19):纯工具层循环 agent(模型自主多步调工具)——feat-025 done

用户:"要模型自主用多工具,要纯粹的工具层循环的支持作为保底"。关键判断——**不绑 provider 原生
function-calling**(mock 和不支持的模型就废),用**文本约定的工具协议**(```tool JSON 块),任何文本
模型都能跑=保底;支持原生的 provider 以后可另接高性能通道。

- `psyclaw/toolloop.py`:`parse_tool_calls`(纯)+ `build_tools`(把既有能力暴露为 5 工具:search[feat-022]
  /read_file[含 PDF feat-021]/save_file[feat-024 护栏]/kg_query[feat-023]/recall[feat-013])+
  `render_tool_catalog` + `run_tool_loop`(chat→解析 tool 块→执行→回灌→续,无块=最终答案/到顶=max_iters)。
- 守 fail-closed:**副作用工具(save_file)需 approve 批准**(HITL 留环里)、max_iters 防打转、只读自动跑、
  data/raw 硬护栏在工具内继续生效、`emit` 事件流对接"流式中间结果"(⚙ 调用 …)。
- REPL:`agent_mode` + `/agent` 开关 + `_run_agent`(ask 分支)。CLI:`psyclaw agent <task> [--auto]`。
- `tests/test_toolloop.py` 13 例;全量 **1115 passed**;离线 end-to-end:脚本 provider →
  recall → save_file(批准)→ 最终答案,3 轮收敛,out.txt 实际写出。
- 这正是我先前说的:工具循环不是不能用,而是**要就用文本约定做 provider 无关的保底**;原生
  function-calling 与 MCP 工具接入留作后续增强点。

## 本轮(18):「天然」保存文件(REPL 无需命令落盘)——feat-024 done

用户实测:PsyClaw 说"我无法创建文件"让人复制粘贴。追问"不加命令不能天然支持么"。
诊断:REPL 是纯对话循环,LLM 没有写文件的**动作通道**,只能吐文本。三条桥:①/save 命令(需触发)
②function-calling 循环(重、依赖 provider、安全升级)③**提示约定+自动落盘**(天然、provider 无关)。选 ③。

- `repl.py`:`_SAVE_SYSTEM` 注入系统提示("要保存文件时用 ```save path=… 块输出");`ask()` 每轮调
  `_capture_saves` 扫描回复的 save 块并写盘——**完全对齐既有 `_capture_plan`「解析回复→写 notes/plan.md」套路**。
- 纯函数 `parse_save_blocks`(支持 path=/裸/引号/Windows 反斜杠/多块)+ `apply_save_block` 护栏
  (status: saved/refused-raw/skipped-exists/error)。守铁律:**绝不写 data/raw**、覆盖前 `_ask_yn` 确认、
  非 TTY 不静默 clobber、写完回报路径。
- `tests/test_repl_save.py` 9 例;全量 **1102 passed**;end-to-end:含 ```save 块回复 → 自动写 method.txt。
- 用户体验:以后在 REPL 直接说"存到 method.txt"即可,无需任何命令。

## 本轮(17):来源路由树 + 带引用的轻 KG ——feat-022 / feat-023 done

用户选了 deep-research 型设计里两块真正新增的高杠杆件(其余记忆/流式基本已有),守 stdlib-only。

**feat-022 来源路由树** `psyclaw/search_router.py`:据任务类型路由检索——factual→学术+精确、
conceptual→学术+语义(默认)、trend→学术+时间序列(年份窗口)、local→会话 FTS。决策树选**主通道**
但**永远带兜底**(主空即走兜底),规避单一模式误路由打空。复用 litsearch(学术)+ ContextArchive.search
(本地 FTS,feat-013)。`classify_task`/`route` 纯确定性可单测;`execute_route` 薄分发。
`psyclaw search <query> [--type]`。web/MCP 源留作扩展点(core 不内置通用网页检索)。

**feat-023 带引用的轻 KG** `psyclaw/kg.py`:SQLite nodes/edges(无 Neo4j),**边由构造即带引用**——
`add_edge` 拒无 `source_ref` 边(反幻觉关系);`verify` **复用 feat-015 cite-check 的 `_canon_key`**
核对每条 citation 边来源是否真在检索语料,溯源不到=孤儿=疑似杜撰关系。`seed_from_evidence_map`
从既有 evidence_map(构念×文献)天然带引用种图;基础实体消歧(归一名+类型去重);ego 子图 mermaid。
`psyclaw kg seed|show <实体>|verify|stats`。

- 新增 CLI 分类『检索/知识图谱』(search/kg/lit);`names==catalogued` 通过。
- `tests/test_search_router.py` 10 + `tests/test_kg.py` 10;全量 **1093 passed**;
  CLI end-to-end:evidence_map 种 2 带引用边 → `kg show` 出 mermaid → `kg verify` 0 孤儿,
  加杜撰边 Ghost(2099) → 被 verify 抓成孤儿;`search '焦虑近年趋势'` → trend/temporal。

## 本轮(16):PDF 正文抽取(读本地论文)——feat-021 done

用户实测痛点:`psyclaw` 引用本地 `.pdf` 时读不了——旧代码把 PDF 当文本 `read_text`,塞给 LLM
的是**二进制乱码**(PDF 头尾 + zlib 压缩流),LLM 只能说"读不了"。

- 新增 `psyclaw/pdf_extract.py`:三级 best-effort——① 可选库 pypdf/pdfplumber(装了最好、
  正确处理字体编码,**非硬依赖**)② 纯 stdlib 兜底(`zlib` 解 FlateDecode + **手写扫描器**抽文本操作符,
  **平衡括号** + 反斜杠/八进制转义 + UTF-16BE)③ **质量门**(抽出不像正文=扫描件/加密/CID 字体 →
  诚实返回提示装 pypdf 或粘贴文本/OCR,**绝不注入乱码**)。
- 经 `context.smart_excerpt` 的 `.pdf` 分支接入 → `@file` 与自动路径检测两条路都覆盖(单点改)。
- 测试中抓修关键缺陷:字面量正则 `\((?:\\.|[^\\()])*\)` **不支持嵌套括号**(论文里 `(p < .05)` 这类
  常见)→ 外层文本被抽丢 → 改手写深度扫描器。
- `tests/test_pdf_extract.py` 8 例;全量 **1073 passed**;本机 pypdf+pdfplumber 均可用,用户实跑走高质量抽取。

## 本轮(15):auto-loop 感知阶段挂 skill 推荐 ——feat-020 done

用户:两候选(AcademicForge→MCP connector、期刊画像加字数/版块核对)**放弃**;把 skill 推荐挂进 auto-loop 感知阶段。

- `autoloop.py`:新增 `skill_hints(action, project_dir, skills, top_k)`——薄封装 feat-018 的
  `recommend_skills`(external_only,推荐失败 fail-safe 返回 [])。`_print_sense` 增 `project_dir` 参数,
  **一次性**预取 `list_skills` 池(避免每个待办各扫一遍 `.claude/skills`),每个**非 blocker** 待办下打印
  `↳ 相关技能包:…`。派发/验收逻辑不动——纯指路、零风险增量(auto-loop 派发的是仓内 workflow,
  推荐的 Agent Skill 是给宿主 Agent 读的 markdown,psyclaw 不执行)。
- `tests/test_autoloop.py` +3 例(类型匹配 / 无匹配·空池 / bundled-only 不推)共 36 例;全量 **1065 passed**;
  离线 end-to-end:seed `.claude/skills` + 数据表 → 感知阶段在 analysis-loop 待办下列出相关技能包。
- **feature_list.json feat-001…020 现全部 done**;TODO.md 候选区清掉两放弃项,只留 provenance 深化。

## 本轮(14):文档债清理 + 会话持久化 session store ——doc-debt + feat-013 done

用户三连:①长期文档债清理 ②feat-013 会话持久化 ③类似 resume/rename 命令。均落地。

**① 文档债清理**:`TODO.md` 原为约 397 行 pre-pivot 统计命令台账(P5–P25 + P5-E:regress/anova/
ttest/efa/mlm/ancova/logit/meta/bayes/survival… 及其单测),这些模块/命令已随统计外移(feat-001)
全删。重写为精简计划真源(重定位说明 + 已落地 harness 指向 feature_list.json + 未完成 feat-013 +
候选后续)。`DESIGN.md`(v0.1 历史设计稿)顶部加「重定位说明」横幅 + 给 §3.2 /stat、§4.1 ARS-Stat、
§5 r-mcp/pystat 三处「内置统计」加作废标注。commit `df146a4`(−374/+57)。

**②③ feat-013 会话持久化 + resume/rename**:关键发现——`recall.ContextArchive` 早已按 `session`
分轮存 SQLite(+关键词/向量召回),缺的是**会话元数据表 + FTS5 全文 + 生命周期命令**,故**扩展**而非重造:
- `recall.py`:加 `sessions(id/name/created/updated)` 表(旧库从 turns 回填)+ `_init_fts`
  FTS5 探测(unicode61;无 FTS5 回落 LIKE;回落期历史轮次惰性回填)+ `ensure/rename/list/
  session_turns/search(FTS5 MATCH bm25,回落 LIKE)/delete_session`;`record` 维护会话与 FTS。
- `repl.py`:`ReplSession(resume_id)` + `_resume_session`(把历史轮次载回 messages、续写到同一会话)
  + slash `/sessions //resume //rename //search` + COMMANDS/HELP_TEXT。
- `cli.py`:顶层 `psyclaw resume [id]`(进 REPL 续接,不给 id 续接最近一次)+
  `psyclaw session list|search|rename|delete`。
- 本机 sqlite 3.50.4 FTS5 可用。`tests/test_session_store.py` 11 例;全量 **1062 passed**;
  CLI end-to-end:seed 两会话 → list/search 焦虑(FTS5 命中)/rename 均正确。

## 本轮(13):skill 路由推荐 + 期刊画像层 ——feat-018 / feat-019 done

用户点了两项:①按研究类型给 AcademicForge 相关 skill 做推荐路由;②AJS 式期刊画像层,让 cite-check 引用风格、
provenance 数据可得性按期刊定制。均已落地。

**feat-018 skill 路由推荐**:`psyclaw/skills/recommend.py`——据研究类型(lit-review/meta/analysis/qualitative,
接受 `*-loop` 别名)用中英双语具体关键词打分,从发现到的第三方技能包挑最相关的。`psyclaw skills --for <type>`。
纯确定性、可单测;仍不执行 skill(执行属宿主 Agent)。end-to-end:`skills --for meta-loop` 命中 forge-meta。

**feat-019 期刊画像层**(AJS 思路):`psyclaw/psych/journals.json` 固化 5 本期刊(心理学报/心理科学/
Psych Science/JPSP/Psych Bulletin)的引用风格/摘要字数/版块/报告标准/数据可得性/退稿红线;`psyclaw journal [id]`
只读浏览(对齐 method/design)。**让前两处通用改进按期刊定制**:
- cite-check `--journal`:`detect_citation_format` 粗判 author-year/numeric,与期刊期望核对(**软提示**,
  孤儿引用仍是唯一硬判据)+ 退稿红线自查清单。end-to-end:`--journal psych-science` 检出 numeric≠author-year。
- provenance `--journal`:期刊 `data_availability=required`(如 Psych Science/JPSP/Psych Bulletin)时,
  溯源完整额外要求带数据指纹;无 → 不完整,补 `--data` → 完整。
- 验证:`tests/test_skill_recommend.py` 6 + `tests/test_journals.py` 13;全量 **1047 passed**。

**Claude Science 两处思路 + AJS 期刊定制 + AcademicForge 接入 至此闭环**。后续可选:把 skill 推荐挂进
auto-loop 感知阶段;把 AcademicForge 包成 MCP connector;期刊画像扩到更多刊 / 加字数与版块的稿件核对。

## 本轮(12):外部技能包发现 —— 接上 AcademicForge / AJS ——feat-017 done

`psyclaw/skills/loader.py` 本就「agentskills.io 兼容」但只扫内置 `psyclaw/skills/`。本轮让它同时发现
**标准安装根**下的第三方 Agent Skill——`.claude/skills`、`.opencode/skills`(项目级 + 用户级)+
环境变量 `PSYCLAW_SKILLS_PATH`。**AcademicForge**(`HughYau/AcademicForge`,curate 了 Claude Science
生态 ~140 科研 + 82 AI skills、78+ 数据库)、**AJS** 等 `bash install.sh` 落到这些根后,`psyclaw skills`
免安装即列出、供研究编排参考。

- `external_skill_roots(project_dir)` 收集存在的标准根;`list_skills(project_dir, include_external=True)`
  平铺 `<skill>/SKILL.md` 与一层学科嵌套 `<domain>/<skill>/SKILL.md` 都扫,按 name 去重(内置优先),
  每条标 `source`/`path`。`cmd_skills` 按来源分组呈现,空时给 AcademicForge 安装指引。
- **边界(诚实)**:PsyClaw 只**发现 + 呈现 + 路由指引**这些 Agent Skill(给宿主 Agent 读的 markdown);
  真正执行发生在 Claude Code 等宿主读取 SKILL.md 时,不由本体 Python 跑——写清在 loader docstring。
- 验证:`tests/test_skills_loader.py` 7 例;全量 **1028 passed**;CLI end-to-end:PSYCLAW_SKILLS_PATH 指向
  模拟 AcademicForge 安装 → `psyclaw skills` 分组列出 forge-genomics / forge-sci-writing。

## 本轮(11):复现溯源 `provenance`(代码+环境+说明+决策轨迹)——feat-016 done

Claude Science 两处思路的第二处落地。`analysis`/`meta` 把统计外移成可复现脚本,但脚本本身
**不记录产出它的环境与决策轨迹**——几个月后想复跑常缺 Python/库版本、数据指纹、当初为何这么分析。

- 新增 `psyclaw/provenance.py`(纯 stdlib,不 import/不跑任何统计库):`capture_environment`
  (Python+平台+统计库版本,经 `importlib.metadata` 读 dist 元数据,不触发计算)、`build_provenance`
  (四要素:确切代码+sha256 / 环境 / 自然语言说明(缺省从 docstring 派生)/ 决策轨迹指针)、
  `write_provenance`(落 `<产物>.provenance.json` + `.provenance.md`)。
- **data 边界**:数据指纹只对 data/clean+根按需**单向**哈希(不入库内容);受保护的 `data/raw`
  一律只记路径不哈希;也可由调用方直接传入已算好的指纹。
- 门禁:`gates/checker.py` 注册 `provenance_complete` + `KIND_TRIGGERS['provenance']`;
  `rules.yaml` 新增 `REPRO.provenance`(trigger `provenance_check`,block)——完整=代码+环境+说明齐
  (决策轨迹尽力采集、不作硬判据,故 block 安全:三要素对生成脚本恒可得)。
- CLI:`psyclaw provenance <产物> [--desc --data --fingerprint]`;catalog 归「记忆/消息/IO」。
- 验证:`tests/test_provenance.py` 11 例;全量 **1021 passed**;`gates` 自检 `REPRO.provenance [block] 校验:自动`;
  CLI end-to-end:outputs/analysis.py → 采集 sha256+Python 3.14.2+平台+docstring 说明+notes/plan.md 轨迹
  + data/clean/scores.csv 指纹 → 溯源完整 rc=0。
- **两处改进(通用版)至此齐活**。下一步(用户选定顺序):叠加 AJS 式**期刊画像层**
  (`brycewang-stanford/Awesome-Journal-Skills` 思路),让 cite-check 的引用风格判据、provenance 的
  data-availability 要求都按期刊(心理学报/心理科学/Psych Science/JPSP/Psych Bulletin…)定制。

## 本轮(10):引用保真核查 `cite-check`(反杜撰参考文献)——feat-015 done

调研 Anthropic **Claude Science**(2026-06-30 发布,workflow 而非新模型:协调 agent + 专家 sub-agent
+ 独立 reviewer 核查每条引用/计算 + 可复现 provenance)后,决定把其中两处思路引进 PsyClaw。
本轮先落**引用保真**(通用版;期刊画像层按用户选择留待后续叠加,参考 GitHub
`brycewang-stanford/Awesome-Journal-Skills` 的期刊定制思路)。

- 关键洞察:`synthesize_review` 早已**指示** LLM「只准引用真实检索命中的键」,却**从无任何环节核验它照做**——
  这正是 AI 写作最常见的学术不端漏洞。本轮补上这道独立验收(实现与验收分离:允许键由真实检索确定、稿件由 LLM 生成)。
- 新增 `psyclaw/psych/citations.py`(纯函数,可单测):`extract_intext_citations`(叙述式+夹注式,
  连接词只认 `&`/`and`——刻意不认逗号以免把句内转折词误并入作者段)、`audit_citations`
  (比对粒度=(首位作者姓氏,4 位年份))、`load_allowed`(读 evidence_map.json 回落 lit_search.json)、
  `run_citation_audit`(落 `notes/citation_audit.json` sidecar + 人读报告;核验前截除参考文献区,其本身即语料)。
- 门禁:`gates/checker.py` 注册 `no_fabricated_citations` + `KIND_TRIGGERS['citation']`;
  `rules.yaml` 新增 `WRITE.citations`(trigger `citation_check`,block)——只对**检出的**孤儿引用 fail-closed,
  无语料/无引用时置 `manual_review` 显式转人工核(不过度拦)。填上了此前 `WRITE.apa7` 里 `apa7_citations`「需人工核」的空缺。
- CLI:`psyclaw cite-check <稿件.md>`(检出孤儿 rc=1);catalog 归「研究前规划/预注册」,`names==catalogued` 校验通过。
- 验证:`tests/test_citations.py` 19 例;全量 **1010 passed**;`gates` 自检 `WRITE.citations [block] 校验:自动`;
  CLI end-to-end:允许键 Smith et al.(2020) + 稿件含 Ghost et al.(2099) → 检出孤儿 1 条、rc=1。
- 测试中修正 2 处真实缺陷:叙述式逗号连接词误并转折词;无语料时误把全部引用当孤儿。
- **待续**:改进①**provenance bundle**(给生成脚本/图打包 代码+环境+说明+决策历史,强化复现门禁)下一轮做;
  之后再叠加 AJS 式**期刊画像层**让两处改进按期刊定制。

## 本轮(9):自主科研回路 `auto-loop`(Ralph 式自循环)——feat-014 done

用户要的「自循环系统」:自动发现需求→分发任务→检查成果→记状态→决定下一步。落在
`<type>-loop` 之上的**自驱动元回路**,一个命令贯通分层心智(Prompt/Context/Harness/Loop):

- 新增 `psyclaw/autoloop.py`(控制流全确定性纯函数,LLM 只在被派发流程内部):
  ① **感知** `discover_backlog` —— 每轮从仓库状态重新推导待办(模型会忘,仓库不会):
     有目标→lit-loop、效应量表→meta-loop、数据表→analysis-loop、转录稿→qual-loop;
     `classify_csv` 只读表头分效应量/数据表;已完成/标志产物已在 → 幂等剔除收敛。
  ② **派发** `_dispatch` —— 路由到对应 workflow(实现 sub-agent);任务级批准后跑到底。
  ③ **独立验收** `verify_result` —— 只读落盘 `workflow_summary.json`+标志产物,**与执行解耦**
     (一个干、一个验:不信返回码,只信仓库里真实存在的东西)。
  ④ **记状态** `notes/autoloop_state.json`(外部记忆;压缩/重启可续)。
  ⑤ **决定** `decide` —— stop:backlog 空 / 门禁 blocker(写 decision_request)/ 迭代上限;
     验收不过→标记跳过+写 `notes/blocked.md` **换下一个任务**,不在坑里空转重试。
- fail-closed:澄清未完=硬 blocker;只读 data/clean+根目录,**不碰受保护的 data/raw**。
- CLI `auto-loop`(--max-iters / --auto);进 CORE_COMMANDS/COMMAND_CATEGORIES/guide。
- 验证:`tests/test_autoloop.py` 33 例;全量 **991 passed**;离线 mock end-to-end 实跑:
  scores.csv → 发现 analysis-loop → 派发 → 独立验收通过 → 记状态 → 次轮收敛停止,exit 0。
- **代码评审两轮收敛**(4 视角并行发现 + 对修复的对抗复审):修复 5 处真实问题——
  ① `classify_csv` 收紧研究标签/方差列名集(`id,d,v` 不再误判成效应量表 → 避免数据表漏掉
     analysis-loop);② `_dispatch` 不把派生标签固化成 goal.md(否则下一轮误触发 lit-loop,
     已 end-to-end 验证 goal-restore);③ `_clarify_card` 异常 fail-closed(硬门禁宁拦不放);
     ④ 派发/验收异常不炸整个回路(记跳过、换下一个任务);⑤ `max_iters` 优先于 blocker,
     撞上限不误写 decision_request。对抗复审确认 5 处修复均正确、无回归。

## What's Done

- [x] feat-029 **v0.2 发布**:--help 收敛(全可调)· 用户别名 aliases.yaml · skills --sync 纳入 · 0.2.0 + CHANGELOG
- [x] feat-028 **插件系统 + 统一 scope**:`.psyclaw/plugins` register(api);skill/MCP/plugins 标 内置/用户·项目/全局
- [x] feat-027 **REPL 交互升级**:键盘选择器(choices 块)· 文件读取 open/safe(`/safemode`)· 会话名进提示符
- [x] feat-026 **易用性收敛套件**:status 一屏态势 · 本地目录感知 · 门禁 --skip-gates(留痕+探索性)· check 一键质检 · guide 决策树
- [x] feat-025 **纯工具层循环 agent**:模型自主多步调工具(provider 无关文本约定;副作用需批准);`toolloop.py` + `/agent` + `psyclaw agent`
- [x] feat-024 **「天然」保存文件**:REPL 直接说"存到 X"即落盘(提示约定+自动写,护栏守 data/raw);`repl.py`
- [x] feat-023 **带引用的轻量 KG**:SQLite nodes/edges,边必带来源,verify 复用 cite-check;`kg.py` + `psyclaw kg`
- [x] feat-022 **来源路由树**:按任务类型路由检索(主通道+兜底);`search_router.py` + `psyclaw search`
- [x] feat-021 **PDF 正文抽取**:读本地论文 PDF(pypdf/pdfplumber 优先,stdlib zlib 兜底,质量门);`pdf_extract.py` + `smart_excerpt`
- [x] feat-020 **auto-loop 感知阶段挂 skill 推荐**:发现待办时顺带列相关外部技能包;`autoloop.py` `skill_hints` + `_print_sense`
- [x] feat-013 **会话持久化 session store**(SQLite+FTS5)+ resume/rename:`recall.py` 扩展 + REPL slash + `psyclaw session/resume`
- [x] feat-019 **期刊画像层**(AJS 思路):`journals.json` 5 刊 + `journal` 命令;cite-check/provenance `--journal` 定制
- [x] feat-018 **skill 路由推荐**:按研究类型推荐外部技能包;`psyclaw/skills/recommend.py` + `skills --for`
- [x] feat-017 **外部技能包发现**(接上 AcademicForge/AJS):skills 加载器扫 .claude/skills 等标准根;`psyclaw/skills/loader.py`
- [x] feat-016 **复现溯源 provenance**:给生成脚本/图打包 代码+环境+说明+决策轨迹;`psyclaw/provenance.py` + `REPRO.provenance` 门禁
- [x] feat-015 **引用保真核查 cite-check**(反杜撰):文内引用逐条溯源到检索命中;`psyclaw/psych/citations.py` + `WRITE.citations` 门禁
- [x] feat-014 **自主科研回路 auto-loop**(Ralph 式):感知→派发→独立验收→记状态→决定;`psyclaw/autoloop.py`
- [x] feat-001 **统计层整体外移**:git rm 42 个统计模块 + 41 个测试;cli/loop/pipeline/repl/scales/preregister 去统计纠缠;psyclaw/ 零统计库依赖
- [x] feat-002 研究编排流水线 research(澄清→文献→设计→写作→评审→总验收;--freeform 走通用回路)
- [x] feat-003 审稿模拟 review panel
- [x] feat-004 研究澄清 clarify(LLM 驱动追问)
- [x] feat-005 预注册 preregister + 分析声明 declare-test
- [x] feat-006 知识参考目录(scale/norms/assume/method/design/cite/ethics)+ 量表计分 score
- [x] feat-007 文献检索 lit + 写作输出 export(APA7/心理学报/JARS)
- [x] feat-008 三层自进化记忆
- [x] feat-009 学术规范门禁 gates
- [x] feat-010 REPL + 路径注入 + 渐进式披露
- [x] feat-011 harness 工程化契约

## What's Next

1. 后续增强:各分析步从"生成脚本"升级为可选直连 MCP 统计后端;质性编码升级为专用 skill
2. 文档去债收尾:DESIGN.md / TODO.md 仍大量描述已删的统计命令,待重写(README 已重写✅)
3. feat-013 会话持久化 session store(SQLite+FTS5)

## 本轮(8):`psyclaw setup` 升级为项目脚手架 + 能力选装向导

- 新增 `psyclaw/scaffold.py`(确定性、幂等、可单测):
  ① 标准目录结构(notes/outputs/data/{raw,clean}/logs/figures/scripts)
  ② 据澄清卡生成 `notes/project_overview.md`(按 A–F 类别组织已澄清内容)
  ③ 项目记忆 `notes/project_memory.md`(据澄清卡播种目标+方法学决策,幂等不覆盖手写)
- `cmd_setup` 编排五阶段:①目录 ②clarify→概览 ③项目记忆 ④能力依赖(`--online` 联网装/交互询问/仅显矩阵)⑤列 MCP 服务器+skill 目录
- `guide` 上手步骤纳入 setup(clarify→setup→loop);`tests/test_scaffold.py` 8 例;全量 **958 passed**

## 本轮(7):暴露全部顶层命令 + 新增 `guide` 首次上手介绍

- 去掉渐进式披露的隐藏:`psyclaw --help` 现暴露**全部 39 个顶层命令**(不再藏一半);
  `CORE_COMMANDS` 仅保留作 `guide`/`commands` 的 ★ 常用标注。
- 新增 `psyclaw guide`:首次使用上手介绍——是什么(研究编排 harness,统计外移)+
  心智模型(每类研究一条 loop)+ 60 秒上手 + 常用单功能;`--help` epilog 指向 guide。
- tests/test_cli_help.py 改测(全部暴露 + guide 注册);全量 950 passed。

## 本轮(6):命令命名重构 — `loop` 通用编排器 + `<type>-loop`

- 命名约定:每个流程都是一个 "loop"。`loop [主题]` = 通用流程编排回路(类 Claude Code 的
  agentic loop = run_loop:planner→执行→critic→修复),不绑研究类型。
- 四条研究流程改名:review-lit→**lit-loop**、meta→**meta-loop**、analysis→**analysis-loop**、
  qualitative→**qual-loop**(走 workflow 引擎;registry command 字段 + CLI 注册同步)。
- `research` 保留(不分类型固定全流程)。CORE_COMMANDS/COMMAND_CATEGORIES 同步;
  tests/docs(ARCHITECTURE/COMMANDS)同步。全量 **949 passed**。

## 本轮(5):qualitative 质性研究流程 — 四条研究流程齐

- `qualitative <转录稿>`:clarify门禁→载入转录稿→质性设计→主题分析(LLM 辅助)→写 COREQ 报告→评审
- 质性是解释性分析(非统计):L3 实现 = LLM 辅助开放编码+主题分析,**研究者须复核**(HITL);
  产物明确标注"LLM 辅助,逐条复核引文与主题归属"
- 新子功能 `load_transcripts`(单文件/目录,过滤非 .txt/.md,fail-closed);生成式 `step_qual_design`/`step_thematic_analysis`/`step_write_qual`
- 验证:`tests/test_workflows.py` 35 例;全量 **949 passed**
- **四条研究流程齐(feat-012 done)**:review-lit / meta / analysis / qualitative,每类一条顶层命令

## 本轮(4):analysis 实证分析流程(第三条流程,统计外移到 pingouin/scipy)

- `analysis <data.csv>`:clarify门禁→画像数据→研究/分析设计→**推荐分析+生成可复现脚本**→写→评审
- 统计外移:`generate_analysis_script` 据数据画像推荐分析(t检验/ANOVA/相关/回归/描述统计)
  并生成委托 pingouin/scipy 的脚本(outputs/analysis.py,含效应量+CI+前提诊断),仓内不算
- 新子功能(独立纯函数):`profile_data`(逐列判数值/分类+水平)、`recommend_analysis`
  (确定性选检验)、`generate_analysis_script`;生成式 `step_design`(LLM 写设计备忘)
- 验证:t检验/ANOVA/相关三种推荐的生成脚本均经 C:\Python314 实跑 exit 0;
  `tests/test_workflows.py` 28 例;全量 **942 passed**
- 三条研究流程齐:review-lit / meta / analysis(命名按用户要求 empirical→analysis)

## 本轮(3):meta 元分析流程(验证"统计外移"端到端)

- `meta <effects.csv>`:clarify门禁→载入校验效应量表→**生成可复现元分析脚本**→写→评审
- 统计外移落地:`generate_meta_script` 产出委托 statsmodels 的脚本(随机效应 DL + I²/τ²/Q + Egger),
  仓内**不算任何统计**;脚本由用户在 [stats] 环境跑或交 MCP
- 新子功能:`validate_effects`(效应量表校验,自动识别 effect 列 + variance/se/ci 方差来源)、
  `generate_meta_script`——均独立纯函数可单用
- 引擎加 `seed` 参数(把 effects_csv 喂进 ctx.data);`step_review` 泛化用 ctx.data['draft_path']
- 验证:生成脚本经 C:\Python314 实跑 → 合并效应 0.347 / I² 27% / Egger p=.008 / exit 0;
  `tests/test_workflows.py` 20 例;全量 **934 passed**

## 本轮(2):Workflow 层 — 按研究类型路由的可组合流程引擎

愿景:不同研究需求走不同流程(文献综述/实证/元分析/质性…),上层分类简单,
每个子功能可单用/可拆/可拼成 loop;harness 约束 + skill/MCP 实现 + memory 横切。

- 架构:四层(L0 路由→L1 流程→L2 子功能→L3 skill/MCP)+ 两横切(harness/memory),见 `docs/ARCHITECTURE.md`
- 引擎 `psyclaw/workflows/engine.py`:声明式 Step 列表 + gate(fail-closed)+ HITL + 机器可读总验收
- 首条流程 **文献综述**(`review-lit <主题>`):clarify→检索→PRISMA筛选→合成综述→评审;复用 litsearch/synthesize/review
- 新子功能 `screen_papers`(PRISMA 相关性初筛,独立纯函数,可单用;跨语言诚实降级)
- L0 路由形态:**每类研究一条顶层命令**(review-lit 已落地,empirical/meta/qualitative 待续)
- 验证:`tests/test_workflows.py` 12 例;全量 **926 passed**

## 本轮(2026-06-26):统计层整体外移

**删除**(git rm,共 83 文件):
- 42 个统计模块:analyze/anova/anova2/ancova/rm_anova/mixed_anova/chisquare/nonparametric/
  paired_categorical/regression/hierarchical_regression/logistic/poisson/negbin/ordinal/
  multinomial/mlm/efa/cfa/invariance/survival/irr/roc/meta/decision_tree/equivalence/bayes/
  partial_corr/compare_corr/descriptives/diagnostics/careless/missing_data/sensitivity/
  effect_size/multiple_testing/power/reliability/stats_core/pingouin_backend/r_backend/ttest
- 41 个对应测试 test_*.py

**保留 harness**(psych/ 12 模块):clarify, knowledge, scales, ethics, institution,
lit_cli, litsearch, synthesize, zotero_client, analysis_plan, preregister, __init__

**纠缠修复**:
- `cli.py` 2166→~790 行:删 ~41 统计命令注册 + 处理器;CORE_COMMANDS/COMMAND_CATEGORIES 重写
- `loop.py`:删 `_auto_analyze`/`_find_csv`/`_guess_vars`(executor 不再自动跑统计)
- `pipeline.py`:删③统计阶段 + 统计门禁;PHASES 去 stat;流程变 文献→设计→写作→评审→总验收
- `repl.py`:删 /check //screen //sensitivity 斜杠命令
- `scales.py`:删 `compute_subscale_reliability`(信度外移)
- `preregister.py`:删 power.compute 嵌入(样本量依据走澄清卡 power 槽位)
- `pyproject.toml`:8 个统计库从硬依赖降为可选 `[stats]` extra

**保留命令**(33):repl/version/doctor/config/setup/skills/mcp/gates/commands ·
scale/norms/assume/method/design/cite/ethics · score · clarify/declare-test/preregister/jars ·
goal/plan/tasks/research/review · memory/serve/notify/lit/auth/export/figures

**验证**:`C:\Python314\python -m pytest -q` → **944 passed**(原 3165,删 ~2200 统计测试);
`psyclaw --help`/`commands`/`gates` 实跑正常;整包 compileall 通过;psyclaw/ 零统计库 import。

## Blockers / Risks

- [ ] 文档去债:DESIGN.md / TODO.md / README.md 仍描述已删统计命令,需重写(本轮只更新了 CLAUDE.md / feature_list.json / docs/COMMANDS.md / 审计文档)
- [ ] gates 仍含统计类门禁(STAT.meta/equivalence、MEASURE.invariance 等)——统计外移后这些门禁无内置产出可校验,但作为规范规则保留(门禁只增不删)

## Notes for Next Session

本地测试解释器:`C:\Python314\python`。PsyClaw 现为纯研究编排 harness,
**不要再往 psyclaw 里加任何统计计算**——统计交给外部成熟库/MCP(见 CLAUDE.md 铁律)。
