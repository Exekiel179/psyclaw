# PsyClaw

PsyClaw 是面向社会科学研究的 Pi 工作台。它把研究项目、证据来源、Claim-Evidence 账本、完整性门禁、人工裁决、可恢复工作流和本地面板接到官方 Pi runtime 上；它不替代统计软件，也不会把未经核验的引用、结果或审稿意见写成事实。

当前版本：`0.26.3`。本仓库以 `psypi v0.4.1` 的完整工作台为功能基线完成改名；`psypi` 仓库保留为历史仓库，正式命令和后续发布均使用 `psyclaw`。

## 安装

需要 Node.js `>=22.19.0`。官方 npm 源：

```powershell
npm install -g psyclaw@0.26.3
```

中国大陆网络较慢或无法访问官方源时：

```powershell
npm install -g psyclaw@0.26.3 --registry=https://registry.npmmirror.com
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
| 查看 Pi runtime 更新 | `psyclaw check-updates` |
| 更新 Pi runtime | `psyclaw update --yes` |
| 打开科研面板 | 在对话中输入 `/panel` |
| 查看或切换 Provider | 在对话中输入 `/provider` 或 `/provider <id>` |
| 管理启动横幅宠物 | `/pet status`、`/pet on`、`/pet off`（默认关闭） |

`psyclaw update` 只更新捆绑的 Pi runtime；它不是从 Git 拉取 PsyClaw 源码。全局安装用户通过 `npm install -g psyclaw@<version>` 获取 PsyClaw 新版本；本仓库开发者直接修改源码并构建。

## 开发者本地安装

```powershell
pnpm install
pnpm build
npm link
psyclaw --help
```

开发阶段不需要执行 `psyclaw update`。它会更新 Pi 依赖，不会同步本仓库代码。

## 从旧 Python 版迁移

如果启动时出现 `ModuleNotFoundError: No module named 'psyclaw.cli'`，终端仍解析到旧 Python 安装的 `psyclaw.exe`，而不是 npm 版本。先检查命令顺序：

```powershell
Get-Command psyclaw -All
where.exe psyclaw
```

保留 npm 的 `psyclaw.cmd`，移除或下调旧 Python 入口所在目录后重新打开终端，再安装当前版本：

```powershell
npm uninstall -g psyclaw
npm install -g psyclaw@0.26.3
psyclaw --help
```

Python 的卸载器提示 `No files were found to uninstall` 时，不要手工删除不明目录；先用上述命令定位旧入口，再在对应 Python 环境中修复或移除它。

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
