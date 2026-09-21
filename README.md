# PsyClaw

面向社会科学研究的智能体工作台：把研究项目、证据账本、完整性门禁、可恢复工作流和本地面板接到内置运行时上。它不替代统计软件，也不会把未经核验的引用、结果或审稿意见写成事实。

当前版本：`0.30.8` · 命令与用户目录：`psyclaw` / `~/.psyclaw` · 许可证：MIT
内置 Academic Research Skills（`vendor/ars`）遵循上游 CC BY-NC 4.0，仅限非商业用途。

## 安装

需要 Node.js `>=22.19.0`。

```bash
npm install -g psyclaw@0.30.8
```

中国大陆可用镜像或安装脚本：

```bash
npm install -g psyclaw@0.30.8 --registry=https://registry.npmmirror.com
# 或
PSYCLAW_CN=1 curl -fsSL https://exekiel179.github.io/psyclaw/install.sh | sh
```

```powershell
# Windows
irm https://exekiel179.github.io/psyclaw/install.ps1 | iex
```

确认入口：

```bash
psyclaw --help
```

直接运行 `psyclaw` 会启动交互工作台；首次无模型配置时会进入配置流程。API Key 只写入用户级 `~/.psyclaw/agent/auth.json`，不要写进命令参数、项目或 Git 仓库。

## 五分钟开始

```bash
mkdir my-study && cd my-study
psyclaw init "社交支持与研究生心理健康的关系" --paradigm survey-observational
psyclaw
```

初始化会创建 `.psyclaw/data/raw/`（只读保护区）、`data/clean/`、`literature/pdfs/`、`notes/`、`outputs/`。对话中也可用 `/init <研究目标>`；用 `Shift+Tab` 在 `chat` → `analysis` → `academic` 间切换。未 `/init` 时保持普通对话，不强制研究门禁。

```bash
psyclaw evidence add notes/source.md --level user
```

## 常用命令

| 需求 | 命令 |
| --- | --- |
| 启动 / 续接会话 | `psyclaw` · `psyclaw -c` |
| 初始化项目 | `psyclaw init <goal> --paradigm <profile>` 或 `/init` |
| 登记证据 | `psyclaw evidence add <path> --level user\|fulltext` |
| 更新 | `psyclaw check-updates` · `psyclaw update` |
| 科研面板 | 对话中 `/panel` |
| 模式切换 | `Shift+Tab`（chat / analysis / academic） |
| 学术 ARS | `/ars` · `/ars <任务>` · `/ars doctor` |
| Skill / Plugin / MCP | `/skill` · `/plugin` · `/mcp` |
| 遥测 | `psyclaw telemetry off\|on\|status`（默认开启，可关） |

更多对话命令见 `psyclaw --help` 与 [使用白皮书](docs/使用白皮书.md)。

## 文档

**研究者**

- [使用白皮书](docs/使用白皮书.md)（正文：[v0.30.1](docs/PsyClaw使用白皮书_v0.30.1.md)）
- [PsyClaw ARS 模式](docs/PsyClaw-ARS模式.md)
- [遥测说明](docs/telemetry.md)
- [文档与产物目录规范](docs/文档规范.md) · [产物目录规范](docs/产物目录规范.md)

**贡献者**（实现契约，非日常使用说明）

- [开工纪要](docs/开工纪要.md) · [架构蓝图](docs/架构蓝图.md) · [评测框架](docs/评测框架.md)
- [技能与生态准入清单](docs/技能与生态准入清单.md) · [威胁模型](docs/威胁模型.md)
- [AGENTS.md](AGENTS.md)

## 边界

- 复用官方 Pi runtime，不维护 fork。
- 统计计算委托 Python/R、SPSS/Stata/Mplus 或受信任 MCP；须保存脚本、输入指纹与环境信息。
- Skill / Plugin / MCP 默认只发现、不执行；启用前核对来源与信任状态。
- 无证据的事实性 Claim 须标为 `uncertain` 或阻断；无 receipt / 审批的副作用不算完成。

## 从源码开发

```bash
pnpm install && pnpm build && npm link
psyclaw --help
```

源码树中请用 Git 同步，不要跑 `psyclaw update`（会拒绝覆盖本地修改）。

发布（维护者）：

```bash
RELEASE_MESSAGE="release: describe the change" pnpm release:push
```

标签推送后由 GitHub Actions（Node 22 + Trusted Publishing）发布 npm。

## 迁移与卸载

若出现 `ModuleNotFoundError: No module named 'psyclaw.cli'`，说明仍指向旧 Python 入口。用 `Get-Command psyclaw -All` / `which -a psyclaw` 定位后移除旧入口，再安装当前 npm 包：

```bash
npm uninstall -g psyclaw
npm install -g psyclaw@0.30.8
```

仅卸载程序：`npm uninstall -g psyclaw`  
同时清除用户配置与会话：再删除 `~/.psyclaw`（不会删除研究项目目录）。
