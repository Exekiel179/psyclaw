# Session Handoff

> 每轮结束前更新本文件，让下一轮（或换一个 agent）能干净重启 (clean restart)。

## Current Objective

- Goal: 发一个 v0.11.0 收尾(用户请求),收束 REPL 交互体验 + 错误自学习 + 图片渲染
- Current status: **v0.11.0 已发布**——feat-055~062 done;62 个 feature 全 done
- Branch / commit: master(v0.11.0 release 提交为最新)

## Completed This Session

- [x] feat-055 `/dump` 导出对话(当前 / `--full` 含隐藏上下文;`transcript.py`)
- [x] feat-056 `/yolo` 审批模式 + 修确认框与命令回显串行(`safe_prompt`)
- [x] feat-057 流式路径 no-progress 检测(深度降为高位安全兜底 100)
- [x] feat-058 错误自学习(命令失败蒸馏环境教训,会话注入 + memory 待确认卡)
- [x] feat-059 环境教训卡自动失效(`archive_lesson` + 再验证,防误删)
- [x] feat-060 选择器非编号输入当自由作答转发(不再吞输入)
- [x] feat-061 终端内联渲染图片(`imgview.py` iTerm2/kitty;`/img` + 自动)
- [x] feat-062 版本 0.10.0→0.11.0 + CHANGELOG v0.11 + COMMANDS + progress/handoff

## Verification Evidence

| Check | Command | Result |
|---|---|---|
| 全量测试 | `uv run --python 3.12 --with pytest python -m pytest -q` | 1382 passed |
| CLI 版本 | `psyclaw version` | 0.11.0 |
| 图片探测 | `imgview._proto_from_env`(Warp env) | iterm2 |
| 教训失效 | 隔离记忆:`ls` 卡自动归档、`no_such_cmd` 卡保留 | 通过 |

## Files Changed(v0.11)

- 新增 `psyclaw/transcript.py` `psyclaw/imgview.py`
  + 测试 `tests/test_transcript.py` `test_repl_approval.py` `test_error_learning.py`
  `test_lesson_invalidation.py` `test_imgview.py`
- 改 `psyclaw/repl.py`(/dump //yolo //img /memory verify · no-progress · 错误学习 · 自动失效
  · 选择器自由文本 · 确认框修复)、`psyclaw/memory.py`(kind + `archive_lesson` + 归档展示)、
  `psyclaw/choices.py`(自由文本回传)、`psyclaw/ui_input.py`(`safe_prompt`)、`psyclaw/loop.py`(`_ask_yn`)
- `pyproject.toml` `psyclaw/__init__.py` `CHANGELOG.md` `docs/COMMANDS.md` + TODO/progress/feature_list
- 未提交:`.claude/`(本地 Claude Code hooks/agents/skills,待用户定夺是否入库)

## Decisions Made

- 审批:YOLO 只放行**非危险**副作用,红线危险命令(`rm -rf`/`push --force`/…)与 `data/raw` 硬拒恒问/恒拒。
- 停机:no-progress 是主判据,深度 100 只是灾难兜底(与 toolloop max_iters 同理),`config max_auto_depth` 可调。
- 教训失效:只碰 `source=error` 机器卡、只在 probe **确证已恢复(True)**时归档——防误删让模型重踩坑。
- 图片:纯 stdlib(终端解码,只 base64),`config image_protocol` 是探测错时的安全阀。

## Blockers / Risks

- Warp 走 iTerm2 图片协议——**多数版本支持**;若某版本显示乱码,`config image_protocol=none` 关掉。
- 错误学习/自动失效目前只覆盖**流式路径**;agent 模式(toolloop)工具失败尚未接同一套。
- 本机只有 python3.9,测试/运行走 `uv run --python 3.12`(memory 已记)。

## Next Session Startup

1. 读 `CLAUDE.md` → `feature_list.json` → `progress.md` → 本交接。
2. `uv run --python 3.12 --with pytest python -m pytest -q` 确认 1382 绿再动手。

## Recommended Next Step

- v0.12 候选(未立项):① 错误学习 + 图片渲染接入 **agent 模式(toolloop)**;② 教训卡**正向加固**
  (同一失败再现→强度 +1,memory 文档已提);③ `@图片` 引用也内联渲染;④ v0.10 遗留:step_write
  引用真分析结果回填稿件、meta workflow 接 pystat、装 [stats] 数值实测;⑤ eval harness。
