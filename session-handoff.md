# Session Handoff

> 每轮结束前更新本文件，让下一轮（或换一个 agent）能干净重启 (clean restart)。

## Current Objective

- Goal: 继续开 v0.5(用户 /goal)
- Current status: **v0.5.0 已发布**——feat-039..042 全部 done;38→42 个 feature 全 done
- Branch / commit: master(v0.5.0 release 提交为最新)

## Completed This Session

- [x] feat-039 MCP stdio 客户端(client.py,真实 subprocess 往返)
- [x] feat-040 agent 循环接入 MCP 工具(agent_tools.py;live 浮出真实 mne-mcp 4 工具)
- [x] feat-041 compact_history 可选 LLM 蒸馏(fail-safe 回落规则蒸馏)
- [x] feat-042 版本 0.5.0 + CHANGELOG + docs(COMMANDS/ARCHITECTURE)

## Verification Evidence

| Check | Command | Result |
|---|---|---|
| 全量测试 | `uv run --python 3.12 --with pytest python -m pytest -q` | 1242 passed |
| CLI 版本 | `psyclaw version` | 0.5.0 |
| MCP 接入 live | `build_tools('.')` | 内置 6 + 真实 mne-mcp 4 = 10 工具 |
| MCP 客户端往返 | test_mcp_client 8 例 | 绿(真 subprocess) |

## Files Changed(v0.5)

- 新增 `psyclaw/mcp/client.py` `psyclaw/mcp/agent_tools.py`
  `tests/test_mcp_client.py` `tests/test_mcp_agent_tools.py` `tests/_mcp_echo_server.py`
- 改 `psyclaw/toolloop.py`(build_tools 并 MCP)`psyclaw/context.py`(LLM 蒸馏)
  `psyclaw/repl.py` `pyproject.toml` `psyclaw/__init__.py` `CHANGELOG.md`
  `docs/COMMANDS.md` `docs/ARCHITECTURE.md` + TODO/progress
- 未提交:`.claude/`(本地 Claude Code hooks/agents/skills,待用户定夺是否入库)

## Decisions Made

- MCP 工具一律 side_effect=True(外部进程执行,保守 fail-closed)
- 客户端进程级缓存(按 command)+ atexit,避免 REPL 反复 build_tools 泄漏子进程
- LLM 蒸馏仅在 provider 有 key 时启用(否则 mock 套话会污染备忘)
- 版本跳过 0.4.0(v0.4 工件 feat-036/037/038 折进 0.5.0 CHANGELOG)

## Blockers / Risks

- 本机只有 python3.9,测试/运行走 `uv run --python 3.12`(memory 已记)
- MCP 接入的 live 验证目前只覆盖 mne-mcp(本机唯一 always-on 且模块就绪的 command 服务器);
  带 key 的 LLM 蒸馏只有离线 fake provider 测试,未实网验证

## Next Session Startup

1. 读 `CLAUDE.md` → `feature_list.json` → `progress.md` → 本交接。
2. `uv run --python 3.12 --with pytest python -m pytest -q` 确认 1242 绿再动手。

## Recommended Next Step

- v0.6 候选(未立项):① 各 workflow 分析步从"生成脚本"升级为"可选直连 pystat MCP"
  (把 feat-040 的能力接到 meta/analysis 流程,闭环最高杠杆);② eval harness(历次 handoff 提过);
  ③ REPL `/mcp-tools` 让用户直接看/试 agent 可用的 MCP 工具清单。
