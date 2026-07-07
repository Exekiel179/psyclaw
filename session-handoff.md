# Session Handoff

> 每轮结束前更新本文件，让下一轮（或换一个 agent）能干净重启 (clean restart)。

## Current Objective

- Goal: v0.9 新增 setup —— 一键配置好所缺失的基础环境(用户请求)
- Current status: **v0.9.0 已发布**——feat-051/052 done;52 个 feature 全 done
- Branch / commit: master(v0.9.0 release 提交为最新)

## Completed This Session

- [x] feat-051 `setup --env` 一键环境配置(env_setup.py:diagnose + bootstrap)
- [x] feat-052 版本 0.9.0 + CHANGELOG + COMMANDS

## Verification Evidence

| Check | Command | Result |
|---|---|---|
| 全量测试 | `uv run --python 3.12 --with pytest python -m pytest -q` | 1293 passed |
| CLI 版本 | `psyclaw version` | 0.9.0 |
| setup --env live | `psyclaw setup --env` | 正确诊断:config✓ provider✓ stats✗ full✗ + 修法 |
| env_setup 单测 | test_env_setup 11 例 | 绿(依赖注入,离线) |

## Files Changed(v0.9)

- 新增 `psyclaw/env_setup.py` `tests/test_env_setup.py`
- 改 `psyclaw/cli.py`(setup --env 分支 + 参数)
- `pyproject.toml` `psyclaw/__init__.py` `CHANGELOG.md` `docs/COMMANDS.md` + TODO/progress
- 未提交:`.claude/`(本地 Claude Code hooks/agents/skills,待用户定夺是否入库)

## Decisions Made

- `setup --env` 作为 setup 的子模式(不动既有脚手架流程),env_setup.py 独立模块
- base 环境 = 配置文件 + provider key + stats 组 + full 组;API key 不能自动装 → 列待手动
- 依赖注入(detect/config/provider/installer)保证离线可测,不真联网/真 pip

## Blockers / Risks

- 本机 uv py3.12 无 pingouin/prompt_toolkit,`--online` 真安装路径未在本机实测
  (installer 逻辑复用既有 bootstrap._pip_install,注入 fake 已测编排逻辑)
- 本机只有 python3.9,测试/运行走 `uv run --python 3.12`(memory 已记)

## Next Session Startup

1. 读 `CLAUDE.md` → `feature_list.json` → `progress.md` → 本交接。
2. `uv run --python 3.12 --with pytest python -m pytest -q` 确认 1293 绿再动手。

## Recommended Next Step

- v1.0 候选(未立项):① workflow 的 analysis/meta 分析步默认走 pystat MCP 出结果
  (端到端闭环,历次提);② `setup --env --online` 真安装路径在装齐环境上实测;
  ③ eval harness;④ `doctor` 与 `setup --env` 合流(doctor 只读诊断 → 一键跳 setup --env 修)。
