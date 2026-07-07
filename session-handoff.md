# Session Handoff

> 每轮结束前更新本文件，让下一轮（或换一个 agent）能干净重启 (clean restart)。

## Current Objective

- Goal: 完成 v0.3 开发 → 写新计划(v0.4)→ 逐条完成(用户 /goal)
- Current status: **v0.3.0 已发布**(feat-031..035);v0.4 feat-036/037/038 全部 done
- Branch / commit: master(v0.4 收尾提交为最新)

## Completed This Session

- [x] v0.3.0:shell fail-closed(HIGH)· save_file 允许清单(MEDIUM)· 上下文滚动修剪 ·
      中文类型别名 · 版本统一 0.3.0 + CHANGELOG
- [x] v0.4:feat-036 provider 网络重试/错误显性化 · feat-037 agent_runs.jsonl + --history ·
      feat-038 docs 同步(COMMANDS/TUTORIAL)+ 本快照

## Verification Evidence

| Check | Command | Result | Notes |
|---|---|---|---|
| 全量测试 | `uv run --python 3.12 --with pytest python -m pytest -q` | 1222 passed | 本机唯一可用测试通道 |
| CLI 版本 | `psyclaw version` | 0.3.0 | uv tool editable 安装 |
| agent 痕迹 | `psyclaw agent "列出项目根目录结构"` → `--history` | 落痕+回显正确 | live e2e |
| 重试离线测 | test_providers TestPostSseRetry 6 例 | 绿 | 429 退避 [1.0,2.0] 等 |

## Files Changed

- v0.3: `psyclaw/repl.py` `psyclaw/toolloop.py` `psyclaw/skills/recommend.py`
  `pyproject.toml` `psyclaw/__init__.py` `CHANGELOG.md` + 对应测试
- v0.4: `psyclaw/providers/base.py` `psyclaw/toolloop.py` `psyclaw/cli.py` `psyclaw/repl.py`
  `docs/COMMANDS.md` `docs/TUTORIAL.md` + 对应测试
- 未提交:`.claude/`(本地 Claude Code hooks/agents/skills 配置,待用户定夺是否入库)

## Decisions Made

- shell 逐条确认是**有意的行为变化**(安全>便利),文档已写清;psyclaw 进程内命令保持自动
- _post_sse 流开始后不重试(防重复消费);仅首字节前退避重试
- v0.4 不单独发版(0.4.0 号留给 scope 再积累;当前 0.3.0)

## Blockers / Risks

- 本机只有 python3.9,一切测试/运行走 `uv run --python 3.12`(memory 已记)
- MCP client 仍是骨架(manager 只做目录/健康检查),agent 循环尚未直连 MCP 工具——v0.5 候选

## Next Session Startup

1. 读 `CLAUDE.md` → `feature_list.json` → `progress.md` → 本交接。
2. `uv run --python 3.12 --with pytest python -m pytest -q` 确认 1222 绿再动手。

## Recommended Next Step

- v0.5 候选(未立项):① agent 循环接入已启用 MCP 服务器的工具(编排纵深,最高杠杆);
  ② REPL 超长会话 compact_history 蒸馏质量的 LLM 辅助升级;③ eval harness(历史 handoff 提过)。
