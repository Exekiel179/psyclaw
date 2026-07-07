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
psyclaw 只保留:研究编排(流程/回路)、知识参考、文献/写作、澄清/预注册、学术规范门禁。

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
| 评审 / 澄清 / 预注册 | feat-003 审稿模拟 · feat-004 clarify(LLM 驱动 17 槽位)· feat-005 preregister + declare-test |
| 知识 / 量表 | feat-006 知识目录 + 量表计分 · feat-019 **期刊画像层**(journal) |
| 文献 / 写作 / 门禁 | feat-007 lit + export(APA7/心理学报/心理科学)+ JARS · feat-009 学术规范门禁 gates |
| 学术诚信增强 | feat-015 **cite-check** 引用保真(反杜撰)· feat-016 **provenance** 复现溯源 |
| 会话 / 记忆 / 交互 | feat-008 三层记忆 · feat-010 REPL+路径注入+MD 渲染 · feat-011 harness 契约 · feat-013 **会话持久化**(SQLite+FTS5)+ resume/rename |
| 生态 / 技能 | feat-017 外部技能包发现(接 AcademicForge/AJS)· feat-018 skill 路由推荐 · feat-020 **感知阶段挂 skill 推荐**(auto-loop 发现待办时顺带列相关技能包) |

---

## 2. 未完成 / 进行中

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

- provenance 深化:由期刊画像的 `data_availability=required` 驱动强制 replication-package 声明。

> **已放弃**(2026-07-03,用户决定):~~AcademicForge 包成 MCP connector~~(现有「发现 + 路由指引」已够,
> 不必让 psyclaw 执行 Agent Skill);~~期刊画像加字数/版块的稿件级核对~~(现只做引用风格 + 数据可得性,足够)。

---

## 4. 里程碑对照(历史 DESIGN §10)

| 里程碑 | 内容 | 状态 |
|--------|------|------|
| M0–M5 | 骨架 → REPL → (统计) → Gates → MCP → 全流水线 | ✅ 已达成后重定位(统计段外移) |
| 后续 | 编排纵深(auto-loop)· 学术诚信(cite-check/provenance)· 期刊定制 · 生态接入 · 会话持久化 | ✅ feat-012…020 全部 done |

> DESIGN.md 为 v0.1 历史设计稿,含内置统计的旧架构描述,顶部已加重定位说明;当前命令集见 `docs/COMMANDS.md`。
