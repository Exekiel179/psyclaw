# PsyClaw

> v0.24.0 adopts the audited 0.4.1 predecessor Node/Pi baseline as an independent
> PsyClaw product. PsyClaw v0.23.0 remains intact in Git history, its
> `v0.23.0` tag, documentation, and existing release assets.

面向社会科学研究者的 Pi 科研智能体层。

正式版安装（Node.js >= 22.19）：

```text
npm install -g psyclaw@0.24.0 --registry https://registry.npmjs.org
psyclaw --help
```

PsyClaw 的目标不是再造一个重量级 Agent，而是在官方 Pi 之上提供少量、可审计、可组合的科研契约：研究项目状态、Claim-Evidence-Provenance 账本、完整性门禁、可恢复工作流、受控记忆和按需技能。统计计算交给成熟库或外接 MCP；Pi 的会话、模型、Skill、Package 和 TUI/RPC 能力继续由 Pi 提供。

当前仓库已完成第一条 M1/MVP-0 可运行切片，并落地 M2 的技能注册与受限多智能体编排基础、M3 的只读并行契约、真实 stdio MCP transport（argv/显式 env/超时隔离）、Skill 恶意正文 preflight、许可证/SBOM 门与 M4 的 literature-review/analysis-delegation/writing-review 三个 workflow 包。官方 Pi 的 `AgentSession`、`SessionManager`、`DefaultResourceLoader`、模型网关和严格 JSONL RPC 已由 adapter 接入；完成项目级 package 安装后提供原生只读 `/agents` 多智能体入口，面板扩展可选安装。联网检索、统计计算和并行写入仍按规划后置。先阅读：

- [开工纪要](docs/开工纪要.md)
- [架构蓝图](docs/架构蓝图.md)
- [多智能体开发与运行框架](docs/多智能体开发与运行框架.md)
- [评测框架](docs/评测框架.md)
- [技能与生态准入清单](docs/技能与生态准入清单.md)
- [威胁模型](docs/威胁模型.md)

代号：`psyclaw`。当前可用命令：

```text
pnpm install
pnpm check:branding            # 发布前阻断活动产品面中的旧品牌残留
pnpm build
pnpm exec pi install -l .       # 一次性把 psyclaw 作为项目级 Pi package 启用
pnpm exec pi --approve           # 运行 Pi 时信任已审查的项目 package
node dist/src/cli.js init "研究问题" --paradigm survey-observational
node dist/src/cli.js evidence add notes/source.md --level user
node dist/src/cli.js brief
node dist/src/cli.js chat              # 以自然语言启动文献、分析或写作工作流
node dist/src/cli.js agents
node dist/src/cli.js install claude-code --yes  # 当前 agent 全局命令仍为 discover-only
node dist/src/cli.js import claude-code --yes
node dist/src/cli.js shell
/skills                         # 查看推荐 Skill 的启用状态
/skills enable <skill-id>       # 启用项目级 Skill
/skills disable <skill-id>      # 禁用项目级 Skill
/mcp                            # 查看推荐 MCP 的启用状态
/mcp enable <mcp-id>            # 启用项目级 MCP
/mcp disable <mcp-id>           # 禁用项目级 MCP
/install skill|mcp <id>         # 生成安装预检计划
pnpm exec pi --extension ./dist/src/extension.js --approve  # 未安装 package 时的临时入口
pi --extension ./dist/src/panel/extension.js                # 可选：在 Pi 中启停 /panel
```

在 `pi-workbench` 中使用时，先在研究项目根目录安装 psyclaw package：

```text
pi install -l F:\Projects\psyclaw
pi-workbench
```

workbench 启动的每个 Pi 会话都会加载 psyclaw 的 `/research`、`/brief`、`/agents` 和 `/panel` 命令。在 Pi 中执行 `/panel` 后，用浏览器打开提示的 `http://127.0.0.1:8787` 地址即可查看当前项目的只读运行状态。

`brief` 与 `workflow` 在证据门禁失败时退出码为 `2`，并保留 manifest 与 HANDOFF，不生成貌似完成的正文。`serve` 启动本机面板：运行事实、Agent/Skill 和模型目录为只读；模型配置表单是唯一明确的本地写入入口，会将 provider 元数据写入 Pi `models.json`，API key 交给 Pi `auth.json` 管理。

内置 agent 下载器/安装器：`agents`/`scan` 只读识别本机其他智能体（Claude Code、OpenAI Codex、Gemini CLI、opencode、Aider、Cursor、Windsurf、Continue、Orca、Copilot CLI）的配置与技能目录，绝不读取凭据内容；安装计划必须有来源、版本、artifact SHA、许可证/依赖审计和 SBOM，缺任何一项都会 `blocked`。当前 agent catalog 只有全局 npm/pipx 命令，尚未绑定可验证 staging artifact，因此即使人工确认也保持 `agent-staging-required`，不会执行全局安装；`import <id> --yes` 将其他 agent 的允许 Skill 文件以来源/SHA-256 溯源导入 `.psyclaw/imports/`；`shell` 启动 ink 交互式表格 TUI（↑/↓ 选择、`i` 安装、`m` 导入、`r` 重扫、`q` 退出）。

Pi 集成分两层：完成一次 `pi install -l .` 后，项目级 package 默认加载 `src/extension.ts`，注册研究命令和原生只读 `/agents`；未安装时可用上面的 `--extension` 临时入口。worker 通过独立 Pi RPC 子进程、`read/grep/find/ls` 工具和结构化 WorkerReport 回传，但进程边界仍不是 OS sandbox。`src/panel/extension.ts` 是可选扩展，使用 `/panel [--port 8787]` 启停仅绑定 `127.0.0.1` 的只读可视化界面。面板的 Agents/Skills 下载页只展示发现结果、来源、版本、许可证、SHA、风险和审批前计划；模型页读取 Pi 本地模型注册表，并在没有对应注册项时显示 psyclaw 的 DeepSeek 模板元数据。页面只显示环境变量名称，不接收或显示 API key；`configured` 只表示环境变量存在，不代表实际认证成功。模型适配沿用 Pi `models.json`/`registerProvider` 契约，DeepSeek helper 只输出 `$DEEPSEEK_API_KEY` 引用。
