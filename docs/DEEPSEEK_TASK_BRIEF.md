# psyclaw DeepSeek 开发任务书

版本：2026-08-14
目标分支：`psyclaw-research-agent-suite`
当前基线：`0aab8b8`（任务启动基线；后续 D1-D7 已分别落盘）
任务性质：在现有实现上做可独立验收的基础加固；不是重新设计 psyclaw，也不是扩展成重量级 Agent 平台。

## 0. 先读什么

开始前必须阅读：

1. `README.md`
2. `docs/开工纪要.md`
3. `docs/架构蓝图.md`
4. `docs/多智能体开发与运行框架.md`
5. `docs/评测框架.md`
6. `docs/威胁模型.md`

当前本机基线已经通过：

```text
pnpm typecheck
pnpm build
pnpm test                 # 任务启动时 28 files / 113 tests；当前复核 29 files / 159 tests
pnpm eval                 # 6 个离线案例，hardFailCount = 0
git diff --check
```

这些通过只代表现有 fixture 通过，不代表下载、外部 Skill、MCP、模型或真实网络安全已经证明。当前版本仍是 `blocked`，不要在提交信息或报告中写“生产就绪”。

## 1. 分工边界

### DeepSeek 负责

完成本文第 3 节列出的安全、契约、测试和基础 UI 工作。每项工作必须小范围修改、带确定性 fixture，并保持离线默认。

### Root 保留的唯一核心工作

我保留 **Pi 原生运行时、模型适配和原生多智能体入口的整合**。这是一项不可拆开的核心工作，包含：

- `AgentSession` / `SessionManager` / `DefaultResourceLoader` 的 adapter；
- ModelGateway/provider 配置（包括 OpenAI-compatible/DeepSeek endpoint、模型列表、fallback、密钥引用和日志脱敏）；
- Pi 原生多智能体执行入口、受控 executor 和真正的进程/容器隔离；
- `/model`、`/agents` 等 Pi 命令与最终面板接入；
- 最终合并、Node 22 CI 和发布闸门。

DeepSeek 不得修改以下保留路径，除非先在报告中提出接口变更并得到确认：

```text
src/adapters/pi/extension.ts
src/adapters/pi/session.ts       # Root 保留，已创建
src/adapters/pi/model.ts         # Root 保留，已创建
src/adapters/pi/resources.ts     # Root 保留，已创建
src/adapters/pi/rpc.ts           # Root 保留，已创建
src/orchestration/pi-executor.ts # Root 保留，已创建
```

不要自行添加第二套 provider/session/plugin runtime，也不要把真实 API key 写入仓库、测试、日志、截图或 fixture。

## 2. 工作规则

- 一次只做一个任务；不得两个任务同时改同一文件。
- 先读现有代码和测试，再编辑；保持现有 TypeScript/ESM、TypeBox、JSONL 模式。
- 不使用 `git reset --hard`、`git checkout --` 或覆盖他人改动。
- 不为“通过测试”放宽 evidence gate、raw-data 保护、审批或 provenance 要求。
- 默认不联网、不调用真实模型、不安装第三方包；需要网络的行为只能通过 fake runner/fixture 验证。
- `data/raw`、`.git`、凭据、secret、符号链接目标永远不可写。
- 任何 P0、安全边界不确定、许可证不明或 API 行为不确定，立即停止该任务并报告，不自行猜测。
- 应用层路径检查不等于 OS sandbox；不要在报告中把它描述成沙箱。

## 3. DeepSeek 任务清单

| ID | 任务 | 优先级 | 依赖 | 主要 owned paths |
|---|---|---:|---|---|
| D1 | 安装/下载安全闭环与真实幂等 | P1 | 无 | `src/install/installer.ts`, `src/agents/catalog.ts`, `src/cli.ts`, `tests/unit/installer.test.ts` |
| D2 | 外部 Agent Skill 导入边界 | P1 | 无 | `src/agents/import.ts`, `tests/unit/agents-import.test.ts`, `tests/security/*import*` |
| D3 | Runner 产物/回执/恢复验收 | P1 | 无 | `src/orchestration/runner.ts`, `tests/unit/orchestrator.test.ts`, `tests/contract/parallel.test.ts` |
| D4 | Workflow 输出、事件顺序和 provenance | P1 | D3 的契约可参考即可 | `src/workflows/*`, `tests/integration/workflows.test.ts` |
| D5 | MCP 工具 allowlist、effect 和超时 | P1 | 无 | `src/integrations/mcp.ts`, `tests/contract/mcp.test.ts` |
| D6 | Skill manifest/许可证/依赖准入 | P1 | 无 | `src/skills/*`, `tests/unit/skills-registry.test.ts`, `tests/security/malicious-skill.test.ts` |
| D7 | Panel 事实投影 fail-closed | P1 | D4 的事件语义 | `src/panel/*`, `tests/unit/panel-projection.test.ts`, `tests/contract/panel-server.test.ts` |
| D8 | 下载/Agent 页面（只读计划视图） | P2 | D1、D7 | `apps/panel/index.html`, 面板相关测试 |
| D9 | 对抗 fixture、文档和回归报告 | P1 | D1-D8 | `tests/security/*`, `evals/cases/*`, `docs/评测框架.md` |

任务可由同一 DeepSeek 会话顺序完成；若拆成多个 worker，必须严格按 owned paths 隔离。

### D1：安装/下载安全闭环与真实幂等

目标：安装前先完成 staging、稳定读取、SHA/来源/许可证预检，只有通过后才激活或执行安装。

必须做到：

- `expectedSha256` 缺失、格式错误或不匹配时，结果为失败，不能返回 `receipt.ok=true`。
- 下载文件先落在受控 staging 目录；验证失败不得留下可执行/已激活结果，也不得静默覆盖旧版本。
- `sourceRef`、版本/ref、许可证和内容 SHA 在计划与 receipt 中可追溯；catalog 不再使用无版本的“最新版”作为已验证安装。
- 相同 `(plan.id, contentSha256, target)` 的重复请求只执行一次；跨进程至少使用项目内原子 receipt/锁或明确返回 `already-recorded`。
- runner 抛异常时返回结构化失败 receipt，不把异常文本原样写入审计字段。
- `kind:agent` 的全局 npm/pipx 命令没有 staged artifact 绑定时必须保持 discover-only；仅有格式正确的 SHA 字符串不能授权执行。
- 保留人工 `--yes` 审批；浏览器/面板本轮不得直接执行安装命令。

建议新增 fixture：hash mismatch、missing pin、runner throw、重复调用计数必须为 1、旧版本不被破坏。

完成命令：

```text
pnpm vitest run tests/unit/installer.test.ts
pnpm typecheck
pnpm test
```

### D2：外部 Agent Skill 导入边界

目标：只导入经过路径和内容检查的 Skill 资料，不把外部 Agent 目录当作可信文件树。

必须做到：

- 校验 `agent.id`、`skill.name` 和所有目标路径，使用项目根 containment；拒绝绝对路径、`..`、ADS、`.git`、`data/raw`、credentials、secret 和符号链接祖先。
- 源文件在复制前后做 canonical path 和 SHA-256 稳定检查；源文件被替换时 fail-closed。
- 默认只允许 `SKILL.md` 以及明确列入白名单的 `references/`、`scripts/`、`assets/` 内容；拒绝 `.env`、auth、token、cookie、私钥和可疑二进制文件。
- 目标已存在时不得无提示覆盖；相同 SHA 可幂等跳过，不同 SHA 必须冲突阻断并保留旧文件。
- manifest 记录 source/resolved path、每个文件 SHA、审批者和安全诊断；导入结果不代表 Skill 已启用。

必须补测：伪造 `AgentScan` 路径穿越、skill 名称覆盖、目录内 `.env`、目标 symlink、源文件竞态、重复导入。

### D3：Runner 产物/回执/恢复验收

目标：Verifier 只接受真实、归属明确、可复核的完成结果。

必须做到：

- 每个 required artifact 必须位于该 task 的 `ownedPaths` 或 `outputs`，不能用项目中预先存在的任意文件冒充。
- required artifact 必须是 regular file，拒绝 protected path，并验证实际存在和 SHA-256；路径、hash、run/task/dispatch ID 严格校验。
- `allowedEffects` 缺省仍为 `read`；`write`、`network`、`destructive` 分开处理，不能用一个 `allowWrites` 布尔值隐式放行全部副作用。
- receipt 必须有安全 ID、合法时间、effect、approval、幂等键；同一 run 全局保留幂等键 reservation，兄弟 worker 不能竞态通过同一键。
- checkpoint 恢复时重新验证成功任务的 artifact、receipt、written paths 和任务集合；损坏、伪造或漂移必须转为 `blocked`，不能静默复用。
- 明确保留当前限制：这仍不是 OS sandbox；不要试图用 `filesModified` 自报来解决隐匿副作用问题，并在测试/文档中标明残余风险。

必须新增：既有 `package.json` 冒充 artifact、receipt 空 ID/坏时间、重复键并发、checkpoint 篡改、network/destructive 未批准等 fixture。

### D4：Workflow 输出、事件顺序和 provenance

目标：工作流只有在产物、manifest 和 verdict 都成功落盘后，才能发出 `completed`。

必须做到：

- 所有 `output.path` 经过安全项目路径检查；拒绝 traversal、绝对路径、raw、`.git`、credentials 和 symlink ancestor。
- `WorkflowSpec.requiredArtifacts` 必须实际检查；每个输出记录 SHA、输入 digest、workflow version、环境/脚本引用。
- 事件顺序固定为 `planned -> started/gates -> outputs verified -> manifest/verdict -> completed`；任何中途失败只发 `blocked` 或 `unknown`。
- evidence gate 阻断时不生成可被误认成完成正文的输出；如确需保留草稿，必须写明 `draft/blocked` 状态并从 `verified` 列表排除。
- 固定输出文件有并发保护；不同 run 不能互相覆盖。

### D5：MCP 工具 allowlist、effect 和超时

目标：MCP server 信任不等于所有工具自动可信。

必须做到：

- `list()` 后缓存工具 descriptor；`invoke()` 只能调用本次发现且显式启用的工具。
- 对输入做最小 schema/类型检查；工具不存在、输入不符合 schema、来源或 effect 不匹配时 fail-closed。
- effect 不能由 server 自报提升；`read/write/network/destructive` 使用宿主侧 ceiling 和人工审批。
- 副作用调用必须有幂等键，重复键不得重新执行；超时、断线或错误必须关闭/终止 transport，不能留下孤儿进程。
- 错误 receipt 只保留稳定 reason code/hash，不泄露 server 原文、环境变量或凭据。

### D6：Skill manifest/许可证/依赖准入

目标：Skill 正文的 frontmatter 不是供应链证明。

必须做到：

- `approvedIds` 无 pin 的 shorthand 不得授予执行权；批准至少绑定 root/resolved path/ref 和 SHA。
- `licenseStatus`、`dependencyStatus`、`trust` 由宿主 manifest/预检决定，不能接受 Skill 自报 `verified/ready/trusted` 作为充分条件。
- 执行批准还必须带版本化主机 admission evidence（`psyclaw/skill-admission/v1`、SPDX、许可证证据引用、依赖审计引用、SBOM SHA-256，并绑定 `contentSha256`）；只有路径/SHA pin 仍保持 `discover-only`。
- license unknown、依赖 missing/blocked、manifest/SBOM 缺失默认 `discover-only`；高风险人工 override 必须有审计记录。
- load 前后继续做 stable read、realpath 和 hash 检查；冲突 ID 不得静默择一。

补测：同 ID 换 root/换内容、缺许可证、自报 trusted、缺依赖、过期 SHA、恶意正文和 symlink race。

### D7：Panel 事实投影 fail-closed

目标：面板是事实的只读投影，不是“看起来完成”的生成器。

必须做到：

- event schema 除字段类型外校验状态机；单独伪造 `completed` 事件不能让 run 变成 completed。
- corrupt/missing checkpoint、ledger 或 event 应显示 `unknown/blocked` 并给稳定诊断，不得 catch 后当作不存在。
- artifact 路径、goal、gate reason 和错误响应做脱敏；server 默认只允许 loopback，不能由调用者随意暴露到外网。
- API 只读，明确拒绝写方法；保留现有 `/api/runs`、`/api/snapshot` 兼容性。

### D8：下载/Agent 页面（只读计划视图）

这是 UI 基础任务，不实现模型页，也不执行安装。

必须做到：

- 在现有 `apps/panel/index.html` 增加 Agents/Skills 只读视图：已发现、来源、版本/ref、许可证状态、SHA、风险、是否已配置。
- 展示安装计划和审批前风险；点击页面不能直接执行 npm/pipx/curl。
- 面板断线、空目录、无项目、恶意/缺许可证状态有明确空态和 blocked 状态。
- 不把 credential path 内容展示给浏览器；不添加任意文件读取 endpoint。

TUI 的安装确认文案可补充 source/ref/license/hash，但实际安装安全由 D1 提供。

### D9：对抗 fixture、文档和回归报告

为 D1-D8 各补至少一个确定性测试，并更新：

- `docs/评测框架.md` 的实际测试数量、任务状态和新增 hard-fail 案例；
- `docs/威胁模型.md` 的安装、导入、worker 隐匿副作用和面板篡改残余风险；
- `README.md` 中的面板、模型适配和安装器状态与实际命令一致；
- 不要把评测生成的密钥、完整论文或敏感路径写入 `evals/reports/latest.json`。

## 4. 建议执行顺序

```text
D1 || D2 || D5 || D6
        |
       D3
        |
       D4 || D7
        |
       D8
        |
       D9
        |
Root：Pi runtime + model adapter + native multi-agent integration + final gate
```

`||` 只表示文件不重叠；同一 worker 可以顺序执行。D9 必须在代码测试真实通过后更新数字，不得预填结果。

## 5. Worker 回报格式

每个任务完成后只提交一份结构化报告，并附精确命令输出：

```json
{
  "schemaVersion": "psyclaw/worker-report/v1",
  "taskId": "D1",
  "outcome": "succeeded|failed|blocked",
  "summary": "事实性摘要，不写模型自评",
  "filesModified": [],
  "verification": [
    {"command": "pnpm vitest run ...", "exitCode": 0, "outputDigest": "<sha256>"}
  ],
  "securityFindings": [],
  "blockers": [],
  "nextOwner": "root|D<id>|human"
}
```

报告必须说明：是否联网、是否运行外部命令、是否接触凭据、是否有未解决的 TOCTOU/OS sandbox 风险。没有实际命令就写 `verification: []`，不能写“已验证”。

## 6. 统一完成定义

任务只有同时满足以下条件才可标记 `succeeded`：

1. 只修改 TaskSpec 的 owned paths，`git diff --check` 通过。
2. 目标单测、相关契约测、至少一个安全对抗 fixture 通过。
3. `pnpm typecheck`、`pnpm test`、`pnpm eval` 全部通过，或明确记录是哪个外部条件阻塞。
4. 没有降低既有 gate、审批、raw-data 或 provenance 规则。
5. 失败闭合：异常、超时、缺 hash、缺许可证、路径不确定时返回 blocked/unknown，而不是成功。
6. 没有真实 API key、Cookie、未授权全文或个人数据进入仓库、日志、测试报告。

## 7. 交接给 Root

DeepSeek 完成 D1-D9 后不要自行宣称 release-ready。Root 将重新审查 diff，接入保留的 Pi runtime/model/native multi-agent 工作，并在 Node 22、真实 provider、真实 MCP 和面板隐私回归完成后决定是否解除 `blocked`。

### Root 复核结果（2026-08-14）

- D1-D7 基础加固和 D8 只读 Agents/Skills、模型适配元数据页已落盘；完成 `pi install -l .` 后，项目级 package 默认加载原生研究命令与只读 `/agents`；fresh checkout 可用 `pi --extension ./dist/src/extension.js` 临时加载。
- `src/panel/extension.ts` 是可选扩展，只绑定 `127.0.0.1`，`/panel` 只启停只读面板；浏览器页面不会执行 npm/pipx/curl，也不会接收 API key。
- Root 已接入 `AgentSession`、`SessionManager`、`DefaultResourceLoader`、`ModelRuntime` 和严格 JSONL RPC；DeepSeek/OpenAI-compatible provider 配置只输出环境变量引用。
- 当前验收：`pnpm typecheck`、`pnpm build`、`pnpm test`（29 files / 159 tests）、`pnpm eval`、`git diff --check` 全通过。
- 发布仍保持 `blocked`：Node 22 CI、真实 provider/MCP、真实下载供应链和 OS 级 worker sandbox 尚未证明。

### 可直接复制给 DeepSeek 的启动指令

```text
你负责 psyclaw 的基础安全与契约任务，遵守 docs/DEEPSEEK_TASK_BRIEF.md。
先执行 D1、D2、D5、D6 中一个，读取现有代码和测试后再编辑。
不要修改 src/adapters/pi/*、src/orchestration/pi-executor.ts，也不要实现模型 provider 或原生多智能体入口；这些由 Root 负责。
每个任务只改 owned paths，补确定性对抗测试，失败闭合，不联网、不读取凭据。
完成后按文档第 5 节返回结构化 worker report，附真实命令、退出码、残余风险和下一任务建议。
```
