# Changelog

## 0.29.14 - 2026-09-07

- Republish as 0.29.14 after npm staged 0.29.13 without making it publicly available (E409)
- Same changes as 0.29.13: human verify gate, Windows update repair, academic skill catalog, Computer Use MCP

## 0.29.13 - 2026-09-07

- analysis/academic: AI /crosscheck then mandatory human Panel verify before handoff/finalize
- Windows update verifies global install and repairs stale ENOTEMPTY installs
- Trim recommended catalog: academic-only, no author branding; Mac Computer Use skill + Computer Use MCP
- Help/Panel copy and verify checklist statuses (ai-checked vs human verified)
- Pin website/docs install examples to 0.29.13

## 0.29.12 - 2026-09-07

- Replace default Pi coding-agent identity with PsyClaw via --system-prompt
- Add launch-only psyclaw --continuously-work with red token/quality warning (not Shift+Tab)
- Remove dead Panel pause/resume and /api/artifact/save handlers
- Scrub CLAUDE.md and 开工纪要 to 0.29; mark 会话复盘 /run notes obsolete; drop empty CHANGELOG Unreleased stubs
- Pin website/docs install examples to 0.29.12; refresh stale command/verify contract tests
- Ignore local Python v0.23 remnants (.venv, egg-info, dist2, psyclaw-*.tgz)

## 0.29.11 - 2026-09-07

- Fix ERR_UNSUPPORTED_ESM_URL_SCHEME on Windows by passing file:// to node --import and startup import
- Harden network-routing URL/createRequire bases for Windows paths
- Identity prompt: refuse dumping system prompt / pi harness / internal skill catalogs

## 0.29.10 - 2026-09-07

- Sync CLI assistant replies to Panel via SSE (/api/assistant/stream)
- Add psyclaw_wake_options (唤醒选项): Panel modal + CLI renderer; checklist can sync verify marks
- Allow Panel POST /api/crosscheck and /api/wake-options/respond

## 0.29.9 - 2026-09-07

- Emphasize ARS/Nature/compose/analysis-plan/grill are bundled: never ask the user to install them
- Use natural-language soft-route in chat/analysis/academic (or explicit /skill) instead of install conversations
- Update /help notes and Nature missing-filler messaging

## 0.29.8 - 2026-09-07

- Rename distillation skills to distill-scholar and distill-journal; repo https://github.com/Exekiel179/distill-skills
- Drop incorrect still-* naming (distill is the English for 蒸馏)

## 0.29.7 - 2026-09-07

- Rename recommended distillation skills to English ids distill-scholar and distill-journal (drop still-学者 / still-期刊 mixed names)
- Point docs and catalog at https://github.com/Exekiel179/distill-skills distill-scholar / distill-journal

## 0.29.6 - 2026-09-07

- Remove bundled huashu-nuwa; scholar/journal distillation moves to recommended distill-scholar and distill-journal at https://github.com/Exekiel179/distill-skills
- distill-journal requires ≥3 local full texts (recommend 8–12)
- Update help, scholars README, and perspective skills to point at Still

## 0.29.5 - 2026-09-07

- /help opens Panel「使用速览」; simplify help copy and note bundled scholar/journal distillation
- Expand huashu-nuwa for scholar lenses and journal/style skills
- Mainland built-ins: PSYCLAW_CN/npmmirror GitHub mirrors for fd/rg (raw/codeload), CN-aware update/check-updates, mirrored recommended skill git clone

## 0.29.4 - 2026-09-07

- Fix Thinking cycle shortcut to Ctrl+Shift+T (modes stay Shift+Tab)
- /help prints three-mode whitepaper snippet and common commands
- Soft confirm before stats/writing when project was never /init
- Analysis plan UX: NL confirm, /plan auto with 未经人审批 disclosure, per-analysis choices
- /crosscheck (alias /verify) model-driven checklist; Panel checklist + full-page chat
- Bundle huashu-nuwa (女娲) plus kahneman/gelman/freud-perspective; other Huashu flagships including huashu-mac-use in recommended catalog

## 0.29.3 - 2026-09-06

- Fix CLI footer duplicate academic pill and align chat/analysis/academic in single row
- Update startup banner pipeline, protocol, and mode switch hints to match ARS social science workflow
- Integrate CLI interactions to Web Panel: 5-step research pipeline stepper, topbar quick actions, init project modal, and interactive web console drawer

## 0.29.2 - 2026-09-07

- Add analysis-mode stats soft-takeover via core skill `analysis-plan`, durable plans under `analysis/plans/`, and `/plan` (new/status/confirm/review/run/defer/handoff). Default execution is local reproducible scripts; MCP only for special backends or explicit request. Bridge to academic via `analysis/HANDOFF.md` without merging ARS planning.
- Remove the `/run` command. After `/init`, analysis/academic modes and tools use the project itself as the active research context; soft `/verify` gates remain.
- Remove `/brief`, `psyclaw brief`, and the offline `research-brief` skill/path. Evidence-sufficiency evals now call gates directly.
- Academic mode soft-routes only the bundled ARS / Nature / compose skill allowlist from natural language; other skills still require explicit `/skill:<name>`.
- Add `pnpm eval:academic-route` intent suite (per-skill × difficulty, multi-skill, negatives) with primary precision/recall/F1, set recall@k, and negative precision; multi-intent primary follows earliest cue order.

## 0.29.1 - 2026-09-06

- Bump package governance apiVersion to 0.29 so branding checks pass for the 0.29 line.

## 0.29.0 - 2026-09-06

- Shift+Tab cycles three sticky modes: chat → analysis → academic (Ctrl+Shift+Tab keeps thinking).
- `/init` only scaffolds a clean shared workspace (`data/raw|clean`, `analysis/`, `literature/`, `paper/`, root `psyclaw.md`, `.psyclaw/`); no auto grill.
- Soft research pipeline: clarify → review → plan → analyze → report → academic/ARS reviews; prioritize runnable results, then AI field checks + human `/verify`.
- Fingerprints protect raw-data tampering only; they are not academic “verified” proof.
- Analysis and academic share one repo via `analysis/HANDOFF.md`; ARS multi-agent and on-demand PDF engine remain available.

## 0.28.3 - 2026-09-06

- Keep Shift+Tab for sticky academic mode; move Pi thinking-level cycle to Ctrl+Shift+Tab via agent keybindings.json (custom bindings preserved).

## 0.28.2 - 2026-09-06

- Enter ARS conversation mode with ars + Tab (ars: prefix and tinted editor); bare /ars no longer shows the profile popup.
- Bundle Nature gap-fill skills (nature-figure, nature-ref-verifier, nature-polishing) and academic-paper-strategist/composer in the npm package.

## 0.28.1 - 2026-09-06

- Add Claude-style Subagent browsing via /agents and Panel, with eight bundled literature/review workers.
- Make psyclaw update print a compact before→after success summary by default; use --detail for the JSON receipt.
- Allow Subagent write/network/destructive effects only after interactive confirmation at create and each /agents run.

## 0.28.0 - 2026-09-06

- Add preview-and-confirm `/create-skill`, `/create-hook`, `/create-rule`, and `/create-subagent` commands with project-local schemas, no-clobber writes, hashes, and audit receipts.
- Extend `/agents` to run up to four selected project-defined read-only personas in isolated Pi RPC workers.
- Add a narrow ARS review bridge: fixed five-seat, two-phase Stage 3 review with deterministic validation and provenance, plus ordered three-gate Stage 3′ re-review without false parallelism claims.
- Remove the user-facing `/install` slash command; install through `/skill`, `/plugin`, `/mcp`, or `/panel`.
- Add `pnpm test:ars` as the ARS-path minimal acceptance suite.
- Bundle official Windows x64/arm64 `ripgrep` 15.2.0 and `fd` 10.5.0 executables in the npm package, and expose them to Pi through `PATH` so Windows startup performs no tool download.
- Hide Pi's detailed local Skills, Extensions, and Themes inventory by default; `ctrl+o` still expands it when needed.
- Point the ARS recommendation to the original `Imbad0202/academic-research-skills` repository; during an active ARS run, gap-fill only with loaded Nature fillers when present.

## 0.27.23 - 2026-09-04

- Align panel manuscript/document management with the read-only workbench contract: write routes answer 405 and the panel never mutates project files.
- Harden the /panel workbench launcher: surface real startup failures and fall back to a manual URL when the browser cannot be opened automatically.
- Replace user-facing instructions to install via Pi internals with system-managed install wording in recommendation, plugin and panel flows.
- Gate /run behind /init: compliant analysis documents alone no longer auto-bootstrap a controlled project.
- Route /install recommendation surface to system-managed installation and drop the removed /export command from the registered command set.

## 0.27.22 - 2026-09-04

- Keep proxy users on GitHub's official API and Release URLs while routing mainland-registry users exclusively through mainland GitHub mirrors.
- Retry managed `ripgrep` and `fd` downloads through a second mainland mirror when the primary mirror fails or returns an HTML error page.
- Preserve Pi's native platform selection, version discovery, extraction, and installation behavior.

## 0.27.21 - 2026-09-04

- Restore Pi's official `ripgrep` and `fd` installation rules instead of disabling managed downloads.
- Route official GitHub downloads through configured proxies, or route both GitHub API and Release requests through one mirror when a mainland npm registry is configured.

## 0.27.20 - 2026-09-04

- Stop Pi's optional `ripgrep` and `fd` GitHub downloads at the managed-tool boundary while continuing to use binaries already available on `PATH`.
- Fall back silently to PsyClaw's built-in cross-platform Node search tools when those optional binaries are unavailable.

## 0.27.19 - 2026-09-04

- Add `psyclaw --continue` and `psyclaw -c` to resume the latest session for the current project through the bundled Pi runtime.
- Use built-in cross-platform file search fallbacks so Windows startup no longer depends on downloading ripgrep and fd from GitHub Releases.

## 0.27.18 - 2026-09-03

- Fix the remaining Node 22 type compatibility issue in research-decision lookup.
- Include all runtime isolation, workflow, ecosystem, Panel, and interaction updates from the preceding unpublished candidates.

## 0.27.17 - 2026-09-03

- Fix Node 22 compatibility in controlled-run authorization and research-decision event lookup.
- Include the runtime isolation, research workflow, Plugin, MarkItDown, MCP, Panel, and interaction updates prepared in 0.27.16.

## 0.27.16 - 2026-09-03

- Isolate bundled runtime configuration under ~/.psyclaw and streamline first-launch provider setup.
- Limit researcher decision prompts to substantive methodological trade-offs while improving guided research initialization and review.
- Add Plugin, MarkItDown, and MCP ecosystem integration plus Panel and command interaction fixes.

## 0.27.15 - 2026-09-02

- Added Plugin recommendations for ARS Academic Research Suite, Nature Skills, Psych Network CSS, and Pingouin.
- Added a repeatable GitHub-based release push workflow.

## 0.27.14 - 2026-09-02

- Added verified recommendations for Wang Fei's journal frontier, statistical forensics, and psychological network analysis projects.

## 0.27.13 - 2026-09-01

- Added the native OpenCode Go subscription provider and its bundled model choices.
- Provider switching now always presents the credential screen; blank input reuses an existing credential and missing credentials are reported explicitly.

## 0.27.12 - 2026-09-01

- Expanded analysis hooks across planning, input validation, delegation, writes, results, reporting, and citation completion.
- Exposed the read-only `/agents` command to regular users while keeping destructive developer commands gated.
- Narrowed Panel mutation routes to Provider and Skill/MCP ecosystem management; project files, evidence, manuscripts, artifacts, and run facts remain read-only.
- Synchronized project, architecture, hook, and whitepaper documentation with the current implementation status.

## 0.27.8 - 2026-08-31

- Renamed the `/skills` manager to `/skill` and removed the old `/skill <name>` forwarding behavior; loaded Skills remain callable through `/skill:<name>`.
- Connected `/plugin list|install|remove` to Pi's package/extension manager with confirmation before changes.
- Moved new projects' immutable original-data location to `.psyclaw/data/raw`; legacy `data/raw` remains protected for compatibility.

## 0.27.7 - 2026-08-31

- Fixed Windows, `~`, relative, and environment-provided Skill path resolution; nonexistent paths are no longer passed to the Pi resource loader.
- Added deterministic same-name Skill selection across project and user Agent directories, with duplicate counts available in `/skill` instead of harmless startup conflicts.
- Loaded Claude command Markdown as individual prompt commands rather than one conflicting `commands` Skill.
- Hid automatically resolved Skill collisions and stale missing paths at startup; remaining long Skill diagnostics are collapsed and can be expanded with `Ctrl+O`.
- Expanded `/skill` and `/mcp` management, per-run Skill selection, Export output, and local MCP discovery included in this release line.

## 0.27.6 - 2026-08-30

- Added a live stdio MCP bridge so enabled project/user MCP configurations are discoverable and callable by the active model; existing MNE MCP configurations no longer stop at installation state.
- Added `/skill <name> [task]` and loaded local Claude, Codex, and shared Agents Skill directories alongside PsyClaw Skills; Pi's native `/skill:<name>` remains available.
- Kept Skill and MCP discovery reloadable through `/reload` without copying or forking Pi's resource runtime.

## 0.27.5 - 2026-08-30

- Added `/run` as the explicit controlled research workflow entry after `/init`; ordinary conversations remain unintrusive.
- Staged academic delivery from analysis report through optional literature research, manuscript writing, `/review`, and final DOCX export.
- Added lawful open-access PDF archiving under `literature/pdfs/`, DOI fallback links for paywalled sources, and a final citation full-text gate.
- Removed automatic `artifacts/` project scaffolding and SmartPlot integration; simplified Panel to project files/Trace, Skill/MCP, and Provider/cost views.

## 0.27.4 - 2026-08-30

- 修正 GitHub Actions 中 npm tarball 的相对路径，避免 npm 将发布产物误解析为 Git 仓库地址。
- 0.27.3 已通过三平台构建与打包，但因上述路径解析错误未上传 npm。

## 0.27.3 - 2026-08-30

- 发布任务不再重复运行离线评测；三平台安装器语法、品牌检查、类型检查和构建通过后直接打包并发布 npm。
- 0.27.2 的三平台构建均通过，但发布前的实时 `/panel` 评测为 30/31，因未产生 notify 事件而停止，未上传 npm。

## 0.27.2 - 2026-08-30

- 修复扩展在不提供事件订阅 API 的兼容宿主中初始化失败的问题，并同步 `/trace` 命令契约。
- Release 工作流改为以三平台安装器语法、品牌检查、类型检查和构建作为发布门禁；完整测试套件不再阻断用户要求的快速补丁发布。
- npm 发布接入 Trusted Publishing，通过 GitHub Actions OIDC 自动认证，无需每次手工输入两步验证码。

## 0.27.1 - 2026-08-30

- 推荐 Skill 安装改由当前模型根据来源网址检查并执行，不再要求推荐目录预先提供固定安装命令。
- 安装前由用户选择项目目录或系统目录；项目目录仅供当前项目使用，系统目录可供所有 PsyClaw 项目使用。
- `/skills` 与科研面板统一显示安装位置、安装状态及 `/reload` 提示，安装完成后可明确启用并重新加载。
- MarkItDown 归入外部工具，不再伪装为可安装 Skill；清理并补充能够由模型从有效来源处理的推荐 Skill。

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

- 旧版科研工作台的完整能力、面板、动态启动横幅、推荐 Skill/MCP 生态与研究工作流迁入本仓库，作为 PsyClaw 的正式后续版本。
- 对外产品名、可执行命令、项目状态目录、工具名、扩展和治理 schema 统一为 `PsyClaw` / `psyclaw` / `.psyclaw`。
- 保留既有 Pi 配置 profile 兼容性，因此已有模型、主题、安装包和生态 Skill 不需要重新配置；旧仓库仅作为历史代码参考，不再是运行时依赖。

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
