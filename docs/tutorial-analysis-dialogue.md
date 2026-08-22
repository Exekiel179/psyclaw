> **v0.23 legacy documentation.** 本页保留用于复现 PsyClaw v0.23.0；v0.24.0 的当前范围、接口与验收标准请以 开工纪要.md、架构蓝图.md 和 评测框架.md 为准。

# 对话演示：从 CSV 到可复现统计脚本

这份教程演示社会科学人员最常见的数据分析路径。PsyClaw 负责数据画像、研究设计建议、脚本生成和质量检查；统计计算由 `[stats]` 依赖或 MCP 后端完成。

## 前置条件

```bash
python -m psyclaw setup --project --modules stats --non-interactive
python -m psyclaw doctor
```

分析设计和脚本生成需要可用的 LLM provider。未配置 provider 或缺少 API key 时，流程会明确失败并提示运行 `python -m psyclaw config`，不会静默切换到 mock。

把清洗后的数据放在 `data/clean/`。原始数据应放在 `data/raw/`，PsyClaw 不读取或写入其原始行。

## 对话

```text
用户：请分析 data/clean/scores.csv。group 是组别，post_score 是结果变量，pre_score 是基线变量。

PsyClaw：我先做数据画像，不直接假设第一个数值列就是结果变量。我会检查行列数、缺失、重复整行、无效数值、数值范围和分类水平。

用户：先告诉我数据质量问题，再生成分析脚本，不要替我删除任何记录。
```

对应命令：

```bash
python -m psyclaw run analysis data/clean/scores.csv \
  --topic "比较两组 post_score，并控制 pre_score"
```

Agent 对话路径还可以调用原生工具：

```text
profile_dataset({"csv_path":"data/clean/scores.csv"})
```

期望结果包括：

- 数据画像：行列数、数值/分类列、缺失率、重复行、数值统计和无效值示例；
- 研究/分析设计备忘；
- `outputs/analysis.py` 或同等可复现脚本；
- 推荐分析与前提提示；
- `notes/workflow_summary.json`。

生成脚本后再运行：

```bash
python outputs/analysis.py
python -m psyclaw provenance outputs/analysis.py
```

## 真实统计与降级行为

安装 `[stats]` 后，脚本可以调用 pandas、pingouin、SciPy、statsmodels 等库。没有统计库时，系统必须明确返回“统计库未安装”或可运行脚本骨架，不能把脚本骨架包装成真实结果。

## 常见卡点

| 现象 | 判断 | 处理 |
|---|---|---|
| CSV 不存在/在项目外 | 路径安全检查拒绝执行 | 将清洗数据放入 `data/clean/` |
| 缺失或重复被报告 | 这是质量提示，不是自动清洗 | 由研究者决定保留、插补或剔除，并记录理由 |
| 数值列混入 `NaN`/文本 | 数据编码问题 | 修正编码后重新画像，不直接强制转换 |
| 只有脚本没有结果 | 统计依赖未安装或 MCP 不可用 | 安装 `psyclaw[stats]`，或配置相应统计 MCP |
| 分析建议不确定 | 研究设计信息不足 | 先补充组别、测量时点、重复测量和协变量信息 |

## 验收标准

统计报告只有在脚本真实运行成功、效应量和 95% CI 可追溯、输入数据和结果路径一致时，才能被视为完成。生成脚本不等于完成统计分析。
