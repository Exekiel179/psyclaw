# 用户分析 Hook

项目可以在 `.psyclaw/analysis-hooks.json` 增加声明式规则。它们只能增加阻断或警告，不能关闭 psyclaw 内置保护。

```json
{
  "schemaVersion": "psyclaw/user-analysis-hooks/v1",
  "hooks": [
    {
      "id": "no-unapproved-outcome",
      "event": "before-analysis",
      "severity": "block",
      "pattern": "unapproved|未批准",
      "message": "该分析包含未批准的结局变量"
    },
    {
      "id": "protect-sensitive-export",
      "event": "before-write",
      "severity": "block",
      "pathPrefix": "outputs/",
      "pattern": "participant|subject|被试",
      "message": "不得导出可识别的被试数据"
    }
  ]
}
```

支持事件覆盖分析全流程：

- `before-plan`：检查研究设计、主要结局以及探索性/确证性边界；
- `before-analysis`：检查输入路径、原始数据保护和输入哈希；
- `before-delegation`：检查统计工具、脚本、环境和输入指纹；
- `before-write`：阻止覆盖原始数据或写入受保护路径；
- `after-analysis`：检查样本量、缺失值、多重比较、效应量、置信区间和结果表述；
- `before-report`：在生成报告或论文正文前拦截超出研究设计的结论；
- `after-report`：检查引用核验和未解决的引用缺口。

脚本型 hook 暂不自动加载；需要执行外部程序时，必须走来源、依赖、权限和独立操作授权流程。用户 hook 只能增加阻断或警告，不能关闭内置规则，也不能创建 `awaiting-human` 研究决策状态。hook 发现的常规问题应先由 AI 修复；无法修复时如实报告。只有另行满足 `psyclaw/research-decision/v1` 合同的实质研究分歧，才请求研究者取舍。
