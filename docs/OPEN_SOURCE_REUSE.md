> **v0.23 legacy documentation.** 本页保留用于复现 PsyClaw v0.23.0；v0.24.0 的当前范围、接口与验收标准请以 开工纪要.md、架构蓝图.md 和 评测框架.md 为准。

# 开源复用清单

这份清单是依赖决策记录，不是安装建议堆。每个外部能力都写清入口、退出路径和当前边界。

| 能力 | 许可证/维护状态 | 接口稳定性 | PsyClaw 接入 | 引入成本 | 替代与退出路径 |
|---|---|---|---|---|---|
| MarkItDown | MIT；可选依赖，社区维护 | 只依赖 `convert()` 文本结果 | `psyclaw convert`：DOCX/PDF 等复杂材料优先调用 | 额外 Python 依赖 | 纯 stdlib 的 md/txt/html/csv/json 转换仍可用；卸载后这些格式不受影响 |
| ScholarBridge 思路 | 参考协议，不复制代码；本地维护审计 | PsyClaw 自有下载契约 | `download_pdf`：`%PDF`、SHA-256、`pdf_audit.json`、重复内容复用 | 本地哈希与审计文件 | 删除审计文件即可重建；下载核心仍由 stdlib urllib 负责 |
| Academic Reference Matcher 思路 | 参考数据协议；本地维护 | `claim/source/status/locator` 稳定字段 | `evidence.py` Claim-Evidence 账本，可供 cite/provenance 迁移 | 新增字段，不改旧 sidecar | 账本是可删除的派生产物，旧格式继续工作 |
| OmniDistill / OPID 思路 | 参考治理规则；不引入训练栈 | JSONL staging 可版本化 | `skill_distill.py`：候选→复现→人工晋升/拒绝 | 零 GPU/训练依赖 | 删除 staging 文件；不会自动修改 bundled Skill |
| Corpus2Skill / OpenKB 思路 | 参考导航协议；不复制服务端 | `INDEX.md` + manifest + 分文件材料 | `psyclaw compile`：目录→可导航 staged Skill；四类验证后才可晋升 v3 | 纯 stdlib；复杂格式沿用可选 MarkItDown | 编译目录是派生产物，可删除重建；原资料不修改 |
| Session Handoff 思路 | 参考交接协议；本地实现 | `HANDOFF.md` + JSON v1 | `psyclaw handoff`：目标/完成项/下一步/阻塞可重放 | 纯 stdlib | 删除交接产物不影响 SQLite 会话与 workflow checkpoint |
| SmartPlot / CodePivot | 暂不作为核心依赖；随用户环境变化 | MCP 工具由 registry 声明并缓存 | 通过 MCP/受控桥接使用，不复制绘图引擎或桌面 UI | 零核心依赖 | MCP 不可用时保留脚本/人工路径 |

默认原则：先借协议，再借实现；任何新依赖必须可禁用、可审计、可退出。
