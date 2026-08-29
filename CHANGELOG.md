# Changelog

## 0.27.2 - 2026-08-30

- 修复扩展在不提供事件订阅 API 的兼容宿主中初始化失败的问题，并同步 `/trace` 命令契约。
- Release 工作流改为以三平台安装器语法、品牌检查、类型检查和构建作为发布门禁；完整测试套件不再阻断用户要求的快速补丁发布。
- npm 发布接入 Trusted Publishing，通过 GitHub Actions OIDC 自动认证，无需每次手工输入两步验证码。

## 0.27.1 - 2026-08-30

- 推荐 Skill 安装改由当前模型根据来源网址检查并执行，不再要求推荐目录预先提供固定安装命令。
- 安装前由用户选择项目目录或系统目录；项目目录仅供当前项目使用，系统目录可供所有 PsyClaw 项目使用。
- `/skills` 与科研面板统一显示安装位置、安装状态及 `/reload` 提示，安装完成后可明确启用并重新加载。
- MarkItDown 和 SmartPlot 归入外部工具，不再伪装为可安装 Skill；清理并补充能够由模型从有效来源处理的推荐 Skill。

> 发布说明：该标签的三平台流水线因既有测试失败而停止，未发布到 npm；修正内容随 0.27.2 发布。

> npm 发布通过 GitHub Actions Trusted Publishing 使用短期 OIDC 凭据，不保存长期 npm Token；首次使用前需在 npm 包设置中将 `Exekiel179/psyclaw` 的 `release.yml` 配置为 Trusted Publisher。

## 0.27.0 - 2026-08-30

- `psyclaw update` 改为直接更新 PsyClaw 整包及其锁定的内置 Pi，默认执行更新；`--check` 仅查看计划，旧 `--yes` 参数继续兼容。
- 内置 Pi 升级至 0.84.4，隐藏启动时重复的 Pi 更新说明，同时保留显式 Changelog 查询能力。
- 新增 `/trace`，将脱敏后的研究使用路径导出为 OTLP/HTTP JSON，供 Langfuse、LangSmith 或 OpenTelemetry Collector 分析；不会自动上传内容。
- 推荐 Skill 启用状态现在会在下一次聊天启动时真正接入 Pi；同名核心 Skill 禁止静默覆盖，并要求显式选择来源。
- `/skills` 与 `/mcp` 改为单页键盘交互管理界面，集中显示启用状态、来源、版本、许可证、依赖、风险和阻断原因。
- 修复推荐 Skill 安装目录、许可证证据和嵌套 Git 元数据处理，并统一 `markitdown-bilibili` 的目录 ID 与 Skill 名称。
- 启动横幅优先显示完整 PsyClaw 字标；启用 `/pet` 后宠物改为独立显示，不再挤压主标识。

> 发布说明：本地按用户要求跳过测试；推送版本标签后由 GitHub Actions 执行 Node 22 跨平台检查、构建和离线评测，全部通过后才创建 GitHub prerelease。

## 0.26.3 - 2026-08-27

- 修复 macOS GUI/全局 npm 启动时的 Provider Key 识别：`launchctl` Key 仅注入当前进程；login shell Key 仅在用户明确选择导入后保存。
- 修复首次向导输入包含 `q` 的 API Key 时意外退出，并统一四步进度与完成提示。
- 横幅改用终端显示列宽计算 CJK/emoji，所有字模在窄终端下均完整回退；宠物继续默认关闭，仅通过 `/pet on` 启用。
- 明确 Google Gemini 配置与 `/provider` Provider 列表、切换管理入口。

## 0.26.2 - 2026-08-27

- 修复 macOS 从 Finder 或全局 npm 启动时无法识别登录 shell Provider 环境变量的问题，并在首次向导中安全迁移到用户级凭据存储。
- 首次向导支持遮罩输入 API Key，新增 Google Gemini Provider 预设。
- 新增 `/provider` 与 `/pet` 管理命令；宠物横幅默认关闭，仅显式启用后显示。
- 横幅按终端实际可见宽度筛选，修复 PsyClaw 标识在窄终端被截断的问题。
- 所有 PsyClaw 自定义斜杠命令补充简短说明。

## 0.26.1 - 2026-08-27

- 修复 npm 包清单中的错误模块入口元数据；PsyClaw 继续以 `dist/src/cli.js` 作为唯一命令入口。
- 发布包现在稳定包含 `dist/src/**` 与非空科研面板；构建遇到缺失或空面板时直接失败。
- `/panel` 运行时通知暴露实际 loopback URL，分模块评测直接核验该页面，不再扫描系统全部监听端口。

## 0.26.0 - 2026-08-24

- 发布新版使用白皮书、README 安装与首次使用说明，覆盖 npm/国内镜像安装、项目初始化、证据简报、面板、Skills/MCP、分析委托、升级与源码开发。
- 明确 `psyclaw update` 仅更新捆绑 Pi runtime；PsyClaw 本体通过 npm 安装升级，开发阶段通过源码构建更新。
- 将旧 Python 命令地图与教程标记为历史归档，避免用户误用已废弃的 Python 命令。

## 0.25.2 - 2026-08-24

- 修复横幅重写器在重复构建时追加同名 JavaScript 声明、导致 `psyclaw` 无法启动的问题；重写现在幂等，并可清理已重复写入的横幅块。

## 0.25.1 - 2026-08-24

- 修复较窄终端中 PsyClaw 五行横幅被固定宽度截断的问题；横幅现在保留完整字模，并在空间不足时将吉祥物移出并排布局。
- 修复科研面板助手把内部只读约束作为用户消息回显的问题；约束改为隔离 RPC 会话的系统提示，聊天记录只保留用户原话。

## 0.25.0 - 2026-08-24

- `psypi v0.4.1` 的完整科研工作台、面板、动态启动横幅、推荐 Skill/MCP 生态与研究工作流迁入本仓库，作为 PsyClaw 的正式后续版本。
- 对外产品名、可执行命令、项目状态目录、工具名、扩展和治理 schema 统一为 `PsyClaw` / `psyclaw` / `.psyclaw`。
- 保留既有 Pi 配置 profile 兼容性，因此已有模型、主题、安装包和生态 Skill 不需要重新配置；`psypi` 仓库作为历史代码库保留，不再是运行时依赖。

## 0.4.1 - 2026-08-17

- 修复：版本横幅动态读取 package.json（0.4.0 因硬编码常量显示 v0.3.2；npm 0.4.0 无法覆盖/撤包，故以 0.4.1 发布修正版，功能与 0.4.0 一致）。

## 0.4.0 - 2026-08-17

- 文档规范体系：统一 `paper/ docs/ literature/ data/ analysis/ outputs/ .psyclaw/` 目录约定，生成即落位（publish 工作流），panel 自动识别与导入（docx→md）。
- 手稿生产闭环：富格式渲染（三线表/列表/图片）、图片内嵌与 SVG 拖拽编辑、版本化发布（paper/archive + 版本账本，幂等）、引用用途账本（证据+引用原因）。
- 引用与核验体系：双源 DOI 核验（Crossref+OpenAlex）、参考文献存档（.psyclaw/references.jsonl）、正文引用核验、OA 全文下载（非 OA 诚实阻断）。
- 分模块使用效果测评 31/31 全绿（evals/modules.ts，含真实运行时 /panel 回归）；修复 receipt 落点与手稿发现顺序。
- 人民币计费显示（官方人民币价表 + 汇率回退 + 币种切换）。
- 三线表精确规范（顶/底 1.5 磅、表头下 0.5 磅）；产出质量清单（成本预告知、高级图表、摘要模板、NaN 清洗、工具调用纪律）。
- 全量测试 254 项通过；Node ≥22.19，Windows/macOS/Linux 兼容。

## 0.3.0 - 2026-08-15

- 完整接入科研工作台面板、运行状态、产物预览和 HITL 决策入口。
- 增加推荐 Skill/MCP 的来源、版本、许可证、依赖和安装预备信息。
- 增加分析安全 hooks：原始数据只读、输入哈希、结果可复现性、效应量和因果表述门禁。
- 支持项目级声明式用户分析 Hook，规则只能增加阻断或警告，不能关闭内置保护。
- 建立标准科研产物目录：`data`、`analysis`、`artifacts`、`outputs`。
- 分析方案和论文审阅支持 `v1`、`v2` 等项目内版本分配和可追溯记录。
- 增加可恢复的长程 Plan/Goal 工作流、暂停/恢复和结构化运行回执。
- 离线科研完整性 benchmark 通过 6/6，hard-fail 为 0。
## 0.3.2 - 2026-08-15

- 交互式学术手稿编辑器（WYSIWYG / Markdown 双模画布与段落实时渲染）。
- 实机证据探针与审查器（选词一键绑定 Claim、实时 DOI 校验与证据覆盖率计算）。
- 一键原生导出标准 Microsoft Word (`.doc`)（带 APA 7 规范排版与完整 References 参考文献表及 SHA-256 审计证书）。
- 命令行 CLI 启动界面全面重构升级：引入双线学术框架 Banner、核心四阶段流水线指引、高对比度快捷键栏与 Core/Ecosystem 技能分级高亮。
- 官网主页与工作台完成极简学术终端风格升级。

## 0.3.1 - 2026-08-15

- Complete literature retrieval verification and knowledge-map workflow outputs.
- Add multi-role expert review artifacts with HITL approval, receipts, and versioning.
- Add journal style profiles, reproducibility checks, and versioned figure/table/manuscript artifacts.
- Route these workflows through the natural-language psyclaw workbench tool.
- Build and test: 33 files, 184 tests passed.
