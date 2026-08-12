# PsyClaw v0.23.0 协作交接

**快照日期：** 2026-08-12

**发布标签：** `v0.23.0`

**分支：** `master`，已推送至 `origin/master`

本页是面向协作者的当前状态、待办和人工验收清单。它区分已自动验证、需要真实环境验证、以及尚未同步的对外文档；不要将三者混为“已完成”。

## 发布结论

`v0.23.0` 已发布。此次版本将 PsyClaw 从“能发现外部 Skill”扩展为可安装的学术
Skill 平台，并补齐 Windows/macOS 双平台安装包与 Agent 执行可靠性修复。

公开心智模型保持两个入口：

- `chat`：研究者与 Agent 协作推进。
- `run`：按声明式流程执行；`run <类型>` 执行指定流程，裸 `run` 自动继续下一步。

旧 `auto` 保留为兼容入口，不再是对外主模型。

## 已交付

| 模块 | 当前能力 | 主要实现/说明 |
|---|---|---|
| 学术编排 | 文献、元分析、实证、质性四类 workflow；前置 gate、检查点、产物与总验收 | `psyclaw/academic_orchestrator.py`、`docs/ARCHITECTURE.md` |
| Agent 原生工具 | 资料导入与编译、证据账本、Skill 蒸馏、交接、图件编排、DOCX 检查以结构化工具暴露给 Agent；CLI 只作人工调试入口 | `psyclaw/academic_tools.py` |
| Skill Registry | 自然语言检索、分类、哈希、来源、证据等级、启停状态和重名副本审计 | `psyclaw/skills/registry.py`、`docs/SKILL_REGISTRY.md` |
| 系统 Skill 包 | core 随包启用；研究设计、文献、定量、写作审稿、智能体学习按领域远程稀疏安装与更新 | `psyclaw/skills/packs.py`、`docs/SKILL_PACKS.md` |
| 宿主生态发现 | 只读识别 Claude Code、Codex、cc-switch 的 Skill、插件和 MCP 配置；项目 MCP 默认仅发现，需显式信任后执行 | `psyclaw/mcp/host_configs.py`、`psyclaw/plugins_catalog.py`、`docs/HOST_SKILL_MCP.md` |
| DOCX 交付质量 | APA7 导出确定性化；检查 OOXML parts、样式、固定表格几何、行不拆分与真实脚注；提供三线表 fixture | `psyclaw/output/docx_contract.py`、`psyclaw/output/docx_visual.py`、`scripts/verify_docx.py` |
| 资料到 Skill | 多格式资料编译为可审计的索引、claims 和 staged Skill；只有带来源的多维验证通过后才能人工晋升 | `psyclaw/materials.py`、`psyclaw/knowledge_compile.py`、`psyclaw/skill_distill.py` |

## 自动化验证

- Skill 相关回归：**53 项通过**。
- `python3 -m psyclaw eval`：**37/37 通过**。
- `git diff --check`：通过。
- `python3 -m psyclaw version`：`psyclaw 0.23.0`。
- 全量 pytest（2026-08-09）：**2325 项通过，12 项跳过，0 项失败**。
- 安装包：`psyclaw-macos-0.23.0.tar.gz` 与 `psyclaw-windows-0.23.0.zip` 均完成结构校验。

## 文档状态

| 文档 | 状态 | 对外使用建议 |
|---|---|---|
| `docs/PsyClaw使用白皮书_v0.23.0.docx` | 已重新生成；新增文献调研实现链路、检索计划、多源检索、PRISMA、Evidence Map、引用核验和真实验收边界；Pandoc 文本抽取与 OOXML ZIP 校验通过 | 可作为 v0.23.0 使用说明；本机未安装 LibreOffice，PDF 仍保留为历史 v0.21.0 归档 |
| `docs/PsyClaw预印本_draft.md/.docx` | 本次随代码提交，但仍是**草稿** | 可供内部讨论；其中“2228 全部通过”等测试数字已过时，投稿/公开前必须按可复跑证据修订 |
| 本页 | 已按 v0.23.0 发布状态整理 | 可直接发送给协作者 |

旧的 v0.21.0 白皮书文件保留为历史归档。当前 DOCX 由 `scripts/build_whitepaper_docx.py` 与当前公开接口维护；本轮未生成新 PDF，因为当前环境没有 LibreOffice/soffice，无法完成可靠的中文分页和字体视觉验收。后续在具备 Word/LibreOffice 与中文字体的环境中，应重新导出 v0.23.0 PDF 并逐页验收。

## 开发待办

### P0：发布后必须收口

- [ ] 更新预印本中的版本、测试数、规则数和功能描述；每个数值必须能追溯到命令输出或测试报告，再重建 DOCX。
- [ ] 在可绑定 localhost 的环境复跑全量 pytest，确认或定位当前 7 个 fixture 错误。

### P1：真实生态兼容性

- [ ] 在真实的 Claude Code、Codex、cc-switch 环境分别验证 Skill、插件和 MCP 发现；检查同名冲突、禁用态和来源偏好。
- [ ] 从干净用户目录安装每个领域 Skill 包，验证 install/update/enable/disable、离线/网络失败提示和不覆盖用户 Skill。
- [ ] 使用一份真实研究项目验证 Agent 的 `skill_search -> skill_get -> 执行` 链路，以及副作用工具审批。

### P2：交付体验与回归基础设施

- [ ] 在装有 LibreOffice 与 Poppler 的机器上执行多页 DOCX 转 PDF/PNG 视觉回归，把当前 Quick Look 首页抽查升级为完整页验收。
- [ ] 对远程 Skill pack 的版本固定、签名/完整性策略和更新提示补充发布策略与集成测试。
- [ ] 将本页的发布验证命令接入可公开复跑的 CI 报告，避免文档手写测试数字再次漂移。

## 人工测试清单

以下用例无法由当前受限沙箱充分证明，建议协作者按实际环境执行并记录结果、系统版本、命令和截图/日志。

| 优先级 | 用例 | 操作与验收标准 |
|---|---|---|
| P0 | 全量回归 | 在允许绑定 localhost 的 Python 3.12 环境执行 `uv run --python 3.12 --with pytest python -m pytest -q`；目标是无错误，若失败附完整 traceback |
| P0 | DOCX 三线表与分页 | 运行 `scripts/build_three_line_table_fixture.py` 与 `scripts/verify_docx.py`，用 Word/LibreOffice 打开；检查无边框残留、表头/正文不重叠、不跨页断行、脚注真实可见 |
| P0 | 使用白皮书 | 新白皮书生成后，从安装到 `chat`、`run`、Skill/MCP 示例逐条实操；所有命令、链接、截图必须与 v0.23.0 一致 |
| P1 | Claude Code/Codex/cc-switch | 每种宿主分别放入一个项目级 Skill 和 MCP；确认可发现但项目 MCP 未信任时不可执行，信任后仅 stdio MCP 可注册 |
| P1 | Skill 包更新 | 在干净目录分别安装五个领域包，重复执行更新；确认状态可见、启停生效、core 不可误停、网络失败不破坏已安装内容 |
| P1 | 重名/插件识别 | 制造同名 Skill 的项目级、全局和插件副本；确认默认不静默选错，可通过 duplicate/source preference 审计或决策 |
| P1 | WebBridge/受限全文 | 在已登录机构账号的真实浏览器验证打开、授权、抓取、PDF 魔数检查与落盘；不得绕过付费墙或读取凭据 |
| P2 | Agent 端到端 | 以真实研究目录执行资料编译、Skill 检索、分析委托、DOCX 导出和质量 gate；验证每个写盘/外部动作均出现审批与可追溯产物 |

## 协作约定

- 报告测试结果时必须写明命令、Python/OS、是否联网、是否可绑定 localhost；“通过”不可替代原始输出。
- 不将外部 Skill 的“发现”描述为“启用”或“已验证”；非 core Skill 必须安装领域包或显式启用。
- 不将自动 gate 视为方法学或伦理审查的替代品；预注册、剔除、因果解释和投稿版本仍由研究者负责。
- 任何更新白皮书/预印本的数字，都应先更新可复跑证据，再更新 Markdown，最后生成 DOCX/PDF。
