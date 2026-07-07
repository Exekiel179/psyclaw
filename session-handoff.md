# Session Handoff

> 每轮结束前更新本文件，让下一轮（或换一个 agent）能干净重启 (clean restart)。

## Current Objective

- Goal: 实现 v0.7 版本(用户 /goal);期间用户插入 REPL 方向键 bug,优先修复
- Current status: **v0.7.0 已发布**——feat-047/048 done;48 个 feature 全 done
- Branch / commit: master(v0.7.0 release 提交为最新)

## Completed This Session

- [x] feat-047 REPL 方向键/历史/光标(readline 后端,修用户报的 ^[[A)
- [x] feat-048 版本 0.7.0 + CHANGELOG + TUTORIAL

## Verification Evidence

| Check | Command | Result |
|---|---|---|
| 全量测试 | `uv run --python 3.12 --with pytest python -m pytest -q` | 1270 passed |
| CLI 版本 | `psyclaw version` | 0.7.0 |
| readline 路由 | test_repl_ptk 40 例 + smoke | 绿(非 ptk TTY 首选 _readline_input) |

## Files Changed(v0.7)

- `psyclaw/ui_input.py`(_readline_input/_rl_wrap_prompt + read_line 路由)
- `tests/test_repl_ptk.py`(改 1 + 新增 6)
- `pyproject.toml` `psyclaw/__init__.py` `CHANGELOG.md` `docs/TUTORIAL.md` + TODO/progress
- 未提交:`.claude/`(本地 Claude Code hooks/agents/skills,待用户定夺是否入库)

## Decisions Made

- 非 ptk TTY 主路径改用 readline(成熟 stdlib,方向键/历史/光标全免费)而非自研 raw reader
- 原 v0.7 计划(pystat MCP 直连)顺延——发现 pystat 在 registry 有声明但**无 server 文件、
  无 command**,feat-040 因此不会浮出它;要直连需先建 pystat_server.py(照 mne_server 惯例:
  惰性 import pingouin,缺失降级为可运行脚本模板),工作量较大,且用户插入的方向键 bug 更急

## Blockers / Risks

- 本机只有 python3.9,测试/运行走 `uv run --python 3.12`(memory 已记)
- 方向键修复用单测 + 非交互 smoke 验证;未在真实交互 TTY 里逐键实测(harness 无法按键)。
  用户可直接 `psyclaw repl` 试 ↑↓←→ 确认

## Next Session Startup

1. 读 `CLAUDE.md` → `feature_list.json` → `progress.md` → 本交接。
2. `uv run --python 3.12 --with pytest python -m pytest -q` 确认 1270 绿再动手。

## Recommended Next Step

- v0.8 候选(未立项):① **pystat MCP 服务器**(psyclaw/mcp/servers/pystat_server.py,惰性
  pingouin/statsmodels,缺失降级脚本模板)+ registry 补 command → 让 feat-040 浮出 pystat →
  meta/analysis workflow 分析步可选直连(闭环「统计外移到 MCP」,最高杠杆,历次 handoff 均提);
  ② 真实交互 TTY 手测方向键;③ eval harness。
