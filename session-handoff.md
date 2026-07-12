# Session Handoff

> 每轮结束前更新本文件，让下一轮（或换一个 agent）能干净重启 (clean restart)。

## Current Objective

- Goal: 统一 run 执行行为,并保持 chat / run / auto 公开心智模型
- Current status: **feat-078 done,未发布**;旧命令、旧参数和内部标识保留兼容
- Branch / commit: master;工作区含用户手测产物与本轮未提交修改,未推送

## Completed This Session

- [x] feat-078 run 默认连续执行、探索性/逐步确认/恢复统一参数、逐步检查点、auto 可重试状态
- [x] feat-077 用户术语统一为研究准备项 / 前置检查 / 质量检查,新增回归测试
- [x] feat-076 三入口共享路由、CLI/REPL 收敛、兼容别名、全套文档与内置 skill 同步
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
| feat-078 定向测试 | `C:/Python314/python -m pytest ...` | 189 passed |
| feat-078 全量测试 | `uv run --python 3.12 --with pytest python -m pytest -q` | 1483 passed;12 个既有 Windows 图片/MCP 环境失败 |
| feat-078 质量规则 | `python -m psyclaw gates` | 22 条规则 |
| feat-078 离线评测 | `python -m psyclaw eval` | 28/28 |
| feat-078 Harness | `node .agents/skills/harness-creator/scripts/validate-harness.mjs --target .` | 100/100 |
| feat-077 定向测试 | `C:/Python314/python -m pytest ...` | 203 passed |
| feat-077 全量测试 | `uv run --python 3.12 --with pytest python -m pytest -q` | 1474 passed;12 个既有 Windows 图片/MCP 环境失败 |
| feat-077 质量检查 | `python -m psyclaw gates` | 22 条规则 |
| feat-077 离线评测 | `python -m psyclaw eval` | 28/28 |
| feat-077 Harness | `node .agents/skills/harness-creator/scripts/validate-harness.mjs --target .` | 100/100 |
| feat-076 定向测试 | `python -m pytest ... modes/cli/repl/status/workflow` | 342 passed |
| 当前全量测试 | `uv run --python 3.12 --with pytest python -m pytest -q` | 1473 passed;12 个既有 Windows 图片/MCP 环境失败 |
| Harness | `node .agents/skills/harness-creator/scripts/validate-harness.mjs --target .` | 100/100 |
| 全量测试 | `uv run --python 3.12 --with pytest python -m pytest -q` | 1460 passed |
| 门禁自检 | `python -m psyclaw gates` | 22 条规则 ✓ |
| 离线评测 | `python -m psyclaw eval` | 6 用例 28/28,exit=0 |
| CLI 版本 | `psyclaw version` | 0.12.0 |
| 数值实测 | pystat_meta / pystat_ttest(uv+清华镜像真装 statsmodels/pingouin) | 合并效应 0.327 CI[0.200,0.455] I²=9.7% Egger p=.0045;T=-7.11 p=.0004 d=5.03——与生成脚本直跑数值一致 |
| provenance 端到端 | `psyclaw provenance <脚本> --journal psych-science --data <csv>` | 声明生成 ✓ exit=0;缺 --data 列缺项 exit=1 |

## Files Changed(feat-076)

- 新增 `psyclaw/modes.py`、`tests/test_modes.py`。
- 修改 `psyclaw/cli.py`、`repl.py`、`ui.py`、`status.py`、`path_ingest.py`、`autoloop.py`、
  `workflows/registry.py` 与内置 research skills。
- 修改 README、TUTORIAL、COMMANDS、ARCHITECTURE、CHANGELOG 和 harness 状态文件。
- 工作区中的 Word、`outputs/`、`notes/goal.md`、手测案例是用户现有产物,未回退。

## Files Changed(feat-077)

- 修改用户可见运行文案:`psyclaw/psych/{clarify,preregister}.py`、`workflows/`、
  `cli.py`、`repl.py`、`status.py`、`autoloop.py`、`pipeline.py`、`loop.py`、`gates/`。
- 同步内置 agents/skills、README、docs、DESIGN、AGENTS/CLAUDE 与项目元数据。
- 新增 `tests/test_terminology.py`;更新受文案影响的测试断言和研究准备清单表头 fixture。

## Files Changed(feat-078)

- 修改 `psyclaw/modes.py`、`cli.py`、`repl.py`:公开 run 类型与统一参数,新增 `prepare`。
- 修改 `psyclaw/workflows/engine.py`:逐步原子检查点、安全恢复、输入自动恢复。
- 修改 `psyclaw/autoloop.py`、`status.py`:失败转 needs_attention,下次可重试,迭代上限按单次运行。
- 同步 README、COMMANDS、TUTORIAL、ARCHITECTURE 与内置 workflow skills;补 modes/workflow/auto 测试。

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

- 公开 `run` 只包含具备稳定输入、步骤、产物和验收契约的四条 workflow;固定 research pipeline 与通用 task loop 仅保留兼容。
- `--exploratory` 表达推断身份变化,取代公开的“跳过检查”;`--resume` 必须拒绝任何状态漂移。
- 用户术语按语义分层:流程启动条件称“前置检查”,产出规范校验称“质量检查”;内部兼容标识不改。
- 自学习只蒸馏 **ok=False** 的工具结果——ok=True 的输出可能是读到的文件内容,当环境事实会误学。
- 「统计库未安装」返回的脚本骨架**不算真结果**(`_real_result` 守卫)——写作只引用真实数值。
- replication-package 声明**照常生成**(非强制期刊可自愿附),但只有 `data_availability=required` 才被门禁强制——旧 sidecar/非强制期刊不受影响(契约不破坏)。
- eval harness 用例崩溃记为失败 check(fail-closed),不静默跳过;报告落 `.psyclaw/eval_report.json`(已 gitignore)。

## Blockers / Risks

- 本轮功能无阻塞。Windows 环境仍有 12 个既有失败:3 个终端图片协议测试、9 个 MCP 子进程
  roundtrip/工具浮出测试;新增模式测试全部通过。
- PyPI 直连超时,统计栈实测走清华镜像:`UV_HTTP_TIMEOUT=300 uv run --index-url https://pypi.tuna.tsinghua.edu.cn/simple --with statsmodels --with pingouin …`。
- 本机只有 python3.9,测试/运行走 `uv run --python 3.12`(memory 已记)。
- master 有 9 个本地提交未推送(受保护分支,等用户决定)。

## Next Session Startup

1. 读 `CLAUDE.md` → `feature_list.json` → `progress.md` → 本交接。
2. 先跑 feat-076 定向测试;全量当前预期为 1473 passed + 12 个已知 Windows 环境失败。
3. `python -m psyclaw eval` 28/28 作为编排层回归基线。

## Recommended Next Step

- 用同一手测案例分别验证 `psyclaw`、`psyclaw run analysis ...`、`psyclaw auto` 三入口的
  产物一致性;随后实现共享 Analysis Contract,解决异常值/ANCOVA 事后比较/CI 量纲问题。
