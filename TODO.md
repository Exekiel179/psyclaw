# PsyClaw 代办 / Roadmap（计划真源）

> **状态约定**：✅ 已落地 · 🚧 进行中 · 📋 已设计待实现 · ❓ 开放问题
> **真源分工**：机器可读状态真源 = `feature_list.json`；人读快照 = `progress.md`;
> 交接 = `session-handoff.md`;本文件 = **计划真源**(只列现状与未完成/候选工作)。
> 最后整理：2026-07-03

---

## 0. 重大转向(2026-06)——本文件已按此重写

PsyClaw 从「全流程**统计** CLI」重定位为「纯研究**编排** harness」:
**统计计算整体外移到成熟库/MCP(scipy/pingouin/statsmodels/lifelines…),本仓不内置、不 import
任何统计库,也不重实现任何统计算法**(feat-001 删除约 42 个手写统计模块 + 对应命令/测试)。
psyclaw 只保留:研究编排(流程/回路)、知识参考、文献/写作、澄清/预注册、研究质量检查。

> ⚠️ **历史说明**:本文件早期版本(2026-06-14 前)记录过一整套内置统计命令
> (`psyclaw anova/ttest/regress/efa/mlm/ancova/logit/meta/bayes/survival…`,即旧 P5–P25 台账)。
> 这些模块与命令**已随统计外移全部删除**,不再是计划的一部分;完整历史见 git 提交记录。
> 需要统计时:meta/analysis 流程**生成**委托外部库的可复现脚本(交 `[stats]` 环境或 MCP 跑),
> 或直接用 SPSS/MNE/Mplus/Stata 等 MCP 服务器。

---

## 1. 已落地(post-pivot harness) —— 详见 `feature_list.json`

| 区块 | 覆盖 |
|---|---|
| 统计外移 | feat-001:删 42 统计模块 + 41 测试;`psyclaw/` 零统计库依赖;`[stats]` 降为可选 extra |
| 研究流程 | feat-002 research 流水线 · feat-012 Workflow 引擎(lit-review/meta/analysis/qualitative 四流程)· feat-014 **auto-loop** 自主科研元回路 |
| 评审 / 澄清 / 预注册 | feat-003 审稿模拟 · feat-004 clarify(LLM 驱动 17 个研究准备项)· feat-005 preregister + declare-test |
| 知识 / 量表 | feat-006 知识目录 + 量表计分 · feat-019 **期刊画像层**(journal) |
| 文献 / 写作 / 质量检查 | feat-007 lit + export(APA7/心理学报/心理科学)+ JARS · feat-009 研究质量检查 gates |
| 学术诚信增强 | feat-015 **cite-check** 引用保真(反杜撰)· feat-016 **provenance** 复现溯源 |
| 会话 / 记忆 / 交互 | feat-008 三层记忆 · feat-010 REPL+路径注入+MD 渲染 · feat-011 harness 契约 · feat-013 **会话持久化**(SQLite+FTS5)+ resume/rename |
| 生态 / 技能 | feat-017 外部技能包发现(接 AcademicForge/AJS)· feat-018 skill 路由推荐 · feat-020 **感知阶段挂 skill 推荐**(auto-loop 发现待办时顺带列相关技能包) |

---

## 2. 未完成 / 进行中

**用户实测反馈立案(2026-07-13,v0.13.0 评估中发现,未排期实现)**:

- ⬜ feat-090 候选:chat 生成中可中断——LLM 流式请求阻塞期监听按键,ESC/Ctrl+C 能
  取消当前轮(现状:Ctrl+C 仅在输入态两处捕获 repl.py:832/1655,生成中无响应);
  裸 `quit`/`exit`(不带斜杠)也应识别为退出词(现只认 /exit /quit /q)。
- ⬜ feat-091 候选:审批模式可见性——YOLO/逐条确认当前模式在 banner 或 status 行
  常显(现状 repl.py:653 yolo 生效但界面零提示,用户不知道自己处于哪种审批模式)。
- ⬜ feat-092 候选:chat 层统计外移失守——对抗评估实测,用户说「别调外部库,手写
  Welch t 检验」,chat 直接手写了含 erf 近似 p 值的完整实现(还自认精度有问题)。
  system prompt 应把「统计路由外部库/MCP」写成硬约束,识别到统计实现请求时改走
  run-stats 路由并解释原因。
- ⬜ feat-093 候选:反杜撰不彻底——chat 拒绝了用户点名编造的 Smith & Johnson
  (2024),却凭记忆主动供出多条带卷期页码的"替代文献"(仅一条标了「检查是否存在」)。
  凭记忆给出的文献条目应一律标注未核实/建议检索,或直接走 lit 检索。
- ✅ feat-094 meta 行清洗单一真源(_row_yv,负 se/倒置 CI 换算前拒绝)+ 生成脚本
  内嵌同口径清洗(剔除逐行打印·可用<2 fail-closed·k<3 不算 Egger)+
  step_load_effects/step_write_meta 的 dropped 呈报(psyclaw/workflows/steps_meta.py)。
- ⬜ feat-095 候选:meta 写作步角色混乱——report.md 产出的是模型执行独白
  (「我将先列出目录结构…现在开始执行」+ 一段另写的带错脚本),不是稿件骨架;
  写作 prompt 需约束产出形态(引用 outputs/meta_analysis.py 结果占位)。
- ✅ feat-096 check/jars 判据升级:效应量/CI 升阻断级(识别裸 d/g/r=),
  integrity_flags 诚信启发式(因果×横断面 block·亚组 HARKing block·事后剔除
  邻近窗口 warn·边缘显著话术 warn·否定校正剥除),run_jars_check 关键字
  TypeError 修复(psyclaw/output/jars.py·writing_backend.py·checkup.py)。
- ✅ feat-097 cite-check 零语料一致性:extract_reference_entries + consistency_check
  双向比对(文内不在文献表=硬判据入 no_fabricated_citations;未被引用=软警告),
  CLI/checkup/报告三处呈现(psyclaw/psych/citations.py·cli.py·checkup.py)。

其余当前**无未完成 feature**——feat-001…076 全部 `done`。**v0.12.0 已发布**,feat-076
(chat / run / auto 心智模型收敛)已完成但尚未发布;详见 `CHANGELOG.md` 的 Unreleased。
上一版 **v0.10.0(2026-07-07)**=数据→结果端到端闭环(analysis 流程直接经 pystat MCP 出结果):

- ✅ feat-053 workflow 分析步接 pystat MCP(pystat_bridge 映射+跑;step_analysis 落 result.txt)。
- ✅ feat-054 v0.10.0 发布收尾(版本 + CHANGELOG + ARCHITECTURE)。
- ✅ feat-055 REPL `/dump` 导出对话(当前对话;`--full` 连同隐藏上下文 system/memo/约定片段;
  纯渲染在 `psyclaw/transcript.py`;拒写 data/raw;+13 测试)。
- ✅ feat-056 REPL 审批模式修三坑:`/yolo` 自动放行非危险副作用(危险命令仍问,data/raw 硬拒);
  确认框不再与命令回显串行(`_side_effect_ok` 单独打内容 + `safe_prompt` 包裹 ANSI);
  自动跟进深度 3→12(YOLO 40),多步分析不再停等「继续」;+11 测试。
- ✅ feat-057 流式路径 no-progress 检测:命令/读取跟进靠「连续重复相同请求即停」判停
  (`_followup_signature`+`_noprogress_stop`),深度上限降级为高位安全兜底(100,config 可调);
  审计确认同类问题无残留(有色 input 仅 `_ask_yn` 已修;autoloop backlog 单调收缩不重复);+5 测试。
- ✅ feat-058 错误学习:命令失败经 `distill_env_lessons` 蒸馏环境教训(命令不存在/模块未装/
  API 改名),记入本会话记忆每轮注入止损 + 落 memory 待确认卡(跨会话,HITL 确认);+14 测试。
- ✅ feat-059 环境教训卡自动失效:卡带 kind,`memory.archive_lesson` 落实「被推翻则归档」,
  `probe_env_card_stale` 再验证(cmd 用 which 秒回;module/attr 用 python3 真跑),启动轻量验证
  + `/memory verify` 全量;只在确证已恢复时失效(防误删),归档同步清会话记忆;+13 测试。
- ✅ feat-060 选择器非编号输入不吞掉:`pick_interactive` 返 (选中项, 自由文本),打 `y` 之类
  非编号输入当自由作答经 `format_free_answer` 转发给模型继续,不再「未选择」死胡同;+5 测试。
- ✅ feat-061 终端内联渲染图片:`psyclaw/imgview.py` 纯 stdlib(iTerm2/kitty 协议,只 base64 字节),
  `/img` 手动 + 命令出图自动渲染;env 探测(Warp/iTerm2/WezTerm/VSCode/kitty),config 可强制;+15 测试。
- ✅ feat-062 v0.11.0 发布收尾(版本 0.10→0.11 + CHANGELOG v0.11 + COMMANDS REPL 命令表 + progress/handoff)。
- ✅ feat-063 no-progress 只管自主回合:`_round_is_autonomous` 判定,用户逐条确认(打 y)不再被
  误判「原地打转」掐断;高位深度兜底始终生效;+6 测试。
- ✅ feat-064 确认支持「全部同意」:非危险副作用三态 `[Y/n/a]`,`a`=本会话该类不再逐条问
  (`_auto_approve_labels` 按 label 分类);危险永远逐条问不给 all;+5 测试。
- ✅ feat-065 错误自学习+图片渲染接入 agent 模式:toolloop 失败工具结果蒸馏教训当轮回灌
  +返回 lessons(只看 ok=False,防把读到的日志当本机事实);REPL/CLI 落卡+内联渲染
  (`render_images_in_text` 共用);+11 测试。
- ✅ feat-066 教训卡正向加固:同卡再现 → active 强度+1(记 reinforced_ts)/pending hits+1;
  注入按强度降序、CLI 显示再现次数;兑现文档「被再次印证则强度+1」;+5 测试。
- ✅ feat-067 确认提示措辞重设计(用户反馈):`[Y/n/a=…]` 改逐项自解释
  `[回车=同意 / n=拒绝 / a=同意且本会话此类不再问]`,行为不变。
- ✅ feat-068 选择器改原地内联(用户反馈):弃 prompt_toolkit 全屏蓝色对话框,
  `_pick_inline` ↑↓/数字/空格/回车/Esc/打字作答,ANSI 原地重画不清屏;+10 测试。
- ✅ feat-069 @图片 引用内联渲染:@path 是图片时终端内联显示,上下文只注入元信息
  (修掉此前 smart_excerpt 把二进制乱码灌进上下文);+3 测试。
- ✅ feat-070 shell「全部同意」按命令前缀限定(用户反馈):`cmd_approval_scope`
  git status ≠ git push,复合命令不泛化;危险红线不变;+7 测试。
- ✅ feat-071 选择器看得见方案详情(用户反馈):宽度感知截断 + 高亮项 2 行详情区,
  `_CHOICES_SYSTEM` 约定选项自包含;+2 测试。
- ✅ feat-072 v0.10 遗留收尾:`pystat_meta` 工具(DL 随机效应+Egger)· meta 流程直跑
  落 meta_result.txt · 写作步注入 pystat 真结果 · `_real_result` 守卫(脚本骨架≠结果)·
  [stats] 数值实测(statsmodels+pingouin 真跑,生成脚本端到端验证);+11 测试。
- ✅ feat-073 eval harness:`psyclaw/evalharness.py` 确定性离线评测(6 用例 28 检查:
  分析/元分析编排、文献初筛诚实降级、质量检查 fail-closed、错误自学习、toolloop 纪律),
  CLI `psyclaw eval [--case --json]` 落 `.psyclaw/eval_report.json`;+10 测试。
- ✅ feat-074 provenance 深化:`build_replication_declaration` 生成 replication-package
  声明(脚本 sha256+数据指纹+环境,可直接放进稿件);新质量检查 `REPRO.replication_package`
  只对 data_availability=required 期刊强制,非强制/旧 sidecar 放行;+8 测试。
- ✅ feat-075 v0.12.0 发布收尾(版本 0.11.0→0.12.0 + CHANGELOG v0.12 + COMMANDS 46 条
  + progress/handoff)。全量 1460 passed · gates 22 条 ✓ · eval 28/28。
- ✅ feat-076 交互心智模型收敛:`chat / run / auto` 三入口 + `psyclaw/modes.py` 共享路由;
  REPL `/run /auto /approval /access`;旧 agent/loop/*-loop/auto-loop 与旧 slash 开关兼容;
  首屏/状态/README/TUTORIAL/COMMANDS/ARCHITECTURE/内置 skill 全部同步;+18 测试。
- ✅ feat-079 真结果守卫结构化(v0.12 评审修复):`MCPClient.call_tool_status` 返回
  {ok,text},`_real_result` 拒 ok=False/骨架哨兵(`SKELETON_MARK` 单一来源)/
  {"error"} 载荷/NaN·inf 数值;`extract_meta_rows` 纯函数行过滤(坏单元剔除呈报,
  k 以可用行计),pystat_meta k<3 不算 Egger、数值异常结构化报错;+16 测试。
- ✅ feat-080 选择器 POSIX 方向键修复(v0.12 评审修复):`_get_key` 改 fd 级 os.read
  (缓冲读吞 \x1b[A 后两字节致 ↑↓ 被判 ESC 取消整题+泄漏假按键),TCSADRAIN 保
  type-ahead,UTF-8 多字节读满,EOF 不忙等;单选空格=选定;pty 真读取器测试补盲区;+10 测试。
- ✅ feat-081 批准范围加固(v0.12 评审修复):解释器 flag(-c/-m/-e)/uv run/包装程序
  (sudo/env/npx…)/环境变量前缀 一律不泛化;.exe 剥后缀恢复子命令区分(git.exe
  status ≠ push);复合命令整条原文不截断(修 80 字前缀碰撞);+9 测试。
- ✅ feat-082 期刊名不识别绝不静默(v0.12 评审修复):journal_unmatched 记 sidecar,
  md/CLI 醒目告警「期刊定制未生效」+ 退出码 1 + 列可用 id;判据口径不动;+4 测试。
- ✅ feat-083 确认教训卡继承再现证据(v0.12 评审修复):confirm 时 strength=max(1,hits),
  再现 5 次的教训不再被归 1 排到偶发教训后面;+3 测试。
- ✅ feat-084 eval 输出健壮性(v0.12 评审修复):_print_encoding_safe(GBK 管道
  emoji 降级不崩)、报告先落盘再打印、--json 落盘失败提示走 stderr、
  重复 --case 去重(合计=分项);+4 测试。
- ✅ feat-085 选择器 CJK 显示宽度几何(v0.12 评审修复):_draw 改用 ui 的 CJK 感知
  截断/折行,中文选项不再物理换行破坏原地重画;选项内嵌 \n 解析源头单行化;
  ui._ANSI_RE 扩到全部 CSI;+3 测试。
- ✅ feat-086 图片渲染路径修正(v0.12 评审修复):render_image_file 直渲已知路径
  (含括号/盘符文件名不再误报「终端不支持」);supports_inline isatty 先于 force
  (强制协议不再往管道灌 base64);+5 测试。
- ✅ feat-087 教训落卡诚实计数(v0.12 评审修复):memory.draft_lessons 批量落卡
  单卡失败不中断、返实际数;cmd_agent 按 saved/total 三态如实报;REPL/CLI 语义收敛;+3 测试。
- ✅ feat-088 toolloop 教训抗修剪(v0.12 评审修复):每轮全量重放累计教训进最新
  反馈,trim 压掉旧副本后上下文恒有完整教训(约 3 份活副本),长任务不再失忆重踩;+2 测试。
  —— 至此 v0.12 code-review 15 项确认缺陷全部修复完毕(feat-079~088)。
- ✅ feat-089 v0.13.0 发布收尾(版本 0.12.0→0.13.0 + CHANGELOG v0.13 定版
  【交互三入口收敛 + 评审修复清零】+ progress/handoff)。全量 1553 passed。

### v0.9(2026-07-07 已发布)

当前**无未完成 feature**——feat-001…052 全部 `done`。**v0.9.0 已发布(2026-07-07)**,
主题=一键配置基础环境,详见 `CHANGELOG.md`:

- ✅ feat-051 `setup --env` 一键环境配置(诊断 provider/key + stats/full,--online 实装)。
- ✅ feat-052 v0.9.0 发布收尾(版本 + CHANGELOG + COMMANDS)。

### v0.8(2026-07-07 已发布)

当前**无未完成 feature**——feat-001…050 全部 `done`。**v0.8.0 已发布(2026-07-07)**,
主题=闭环「统计外移到 MCP」(agent 可直接调统计后端),详见 `CHANGELOG.md`:

- ✅ feat-049 pystat MCP 服务器(pingouin 委托,缺失降级脚本;6 工具经 feat-040 浮出 mcp__pystat__*)。
- ✅ feat-050 v0.8.0 发布收尾(版本 + CHANGELOG + docs)。

### v0.7(2026-07-07 已发布)

当前**无未完成 feature**——feat-001…048 全部 `done`。**v0.7.0 已发布(2026-07-07)**,
主题=REPL 交互体验(修用户报告的方向键 `^[[A`),详见 `CHANGELOG.md`:

- ✅ feat-047 REPL 方向键/历史/光标(readline 后端,非 ptk TTY 主路径)。
- ✅ feat-048 v0.7.0 发布收尾(版本 + CHANGELOG + TUTORIAL)。

### v0.6(2026-07-07 已发布)

当前**无未完成 feature**——feat-001…046 全部 `done`。**v0.6.0 已发布(2026-07-07)**,
主题=多轮对话 + 工具调用稳(审计工具循环、实测复现故障点后加固),详见 `CHANGELOG.md`:

- ✅ feat-043 参数规范化校验(args JSON 字符串解析/非对象报错引导;工具异常标 ok=False)。
- ✅ feat-044 无进展检测(重复相同调用/空回复→stopped=no_progress 收敛,不空转)。
- ✅ feat-045 消息序列不变量(sanitize_messages 防空 content/连续同角色/首条非 user→400)。
- ✅ feat-046 v0.6 发布 + 多轮集成测试(正常→畸形自纠→截断续写→未知工具→重发→答案)。

### v0.5(2026-07-07 已发布)

当前**无未完成 feature**——feat-001…042 全部 `done`。**v0.5.0 已发布(2026-07-07)**,
主题=编排纵深(agent 真正会用 MCP)+ 长会话蒸馏升级,详见 `CHANGELOG.md`:

- ✅ feat-039 MCP stdio 客户端(`psyclaw/mcp/client.py`,JSON-RPC over stdio,超时 fail-safe)。
- ✅ feat-040 agent 循环接入 MCP 工具(`psyclaw/mcp/agent_tools.py`,`mcp__` 前缀、fail-closed、
  客户端进程级复用;live 验证浮出真实 mne-mcp 4 工具)。
- ✅ feat-041 compact_history LLM 蒸馏(有 key 结构化蒸馏,无 key/异常回落规则蒸馏)。
- ✅ feat-042 v0.5.0 发布收尾:版本 0.5.0 + CHANGELOG v0.5 段 + docs(COMMANDS/ARCHITECTURE)。

### v0.4(2026-07-07 已完成)

继续深化「对话长期维持」:网络瞬断不该杀死一次 agent 长任务;跑过的 agent 任务要可回看。

- ✅ feat-036 provider 网络层健壮性:首字节前 429/5xx/网络异常指数退避重试 ≤3 次,
  HTTP 错误读 body 显性化,流开始后不重试(`psyclaw/providers/base.py`)。
- ✅ feat-037 agent 运行痕迹持久化:`.psyclaw/agent_runs.jsonl` + `psyclaw agent
  --history [n]`,CLI/REPL 双入口自动落痕(`psyclaw/toolloop.py` `cli.py` `repl.py`)。
- ✅ feat-038 v0.4 收尾:docs/COMMANDS+TUTORIAL 同步 v0.3/v0.4 用户可感知变化
  (shell 逐条确认/save_file 项目根/PSYCLAW_MAX_TOKENS/--history)+ harness 快照。
  全量 1222 passed。

### v0.3(2026-07-07 已发布)

**无未完成 feature**——feat-001…035 全部 `done`。**v0.3.0 已发布(2026-07-07)**,
主题=agent 执行面安全加固 + 长会话可靠性,详见 `CHANGELOG.md`:

- ✅ feat-031 shell 执行 fail-closed(外审 **HIGH**):shell 类命令每条须 confirm,
  _DANGEROUS_RE 降级为 ⚠ 标签(`psyclaw/repl.py`)。
- ✅ feat-032 save_file 路径允许清单(外审 **MEDIUM**):项目根内+拒软链/凭据路径
  (`psyclaw/toolloop.py` save_path_denied)。
- ✅ feat-033 长会话上下文修剪:toolloop 旧轮次工具结果滚动压缩(trim_convo);
  compact_history 审视结论=现有实现+测试已足。
- ✅ feat-034 normalize_type 补 22 个中文研究类型别名(`psyclaw/skills/recommend.py`)。
- ✅ feat-035 v0.3 发布收尾:版本统一 0.3.0(pyproject+__init__)+ CHANGELOG v0.3 段;
  全量 1212 passed。

- ✅ feat-030 toolloop 截断防护(2026-07-07):修「工具调用中途提前停止」——截断的 ```tool 块
  不再被误判为最终答案(has_truncated_tool_block + provider.last_stop_reason 续写),
  providers 捕获 stop_reason(PSYCLAW_MAX_TOKENS 可配),agent max_iters 6→24。
  实现:`psyclaw/toolloop.py` `psyclaw/providers/{base,anthropic_api,openai_compat}.py` `psyclaw/cli.py`。

---

## 3. 候选后续(未排期)

- ✅ ~~provenance 深化:由期刊画像的 `data_availability=required` 驱动强制 replication-package 声明~~
  (2026-07-11 已完成,见 feat-074)。

> **已放弃**(2026-07-03,用户决定):~~AcademicForge 包成 MCP connector~~(现有「发现 + 路由指引」已够,
> 不必让 psyclaw 执行 Agent Skill);~~期刊画像加字数/版块的稿件级核对~~(现只做引用风格 + 数据可得性,足够)。

---

## 4. 里程碑对照(历史 DESIGN §10)

| 里程碑 | 内容 | 状态 |
|--------|------|------|
| M0–M5 | 骨架 → REPL → (统计) → Gates → MCP → 全流水线 | ✅ 已达成后重定位(统计段外移) |
| 后续 | 编排纵深(auto-loop)· 学术诚信(cite-check/provenance)· 期刊定制 · 生态接入 · 会话持久化 | ✅ feat-012…020 全部 done |

> DESIGN.md 为 v0.1 历史设计稿,含内置统计的旧架构描述,顶部已加重定位说明;当前命令集见 `docs/COMMANDS.md`。
