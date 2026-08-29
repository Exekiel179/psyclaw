# PsyClaw

PsyClaw 是面向社会科学研究的 Pi 工作台。它把研究项目、证据来源、Claim-Evidence 账本、完整性门禁、人工裁决、可恢复工作流和本地面板接到官方 Pi runtime 上；它不替代统计软件，也不会把未经核验的引用、结果或审稿意见写成事实。

当前版本：`0.27.4`。本仓库以 `psypi v0.4.1` 的完整工作台为功能基线完成改名；`psypi` 仓库保留为历史仓库，正式命令和后续发布均使用 `psyclaw`。

## 安装

需要 Node.js `>=22.19.0`。官方 npm 源：

```powershell
npm install -g psyclaw@0.27.4
```

中国大陆网络较慢或无法访问官方源时：

```powershell
npm install -g psyclaw@0.27.4 --registry=https://registry.npmmirror.com
```

确认命令入口：

```powershell
psyclaw --help
```

直接运行 `psyclaw` 会启动交互研究工作台；首次没有模型配置时会进入配置向导。向导会检查当前进程、macOS `launchctl` 和已有用户凭据，也允许直接遮罩输入 Key。`launchctl` Key 只注入当前运行进程、不落盘；登录 shell 仅在用户明确按 `Ctrl+I` 后读取。直接输入或明确导入的 Key 只保存到 Pi 用户级 `auth.json`，不会写入项目或 `models.json`。也可显式运行 `psyclaw wizard`，或使用 `psyclaw setup --provider deepseek` 写入仅引用环境变量的预设。不要把 API key 写进命令参数、项目、README 或 Git 仓库。

## 五分钟开始

在新的研究目录中建立项目：

```powershell
mkdir my-study
cd my-study
psyclaw init "社交支持与研究生心理健康的关系" --paradigm survey-observational
psyclaw
```

初始化会建立 `.psyclaw/`、`data/raw/`、`data/clean/`、`notes/` 和 `outputs/`。`data/raw/` 是只读保护区；把经确认可用于分析的派生数据放在 `data/clean/`。

登记本地材料并生成离线证据简报：

```powershell
psyclaw evidence add notes\source.md --level user
psyclaw brief
```

## 常用入口

| 需求 | 命令或操作 |
| --- | --- |
| 启动研究对话 | `psyclaw` 或 `psyclaw chat` |
| 创建研究项目 | `psyclaw init <goal> --paradigm <profile>` |
| 登记本地证据 | `psyclaw evidence add <path> --level user\|fulltext` |
| 生成离线简报 | `psyclaw brief` |
| 创建人工裁决模板 | `psyclaw hitl init` |
| 写研究移交记录 | `psyclaw handoff` |
| 扫描本机其他 Agent | `psyclaw agents` |
| 查看 PsyClaw 和内置 Pi 更新 | `psyclaw check-updates` |
| 更新 PsyClaw 和内置 Pi | `psyclaw update` |
| 导出脱敏使用路径 | 在对话中输入 `/trace` |
| 打开科研面板 | 在对话中输入 `/panel` |
| 查看或切换 Provider | 在对话中输入 `/provider` 或 `/provider <id>` |
| 管理启动横幅宠物 | `/pet status`、`/pet on`、`/pet off`（默认关闭） |

`psyclaw update` 会更新 PsyClaw 整包，并同时安装该版本锁定、验证过的内置 Pi；它不会更新或删除系统中单独安装的 `pi` 命令。在源码仓库中运行时，命令会停止并提示通过 Git 更新，不会覆盖本地修改。
仅查看更新计划而不执行时，使用 `psyclaw update --check`。旧的 `--yes` 参数仍兼容，但不再需要。

### 导出使用路径

```bash
/trace
```

该斜杠命令直接在 PsyClaw 对话界面中使用，从当前项目的工作流日志和对应 Pi 会话中生成 OTLP/HTTP JSON，用于通过 OpenTelemetry Collector 导入 Langfuse 或 LangSmith。导出器只保留步骤类型、父子关系、时间、结果状态和版本；不包含对话正文、工具参数/输出、研究内容、原始 ID 或绝对路径。命令只写本地文件，不会自动上传。终端兼容入口仍为 `psyclaw traces export`。

## 开发者本地安装

```powershell
pnpm install
pnpm build
npm link
psyclaw --help
```

开发阶段不需要执行 `psyclaw update`。请通过 Git 同步仓库，再运行 `pnpm install` 和 `pnpm build`。

## 从旧 Python 版迁移

如果启动时出现 `ModuleNotFoundError: No module named 'psyclaw.cli'`，终端仍解析到旧 Python 安装的 `psyclaw.exe`，而不是 npm 版本。先检查命令顺序：

```powershell
Get-Command psyclaw -All
where.exe psyclaw
```

保留 npm 的 `psyclaw.cmd`，移除或下调旧 Python 入口所在目录后重新打开终端，再安装当前版本：

```powershell
npm uninstall -g psyclaw
npm install -g psyclaw@0.27.4
psyclaw --help
```

Python 的卸载器提示 `No files were found to uninstall` 时，不要手工删除不明目录；先用上述命令定位旧入口，再在对应 Python 环境中修复或移除它。

## 卸载

仅卸载 PsyClaw 程序，保留用户配置和历史会话：

```bash
npm uninstall -g psyclaw
```

完全卸载 PsyClaw（同时删除模型配置、用户设置和历史会话）：

```bash
npm uninstall -g psyclaw
node -e 'const fs=require("node:fs"),os=require("node:os"),path=require("node:path");const target=path.join(os.homedir(),`.psy${"pi"}`);if(path.dirname(target)!==os.homedir())throw new Error("unsafe PsyClaw data path");fs.rmSync(target,{recursive:true,force:true});console.log(`removed ${target}`)'
```

上述命令不会删除研究项目目录，因为其中可能包含论文、证据、原始数据和分析产物。如需删除某个项目，应单独确认该项目的准确路径后处理。单独全局安装的 `@earendil-works/pi-coding-agent` 不属于 PsyClaw 用户数据，上述命令不会删除它。

## 文档

- [PsyClaw v0.26.0 使用白皮书](docs/PsyClaw使用白皮书_v0.26.0.md)
- [项目范围与里程碑](docs/开工纪要.md)
- [架构蓝图](docs/架构蓝图.md)
- [评测框架](docs/评测框架.md)
- [文档与交付物规范](docs/文档规范.md)

## 边界

- PsyClaw 复用官方 Pi 的 session、model、skill、package 和 extension runtime，不维护 fork。
- 统计计算委托 Python/R、SPSS/Stata/Mplus 或受信任 MCP；输出必须保存脚本、输入指纹和环境信息。
- Skill、Plugin 和 MCP 默认只发现、不执行；启用前需要来源、版本/ref、哈希、许可证和依赖状态。
- 没有可定位证据的事实性 Claim 必须是 `uncertain` 或被阻断；没有审批记录的副作用不能被当作完成。

许可证：MIT。
