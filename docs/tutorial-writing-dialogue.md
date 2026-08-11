# 对话演示：从真实结果到投稿前交付

这份教程演示如何把已经运行的分析结果交给 PsyClaw，完成方法部分、结果部分和投稿前检查。PsyClaw 不会补写缺失统计数值。

## 前置条件

```bash
python -m psyclaw doctor
python -m psyclaw config
```

方法和结果写作需要可用的 LLM provider。未配置 provider 或缺少 API key 时，相关命令会明确失败并提示运行 `python -m psyclaw config`，不会静默切换到 mock。

准备好：

- 已实际运行的统计脚本和结果文件；
- 含研究设计、样本、变量和分析决策的项目记录；
- 稿件 Markdown，例如 `notes/manuscript.md`。

## 对话

```text
用户：请根据 outputs/analysis_result.txt 和 notes/design.md 写方法与结果部分。只使用真实输出中的数值，缺失的结果保留占位符。

PsyClaw：我会先读取研究设计和真实分析回执，再检查样本、变量、效应量、置信区间和前提诊断是否一致。没有出现在回执中的数值不会被补写。

用户：写完后按心理学期刊规范检查，并告诉我所有阻断项。
```

常用命令：

```bash
python -m psyclaw check notes/manuscript.md --journal psych-science
python -m psyclaw export notes/manuscript.md --docx outputs/manuscript.docx
```

也可以直接在对话中提出同一目标。写盘、导出 Word 和修改稿件属于副作用操作，用户应看到审批提示。

## 检查重点

- 方法部分是否说明样本、缺失处理、排除标准和确证/探索性质；
- 统计结果是否来自真实脚本回执；
- 效应量和 95% CI 是否存在；
- 文内引用是否能回溯到检索语料；
- 图件、表格和脚注是否符合目标期刊约束；
- 生成脚本、环境和输入是否具备 provenance。

## 常见卡点

| 现象 | 判断 | 处理 |
|---|---|---|
| 结果里缺数值 | 统计脚本没有真实输出 | 回到分析流程运行脚本，不能让模型猜数值 |
| JARS 检查阻断 | 稿件缺少研究报告必要信息 | 根据检查结果补齐后重跑 `check` |
| 孤儿引用 | 引用没有来源证据 | 重新检索或删除该引用，不保留未经核验的条目 |
| DOCX 视觉不一致 | 需要 Word/LibreOffice 实际打开检查 | 运行结构检查后，再做目标环境视觉验收 |
| 导出失败 | 缺少可选转换依赖或输入格式不完整 | 运行 `doctor`，保留 Markdown 和检查报告 |

## 验收标准

交付物至少应包括稿件、检查结果、统计脚本/环境溯源和未解决问题清单。`export` 成功只代表文件生成成功，不代表论文已经通过方法学或期刊审查。
