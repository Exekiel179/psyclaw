> **v0.23 legacy documentation.** 本页保留用于复现 PsyClaw v0.23.0；v0.24.0 的当前范围、接口与验收标准请以 开工纪要.md、架构蓝图.md 和 评测框架.md 为准。

# 对话演示：从研究问题到可核验文献综述

这份教程演示一个文献综述任务。示例使用探索性入口，便于先验证工具链；正式研究应先完成 `psyclaw prepare`，再执行正式 workflow。

## 前置条件

```bash
python -m psyclaw doctor
python -m psyclaw config
```

需要可用的 LLM provider 才能得到完整的研究设计、综述和审稿文本。未配置 provider 或缺少 API key 时，相关命令会明确失败，不会静默切换到 mock。文献检索还需要网络。

## 对话

```text
用户：我想研究正念训练对大学生考试焦虑的干预效果，优先看近三年的研究，最后给我一份带 DOI 的综述。

PsyClaw：我会先确认研究对象、干预形式、结局指标和时间范围。若你暂时只想探索文献，可以显式标记为探索性运行。

用户：先按探索性运行，保留检索和筛选记录。
```

对应命令：

```bash
python -m psyclaw run literature "正念训练对大学生考试焦虑的干预效果" --exploratory
```

期望流程：

```text
研究准备检查 → 文献检索(PRISMA 识别) → 筛选(PRISMA)
→ 合成结构化综述 → 同行评审
```

重点产物通常包括：

- `notes/lit_review.md`
- `notes/evidence_map.json`
- `notes/workflow_summary.json`
- `notes/gate_skips.md`（使用 `--exploratory` 时）

## 用户需要确认什么

用户需要确认研究范围和筛选标准；付费墙全文必须使用用户自己的机构权限或浏览器登录，不应要求 PsyClaw 绕过权限。下载、写入文库和外部 MCP 调用可能触发审批。

## 常见卡点

| 现象 | 判断 | 处理 |
|---|---|---|
| 未配置模型而初始化失败 | 没有配置 LLM provider 或 API key | 运行 `python -m psyclaw doctor` 查看原因，再运行 `python -m psyclaw config` |
| 检索超时 | 网络、代理或外部 API 不可达 | 先运行 `doctor`，再切换可用网络或稍后重试 |
| DOI/全文不完整 | 数据库没有开放全文或机构权限未连接 | 保留 DOI 和证据记录，使用 `lit_open_institutional` |
| 流程停在准备检查 | 正式研究缺少设计决策 | 补充 `prepare`，或明确使用 `--exploratory` 并接受留痕 |

## 验收标准

不要只看终端里的“完成”。应检查 `workflow_summary.json`、文献来源、筛选状态和 DOI；没有真实来源的条目不能进入正式稿件。
