# Session Handoff

> 每轮结束前更新本文件，让下一轮（或换一个 agent）能干净重启 (clean restart)。

## Current Objective

- Goal: v0.14.0 发布(三轮对抗评估缺陷清零 + 文献查找全链)
- Current status: **v0.14.0 已发布**——feat-090~110 done;110 个 feature 全 done
- Branch / commit: master(待用户推送:`! git push origin master`;tag:`git tag v0.14.0 && git push origin v0.14.0`)
- 待排期候选:feat-105(未跑先造示例数值)/feat-106(路径注入误报,低优先)

## Completed This Session
- [x] 快进合并 feat/interaction-model-run-contracts(feat-076..078)进 master(先测后并:1495 绿)
- [x] feat-079 真结果守卫结构化 + feat-080 POSIX 方向键(两条主线)
- [x] feat-081~088 其余 8 项评审缺陷全部修复(批准范围/期刊静默/confirm hits/eval GBK/
  CJK 宽度/图片直渲+force TTY/落卡诚实计数/教训抗修剪)
| Check | Command | Result |
|---|---|---|
| 全量测试 | `uv run --python 3.12 --with pytest python -m pytest -q` | 1553 passed |
| 离线评测 | `python -m psyclaw eval` | 28/28 exit=0 |
| 质量检查自检 | `python -m psyclaw gates` | 通过 |
| feat-079 数值 | pystat_meta clean/dirty/k=2 三态(镜像真装 statsmodels) | clean 与基线逐位一致;dirty 剔坏行呈报;k=2 无 NaN |
| feat-080 真键盘 | tests/test_ui_input_keys.py(pty 喂原始字节) | 5/5(↓↑/ESC/未知转义/中文/EOF) |
1. 读 `CLAUDE.md` → `feature_list.json` → `progress.md` → 本交接。
2. `uv run --python 3.12 --with pytest python -m pytest -q` 确认 1553 绿再动手。
3. 提醒用户推送:master 领先 11 个提交(`! git push origin master`)。
- 评审遗留的低优先级清理(未立项):steps_meta/steps_analysis 注入块共享 helper、
  生成脚本 res.i2 退化角落加 q>0 守卫、CHANGELOG 补 pre-v0.12 required 期刊 sidecar
  迁移说明。无阻塞项;等用户新需求。
- feat-123(角色模型路由)+ feat-124(辩论式评审档位)已完成入库(95967f1),
  1724 绿 / eval 28/28。用法:配置 `reviewer_provider/reviewer_model` 等键实现
  「便宜模型起草、强模型评审」;`psyclaw review --debate` 或配置
  `review_mode: debate` 开深评档(9 调用/轮,快评档默认零变化)。
- 后续候选(未立项):critic 修复环加辩护人+独立裁判、audit 多裁判面板、
  LLM-judge 汇入 pipeline_verdict(只收紧不放宽)、埋缺陷稿件的裁判召回率小基准。
- ⚠ 并行会话正在做沙箱系统(feat-118~122,TODO 已立案、工作树有未提交文件),
  提交时**不要 `git add -A`**,按文件显式 add,避免互卷。
- 2026-07-15 用户拍板:③ LLM-judge 汇入 pipeline_verdict 与 ④ 裁判召回率基准**暂缓不做**,多智能体线本阶段到 feat-123/124 为止收束;除非用户重新提出,过夜循环不要自行立项。
