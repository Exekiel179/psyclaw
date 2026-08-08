# Claude Code / Codex Integration

PsyClaw 只读发现本机 Agent 宿主已经安装的 Skill 和 MCP 配置，不复制、修改或接管宿主配置。

## Skill 来源

项目级和用户级均扫描以下目录：

- `.claude/skills`
- `.codex/skills`
- `.agents/skills`
- `.opencode/skills`
- `.cc-switch/skills`
- `PSYCLAW_SKILLS_PATH` 指定的目录

同时识别 Claude Code 已安装插件缓存、Codex marketplace 插件和 `~/.cc-switch/skills`。
Registry 会显示 `provider`、`plugin`、`selected` 和 `duplicate_sources`；默认搜索只返回主项，
通过 `skill_duplicates` 或 `skill_search(include_duplicates=true)` 审计同名副本。

## MCP 来源

Claude Code：

- 项目 `.mcp.json`
- 项目/用户 `.claude/mcp.json`
- 项目/用户 `.claude/settings.json` 和 `settings.local.json` 中的 `mcpServers`
- 用户 `~/.claude.json` 的全局 `mcpServers`，以及当前项目对应的 `projects.<path>.mcpServers`

Codex：

- 项目 `.codex/config.toml`
- 用户 `~/.codex/config.toml` 的 `mcp_servers` 表

cc-switch：

- 用户 `~/.cc-switch/settings.json` 的运行状态
- 用户 `~/.cc-switch/cc-switch.db` 的只读 `mcp_servers` 表

PsyClaw 内置 MCP 定义优先于宿主同名定义。宿主中明确禁用的服务保持禁用。

项目级宿主 MCP 只做发现，默认不执行；确认仓库可信后设置
`PSYCLAW_TRUST_HOST_MCP=1` 才允许启动。多个外部来源出现同名 Skill/MCP 时，PsyClaw
不静默择一，保持冲突项不可调用。

若用户明确要选择某个宿主来源，可设置 `PSYCLAW_MCP_SOURCE_PREFERENCE=codex`、
`cc-switch` 或 `claude-code`；只有匹配来源会在同名冲突中获选。

当前执行客户端支持 stdio MCP。HTTP/SSE 配置会出现在目录中，但标记为 unsupported，不注册成 Agent 工具。

## Kaggle 数据 MCP

PsyClaw 内置登记了可选的 Kaggle stdio MCP，用于搜索数据集、查看元数据与文件列表、
以及下载数据。实现复用外部 `mtrakretech/kaggle-mcp`，并固定到经过核验的 Git 提交；
PsyClaw 本体不内置 Kaggle SDK。

首次使用前安装 `uv`，然后运行：

```bash
psyclaw mcp --setup kaggle
```

通常不需要用户记命令：在 `psyclaw chat` 中直接说“配置 Kaggle MCP”，Agent 会调用
`kaggle_configure` 自动检查已有用户级 Token、环境变量和可用的本机 Token 文件；只有确实找不到凭据时才会提示下一步。

按提示从 <https://www.kaggle.com/settings> 创建 API token。新版 Kaggle 下载的
`KGAT_...` Token 也可以直接导入（不会回显 Token）：

```bash
psyclaw mcp --setup kaggle --access-token-file ~/Downloads/kaggle-token.txt
```

凭据只写入用户级 `~/.kaggle/access_token` 或标准 `~/.kaggle/kaggle.json`，不会写入项目或仓库。
PsyClaw 只把 Token 注入 Kaggle MCP 子进程，不会传播给其他 MCP。配置后可在
`psyclaw chat` 中直接说：

```text
在 Kaggle 搜索适合研究工作倦怠的数据集，先列出候选和字段信息，不要下载。
下载 owner/dataset-name 到当前研究项目的 data/kaggle 目录。
```

首批可直接发现的工具为 `search_datasets`、`dataset_details`、
`list_dataset_files`、`get_dataset_metadata` 和 `download_dataset`；首次连接成功后，
完整 Kaggle 工具目录会写入项目的 `.psyclaw/mcp_tools_cache.json`。所有调用都沿用
PsyClaw 的外部副作用审批，下载、上传、提交和删除不会静默执行。

## 安全边界

- MCP `command` 和 `args` 解析成 argv 后直接交给子进程，不通过 shell。
- 配置中的 `env` 值只传给对应 MCP 子进程；子进程不会继承 PsyClaw 的其他 API/云凭据，目录和 Agent 上下文仅显示变量名。
- 读取目录不会启动 MCP；健康检查只确认 stdio 可执行文件存在。
- 工具注册使用 `mcp__<server>__<tool>` 命名，并沿用副作用审批。
- 第一次发现未缓存的宿主 MCP 时会调用 `tools/list`；工具元数据随后缓存到 `.psyclaw/mcp_tools_cache.json`。
