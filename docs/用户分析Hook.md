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

支持事件：`before-analysis`、`before-write`、`after-analysis`。脚本型 hook 暂不自动加载；需要执行外部程序时，必须走来源、依赖、权限和人工审批流程。
