# Session Handoff

> 每轮结束前更新本文件，让下一轮（或换一个 agent）能干净重启 (clean restart)。

## Current Objective

- Goal: 完成 v0.12 候选清单(用户给定 5 项 + TODO §3 provenance 深化)并发布 v0.12.0
- Current status: **v0.12.0 已发布**——feat-065~075 done;75 个 feature 全 done
- Branch / commit: master(v0.12.0 release 提交为最新;**未推送**,master 受保护)

## Completed This Session

- [x] feat-065 错误自学习+图片渲染进 agent 模式(toolloop lessons 回灌+返回;只看 ok=False)
- [x] feat-066 教训卡正向加固(再现 → active 强度+1 / pending hits+1;注入按强度降序)
- [x] feat-067 确认提示自解释措辞(用户反馈:`a` 不易懂)
- [x] feat-068 选择器弃全屏蓝色对话框改原地内联(用户反馈;ANSI 重画不清屏)
- [x] feat-069 @图片 引用内联渲染(上下文只注元信息,修二进制乱码)
- [x] feat-070 「全部同意」按命令前缀限定(用户反馈:放行所有太宽;`cmd_approval_scope`)
- [x] feat-071 选择器高亮项 2 行详情区(用户反馈:看不见方案)
- [x] feat-072 v0.10 遗留收尾(`pystat_meta` DL+Egger · 写作注入真跑结果 · `_real_result` 守卫 · [stats] 数值实测)
- [x] feat-073 eval harness(`psyclaw eval`:6 用例 28 检查,确定性离线)
- [x] feat-074 provenance 深化(required 期刊强制 replication-package 声明 + 门禁 `REPRO.replication_package`)
- [x] feat-075 v0.12.0 发布收尾(版本 + CHANGELOG + COMMANDS + progress/handoff)

## Verification Evidence

| Check | Command | Result |
|---|---|---|
| 全量测试 | `uv run --python 3.12 --with pytest python -m pytest -q` | 1460 passed |
| 门禁自检 | `python -m psyclaw gates` | 22 条规则 ✓ |
| 离线评测 | `python -m psyclaw eval` | 6 用例 28/28,exit=0 |
| CLI 版本 | `psyclaw version` | 0.12.0 |
| 数值实测 | pystat_meta / pystat_ttest(uv+清华镜像真装 statsmodels/pingouin) | 合并效应 0.327 CI[0.200,0.455] I²=9.7% Egger p=.0045;T=-7.11 p=.0004 d=5.03——与生成脚本直跑数值一致 |
| provenance 端到端 | `psyclaw provenance <脚本> --journal psych-science --data <csv>` | 声明生成 ✓ exit=0;缺 --data 列缺项 exit=1 |

## Files Changed(v0.12)

- 新增 `psyclaw/evalharness.py` + `tests/test_evalharness.py`、`tests/test_agent_learning.py`
- 改 `psyclaw/toolloop.py`(collect_env_lessons+lessons 返回)、`psyclaw/repl.py`(_ingest_lessons ·
  render_images_in_text · @图片 元信息 · cmd_approval_scope · 确认措辞)、`psyclaw/choices.py`
  (_pick_inline 原地内联+详情区)、`psyclaw/memory.py`(强度加固)、`psyclaw/cli.py`
  (eval 子命令 · agent 落 lessons/渲染图 · provenance 声明展示)、
  `psyclaw/mcp/servers/pystat_server.py`(pystat_meta)、`psyclaw/workflows/{pystat_bridge,steps_meta,steps_analysis}.py`
  (真结果守卫+注入)、`psyclaw/provenance.py`(replication 声明)、`psyclaw/gates/{rules.yaml,checker.py}`
  (REPRO.replication_package)
- `pyproject.toml` `psyclaw/__init__.py` `CHANGELOG.md` `docs/COMMANDS.md` + TODO/progress/feature_list

## Decisions Made

- 自学习只蒸馏 **ok=False** 的工具结果——ok=True 的输出可能是读到的文件内容,当环境事实会误学。
- 「统计库未安装」返回的脚本骨架**不算真结果**(`_real_result` 守卫)——写作只引用真实数值。
- replication-package 声明**照常生成**(非强制期刊可自愿附),但只有 `data_availability=required` 才被门禁强制——旧 sidecar/非强制期刊不受影响(契约不破坏)。
- eval harness 用例崩溃记为失败 check(fail-closed),不静默跳过;报告落 `.psyclaw/eval_report.json`(已 gitignore)。

## Blockers / Risks

- 无阻塞。PyPI 直连超时,统计栈实测走清华镜像:`UV_HTTP_TIMEOUT=300 uv run --index-url https://pypi.tuna.tsinghua.edu.cn/simple --with statsmodels --with pingouin …`。
- 本机只有 python3.9,测试/运行走 `uv run --python 3.12`(memory 已记)。
- master 有 9 个本地提交未推送(受保护分支,等用户决定)。

## Next Session Startup

1. 读 `CLAUDE.md` → `feature_list.json` → `progress.md` → 本交接。
2. `uv run --python 3.12 --with pytest python -m pytest -q` 确认 1460 绿再动手。
3. `python -m psyclaw eval` 28/28 作为编排层回归基线。

## Recommended Next Step

- TODO §3 候选已清空(provenance 深化已完成,其余两项用户已放弃)。无排期项;
  下一步等用户新需求,或从真实使用反馈里挑卡点(v0.11/v0.12 的交互修复都来自实测)。
