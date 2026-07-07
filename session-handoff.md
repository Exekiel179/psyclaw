# Session Handoff

> 每轮结束前更新本文件，让下一轮（或换一个 agent）能干净重启 (clean restart)。

## Current Objective

- Goal: psyclaw 全流程跑通（环境感知/工具调用/记忆/反馈循环/自进化）；修「工具调用中途提前停止」
- Current status: feat-030 done——截断防护落地，六环节全流程冒烟通过
- Branch / commit: master @ 7f570a1

## Completed This Session

- [x] feat-030 toolloop 截断防护（根因:截断的 ```tool 块被误判为最终答案 → 静默提前停止）
- [x] providers 捕获 stop_reason/finish_reason（归一化 length→max_tokens）+ PSYCLAW_MAX_TOKENS 可配
- [x] agent --max-iters 默认 6→24
- [x] 修 test_mcp_servers 2 例陈旧断言（3d9b183 detect: 门控后未同步）
- [x] 全流程六环节冒烟:status/agent live/记忆召回/auto-loop/gates/技能路由

## Verification Evidence

| Check | Command | Result | Notes |
|---|---|---|---|
| 全量测试 | `uv run --python 3.12 --with pytest python -m pytest -q` | 1190 passed | 本机(macOS)无 3.11+ 系统解释器,走 uv |
| agent 实跑 | `uv run --python 3.12 python -m psyclaw agent "看一下项目目录结构"` | 2 轮 1 调用 answered | 工具循环收敛 |
| auto-loop | `python -m psyclaw auto-loop --max-iters 1 </dev/null` | 感知→停止,不挂起 | 非 TTY fail-closed |
| 记忆 | ContextArchive record+search | 召回命中 1 | |
| 门禁 | `python -m psyclaw gates` | 规则表输出正常 | |

## Files Changed

- `psyclaw/toolloop.py`（截断检测+续写）· `psyclaw/providers/{base,anthropic_api,openai_compat}.py`
- `psyclaw/cli.py`（agent max-iters 24）· `tests/test_toolloop.py`（+6）· `tests/test_mcp_servers.py`（修 2 陈旧）
- `feature_list.json`（feat-030 + evidence）· `TODO.md` · `progress.md`
- 未提交:`.claude/`（hooks/agents/skills 本地 Claude Code 配置,待用户定夺是否入库）

## Decisions Made

- auto-loop 的 max_iters=6 不动（语义=研究阶段数,非工具轮数）
- 截断连续重试上限 _MAX_TRUNC_STREAK=2（防 provider 反复截断死循环）
- 陈旧 mcp 测试改为断言 registry 真源语义（enabled iff shutil.which）而非删除

## Blockers / Risks

- 本机沙箱 allowlist 期望 `python`,只有 `python3`(3.9);统一用 `uv run --python 3.12`
- recommend_skills normalize_type 不识别中文研究类型（『元分析』→None;英文 meta 可）——候选小修

## Next Session Startup

1. 读 `CLAUDE.md`（项目铁律 + Harness 契约）。
2. 读 `feature_list.json` 与 `progress.md`。
3. Review 本交接。
4. `uv run --python 3.12 --with pytest python -m pytest -q` 确认 1190 绿后再动手。

## Recommended Next Step

- 长会话纵深:REPL 的 compact_history 在超长研究会话下的压缩质量验证（配合截断防护,
  这是「对话长期维持」的另一半);或 normalize_type 补中文研究类型别名（小修,高频入口）。
