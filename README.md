# PsyClaw

PsyClaw 是面向社会科学研究的智能体工作台。它把研究项目、证据来源、Claim-Evidence 账本、完整性门禁、可恢复工作流和本地面板接到内置运行时上；只有无法由证据和通行方法消解、且会实质改变研究设计或解释的分歧才交由研究者取舍。它不替代统计软件，也不会把未经核验的引用、结果或审稿意见写成事实。

PsyClaw 自有代码使用 MIT 许可证；随 npm 包内置的 Academic Research Skills 位于 `vendor/ars`，保持上游署名并单独遵循 CC BY-NC 4.0，仅限非商业用途。

当前版本：`0.29.4`。正式命令、用户配置目录和后续发布统一使用 `psyclaw`。

## 发布流程

发布只提交已跟踪文件，并自动递增 patch 版本、创建版本标签，推送当前分支和标签；`.DS_Store`、论文附件、图形和其他未跟踪生成物不会被加入。GitHub Actions 随标签推送执行 Node 22 检查并发布 npm：

```bash
RELEASE_MESSAGE="release: describe the change" pnpm release:push
```

运行前请确认当前分支、工作区变更和 GitHub 权限。NPM 发布由 GitHub Actions 的 Trusted Publishing 完成，本机不需要 `npm login`。

## 安装

需要 Node.js `>=22.19.0`。官方 npm 源：

```powershell
npm install -g psyclaw@0.29.4
```

如果本机 npm 配置把 registry 误写成带有 `~/` 的地址，请显式指定官方源：

```bash
npm install -g psyclaw@0.29.4 --registry=https://registry.npmjs.org/
```

中国大陆网络较慢或无法访问官方源时：

```powershell
npm install -g psyclaw@0.29.4 --registry=https://registry.npmmirror.com
```

PsyClaw 的 npm 发布包直接携带 Windows x64/arm64 版 `ripgrep` 和 `fd`，Windows 启动时直接使用包内可执行文件，不再联网下载。其他平台缺少这两个工具时仍由锁定的 Pi 原生工具管理器处理：代理环境走 GitHub 官方 API 与 Release，国内 npm registry 环境统一走国内镜像。

确认命令入口：

```powershell
psyclaw --help
```

直接运行 `psyclaw` 会启动交互研究工作台；首次没有模型配置时会自动进入配置流程。配置界面会检查当前进程、macOS `launchctl` 和已有用户凭据，也允许直接遮罩输入 Key。`launchctl` Key 只注入当前运行进程、不落盘；登录 shell 仅在用户明确按 `Ctrl+I` 后读取。直接输入或明确导入的 Key 只保存到 PsyClaw 用户级 `auth.json`，不会写入项目或 `models.json`。模型、凭据、会话和宿主资源统一保存在 `~/.psyclaw/agent`，PsyClaw 不创建或使用 `~/.pi`。不要把 API key 写进命令参数、项目、README 或 Git 仓库。

## 五分钟开始

在新的研究目录中建立项目：

```powershell
mkdir my-study
cd my-study
psyclaw init "社交支持与研究生心理健康的关系" --paradigm survey-observational
psyclaw
```

初始化会建立 `.psyclaw/data/raw/`、`data/clean/`、`literature/pdfs/`、`notes/` 和 `outputs/`，不再把原始数据目录暴露在项目根目录。`.psyclaw/data/raw/` 是只读保护区；旧项目的 `data/raw/` 仍保持只读兼容，把经确认可用于分析的派生数据放在 `data/clean/`。

在对话界面中，`/init <研究目标>` 初始化研究项目与工作区；随后用 Shift+Tab 切换到 `analysis` 或 `academic` 推进。没有单独的 `/run` 或 `/brief` 命令。未 `/init` 时保持普通对话，不强制研究门禁。

登记本地材料：

```powershell
psyclaw evidence add notes\source.md --level user
```

## 常用入口

| 需求 | 命令或操作 |
| --- | --- |
| 启动研究对话 | `psyclaw` 或 `psyclaw chat` |
| 续接当前项目最近一次会话 | `psyclaw --continue` 或 `psyclaw -c` |
| 创建研究项目 | `psyclaw init <goal> --paradigm <profile>` 或对话 `/init <goal>` |
| 推进分析 / 写作 | Shift+Tab 切换 analysis / academic；可选 `/loop`、`/review` |
| 模拟同行评审 | 论文完成后在对话中输入 `/review` |
| 登记本地证据 | `psyclaw evidence add <path> --level user\|fulltext` |
| 写研究移交记录 | `psyclaw handoff` |
| 扫描本机其他 Agent | `psyclaw agents` |
| 查看 PsyClaw 和内置运行时更新 | `psyclaw check-updates` |
| 更新 PsyClaw 和内置运行时 | `psyclaw update` |
| 导出会话 | 使用 Pi 内置的 `/export` |
| 打开科研面板 | 在对话中输入 `/panel` |
| 查看或切换 Provider | 在对话中输入 `/provider` 或 `/provider <id>` |
| 管理启动横幅宠物 | `/pet status`、`/pet on`、`/pet off`（默认关闭） |
| 安装本地 Skill | `/skill install <本地目录>` |
| 管理或安装 Skill | `/skill` 或 `/skill install <本地目录>` |
| 创建项目能力 | `/create-skill`、`/create-hook`、`/create-rule`、`/create-subagent`（均先预览并确认） |
| 运行自定义只读角色 | `/agents --agent <id> <task>` 或 `/agents --agents <id,...> <task>`（最多四个隔离 worker） |
| 调用已加载 Skill | `/skill:<name>` |
| 使用模式 | `Shift+Tab`：`chat` → `analysis` → `academic`；thinking 用 `Ctrl+Shift+Tab` |
| 搭建仓库 | `/init`（只建目录 + `psyclaw.md`） |
| 人确认关键字段 | `/verify list` 或 `/verify <id> verified` |
| 使用 PsyClaw ARS | 切到 `academic`；也可用 `/ars doctor` / `/ars full <task>` |
| 管理 Plugin | `/plugin`；终端使用 `psyclaw plugin install|remove|list` |
| 调用已配置 MCP | 模型通过 `psyclaw_mcp` 自动发现并调用 `.psyclaw/mcp/*.json` 中启用的服务器 |

`psyclaw update` 会更新 PsyClaw 整包，并同时安装该版本锁定的内置运行时。在源码仓库中运行时，命令会停止并提示通过 Git 更新，不会覆盖本地修改。
仅查看更新计划而不执行时，使用 `psyclaw update --check`。旧的 `--yes` 参数仍兼容，但不再需要。

### 导出使用路径

```bash
/export
```

`/export` 由 Pi 内置命令提供。PsyClaw 不重复实现会话导出或 Trace 运行时。

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
npm install -g psyclaw@0.27.5
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
- [PsyClaw ARS 模式与保护边界](docs/PsyClaw-ARS模式.md)
- [文档与交付物规范](docs/文档规范.md)

## 边界

- PsyClaw 复用官方 Pi 的 session、model、skill、package 和 extension runtime，不维护 fork。
- 统计计算委托 Python/R、SPSS/Stata/Mplus 或受信任 MCP；输出必须保存脚本、输入指纹和环境信息。
- Skill、Plugin 和 MCP 默认只发现、不执行；启用前需要来源、版本/ref、哈希、许可证和依赖状态。
- 没有可定位证据的事实性 Claim 必须是 `uncertain` 或被阻断；没有审批记录的副作用不能被当作完成。

许可证：MIT。
