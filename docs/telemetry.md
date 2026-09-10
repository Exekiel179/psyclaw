# 遥测（默认开启，可关闭）

PsyClaw 默认发送**匿名产品遥测**，用来改进工具：粗粒度的使用事件、错误报告、LLM 用量元数据，以及可选的 Langfuse 追踪。研究正文、论文、对话内容和身份信息不会作为遥测内容发送。文件系统错误只携带 **home 脱敏后的路径**（`~` 前缀）、errno 与 syscall。

首次启动会用平静的说明告知这一默认行为，并提供立即关闭的选项。阅读后不会每次启动再打扰。偏好保存在本机 `~/.psyclaw/agent/psyclaw-settings.json` 的 `telemetry.enabled`。同一文件里的 `telemetry.anonymousId`（形如 `psyclaw:<uuid>`）是 CLI 与本地面板共用的 PostHog `distinct_id`。

营销网站（`apps/website`）**不会**对普通访客自动开启采集；页面本身不带项目 key。

## 如何关闭 / 重新开启

```bash
psyclaw telemetry off
psyclaw telemetry on
psyclaw telemetry status
```

对话里：`/telemetry off`、`/telemetry on`、`/telemetry status`。

本地面板若尚未阅读过说明，会显示同一条提示；可点「关闭遥测」或「知道了」。

开发者可在当前进程强制关闭（不写偏好文件）：

```bash
PSYCLAW_TELEMETRY=0 psyclaw
```

`PSYCLAW_TELEMETRY=1` 可在已关闭偏好时强制打开当前进程（调试用）。

## CLI 与面板如何对上同一个人

| 表面 | SDK | distinct_id 来源 |
| --- | --- | --- |
| Node CLI / Pi extension | `posthog-node` | `telemetry.anonymousId`（启动时写入 settings） |
| 本地面板 | `posthog-js` | 同一 `anonymousId`，经 `window.__PSYCLAW_OBS__.distinctId` 注入，`bootstrap.distinctID` |
| 营销网站 | 不采集 | 空 |

两边都设置 `$process_person_profile: false` / `person_profiles: identified_only`，并且**不会** `identify()` 成邮箱或用户名。面板 persistence 为 `memory`，刷新后仍使用服务器注入的同一 id。调试可用 `PSYCLAW_DISTINCT_ID` 覆盖当前进程（不写文件）。

## 采集什么、不采集什么

开启时，Node CLI / agent 发送：

- `research_run_started` / `research_run_finished`（`phase`、`status`、`duration_ms`、`mode`、`skill_count`）。`/run` 在启动时发 started，会话结束发 finished（`status=shutdown`）。`psyclaw brief` / `/brief` 与编排器发 started+finished。
- `skill_install_queued` / `skill_install_started` / `skill_install_finished` / `skill_install_failed`（`skill_id`、`scope=project|user`）。推荐 Skill 交给模型安装时是 queued，不是同步 finished。
- `gate_waiting_for_human`（`plan_approval` / `run_approval` / `tool_approval`）
- `agent_error`：错误类名、phase、surface，以及可用时的 `errno`、`syscall`、`failed_path`、`cwd`（均已 `~` 脱敏）、`scope`、`package_version`、`os_platform`、`os_arch`
- `$ai_generation`：Pi 模型调用的 **token / 模型 / 延迟 / 估算费用 / 是否出错**。默认隐私模式：**不含 prompt、completion、工具参数或研究正文**

事件属性有白名单。Sentry `beforeSend` 会再做一次密钥形态脱敏，并关闭 local variables / HTTP body / 默认 PII。

Panel 在遥测开启时使用 autocapture、pageview 和 session replay，同时 `maskAllInputs`，并屏蔽 `.markdown` / `.viewer-body` 等研究正文区域。面板与 CLI 共用 `anonymousId`，因此 rageclick 可以和随后的 `agent_error` / `research_run_*` 对齐。

已关闭时：不 import SDK、不初始化、不发起遥测网络请求（含 Langfuse）。

## Sentry Performance

CLI 在遥测开启且 `SENTRY_DSN`（或打包公钥）可用时，对关键路径打轻量 span（`op: psyclaw`）：

- `cli.research_run` — `/run` 启动与编排器 `runPlan` / `resumePlan`
- `cli.brief` — 离线 brief
- `cli.skill_install` / `cli.skill_install_local` — 推荐 / 本地 Skill 安装
- `cli.llm_call` — `PiModelGateway.complete` 与只读 RPC worker 的主模型调用

Sentry Node 初始化 **全局 OpenTelemetry TracerProvider**。不要再为 Langfuse 注册第二个 `NodeSDK`。

## PostHog LLM Analytics

LLM 栈是锁定版本的 Pi（`@earendil-works/pi-coding-agent` / `@earendil-works/pi-ai`），不是 OpenAI SDK。因此采用 [PostHog 手动 `$ai_generation` 捕获](https://posthog.com/docs/llm-analytics/installation/manual-capture)，并保持 `POSTHOG_PRIVACY_MODE` 语义（永远不发 prompt/completion）。官方 `@posthog/pi` 扩展会另起一套 identity 且默认可能上传对话内容，本仓库不加载它。

挂载点：Pi `agent_end`、RPC worker 返回的 session 事件、`PiModelGateway.complete`。

## Langfuse（可选，Cloud 免费档）

未设置密钥时完全 no-op，不发请求。

1. 注册 [Langfuse Cloud](https://cloud.langfuse.com)（免费档即可；美区为 [us.cloud.langfuse.com](https://us.cloud.langfuse.com)）。
2. 在项目 Settings → API Keys 创建 public/secret key。
3. 导出环境变量后启动 PsyClaw：

```bash
export LANGFUSE_PUBLIC_KEY=pk-lf-...
export LANGFUSE_SECRET_KEY=sk-lf-...
# 可选。默认 https://cloud.langfuse.com（EU）
export LANGFUSE_HOST=https://cloud.langfuse.com
```

实现走 Langfuse **public ingestion HTTP API**，不挂载 `@langfuse/otel` / 第二套 TracerProvider。Sentry Performance 与 Langfuse traces **不共享** span 上下文，因此 Sentry 的 sampling 不会吃掉 Langfuse 的 LLM 追踪。

## 密钥与覆盖

产品使用打包的公开客户端凭证（Sentry DSN / PostHog project key）。它们不是用户密钥；仅在遥测开启时使用。可用环境变量覆盖发送目标：

| 变量 | 表面 |
| --- | --- |
| `SENTRY_DSN` | Node CLI |
| `SENTRY_DSN_WEB` / `PUBLIC_SENTRY_DSN` | Panel |
| `POSTHOG_KEY` / `PUBLIC_POSTHOG_KEY` | Node / Panel |
| `POSTHOG_HOST` / `PUBLIC_POSTHOG_HOST` | 默认 `https://us.posthog.com` |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | 可选 Langfuse；缺一则关闭 |
| `LANGFUSE_HOST` / `LANGFUSE_BASE_URL` | 默认 `https://cloud.langfuse.com` |
| `PSYCLAW_DISTINCT_ID` | 覆盖当前进程的 PostHog distinct_id（调试） |
| `SENTRY_RELEASE` / `SENTRY_ENVIRONMENT` | 发布标识 |

`--help` / `--version` / `psyclaw telemetry` 不会初始化 SDK。

## Skill 安装与不可写的 cwd

推荐 Skill 的**用户级**启用/范围状态写在 `~/.psyclaw/agent/recommendations.json`（与 Skill 文件 `getAgentDir()/skills/<id>` 一致），不再为了用户级欲望状态去 `mkdir` 当前工作目录的 `.psyclaw`。项目级 Skill 与推荐 MCP 仍写 `cwd/.psyclaw/recommendations.json`。若项目目录不可写（例如 `EPERM mkdir`），CLI / 面板会给出带路径的中文错误，并把 errno、脱敏路径、scope 送进 Sentry / `agent_error`。
