# 遥测（默认开启，可关闭）

PsyClaw 默认发送**匿名产品遥测**，用来改进工具：粗粒度的使用事件与错误报告。研究正文、论文、对话、个人路径和身份信息不会作为遥测内容发送。

首次启动会用平静的说明告知这一默认行为，并提供立即关闭的选项。阅读后不会每次启动再打扰。偏好保存在本机 `~/.psyclaw/agent/psyclaw-settings.json` 的 `telemetry.enabled`。

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

## 采集什么、不采集什么

开启时，Node CLI / agent 只发送粗粒度事件，例如：

- `research_run_started` / `research_run_finished`（`phase`、`status`、`duration_ms`、`mode`、`skill_count`）
- `gate_waiting_for_human`（`plan_approval` / `run_approval` / `tool_approval`）
- `agent_error`（错误类名与 phase，不含论文正文）

事件属性有白名单。Sentry `beforeSend` 会再做一次密钥形态脱敏，并关闭 local variables / HTTP body / 默认 PII。

Panel 在遥测开启时使用 autocapture、pageview 和 session replay，同时 `maskAllInputs`，并屏蔽 `.markdown` / `.viewer-body` 等研究正文区域。

已关闭时：不 import SDK、不初始化、不发起遥测网络请求。

## 密钥与覆盖

产品使用打包的公开客户端凭证（Sentry DSN / PostHog project key）。它们不是用户密钥；仅在遥测开启时使用。可用环境变量覆盖发送目标：

| 变量 | 表面 |
| --- | --- |
| `SENTRY_DSN` | Node CLI |
| `SENTRY_DSN_WEB` / `PUBLIC_SENTRY_DSN` | Panel |
| `POSTHOG_KEY` / `PUBLIC_POSTHOG_KEY` | Node / Panel |
| `POSTHOG_HOST` / `PUBLIC_POSTHOG_HOST` | 默认 `https://us.posthog.com` |

`--help` / `--version` / `psyclaw telemetry` 不会初始化 SDK。
