# Session Handoff

> 每轮结束前更新本文件，让下一轮（或换一个 agent）能干净重启 (clean restart)。

## Current Objective

- Goal: v0.6，重点=多轮对话稳、工具调用不出问题(用户 /goal)
- Current status: **v0.6.0 已发布**——feat-043..046 全部 done;46 个 feature 全 done
- Branch / commit: master(v0.6.0 release 提交为最新)

## Completed This Session

- [x] feat-043 参数规范化(args JSON 字符串解析/非对象引导;工具异常标 ok=False)
- [x] feat-044 无进展检测(重复相同调用/空回复→no_progress 收敛)
- [x] feat-045 消息序列不变量(sanitize_messages 防 400)
- [x] feat-046 多轮集成测试 + 版本 0.6.0 + CHANGELOG

## Verification Evidence

| Check | Command | Result |
|---|---|---|
| 全量测试 | `uv run --python 3.12 --with pytest python -m pytest -q` | 1264 passed |
| CLI 版本 | `psyclaw version` | 0.6.0 |
| 多轮集成 | test_toolloop_multiturn 2 例 | 绿(正常→畸形自纠→截断→未知→重发→答案) |
| 工具循环 | test_toolloop 60 例 | 绿 |

## Files Changed(v0.6)

- `psyclaw/toolloop.py`(_normalize_args/_calls_signature/sanitize_messages + 循环加固)
- `tests/test_toolloop.py`(+20 例)`tests/test_toolloop_multiturn.py`(新增)
- `pyproject.toml` `psyclaw/__init__.py` `CHANGELOG.md` + TODO/progress/handoff
- 未提交:`.claude/`(本地 Claude Code hooks/agents/skills,待用户定夺是否入库)

## Decisions Made

- 无进展阈值 _MAX_NOPROGRESS=2(相同调用执行 2 次后第 3 次识别为卡住即停)
- 畸形 args 在 parse 层拦截(报错引导模型),不进工具 run;工具真异常标 ok=False
- sanitize_messages 每次调 provider 前无条件套用(便宜且防一切拼装意外)

## Blockers / Risks

- 本机只有 python3.9,测试/运行走 `uv run --python 3.12`(memory 已记)
- 多轮加固均用 ScriptedProvider 离线验证;未做真实 LLM 长会话实网压测

## Next Session Startup

1. 读 `CLAUDE.md` → `feature_list.json` → `progress.md` → 本交接。
2. `uv run --python 3.12 --with pytest python -m pytest -q` 确认 1264 绿再动手。

## Recommended Next Step

- v0.7 候选(未立项):① 各 workflow 分析步直连 pystat MCP(把 feat-040 接进 meta/analysis
  流程,闭环最高杠杆,v0.5/v0.6 handoff 均提过);② 真实 LLM 多轮长会话实网压测(把离线
  ScriptedProvider 覆盖延伸到实网,验证截断/无进展/蒸馏在真模型上的表现);③ eval harness。
