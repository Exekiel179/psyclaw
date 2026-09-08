# 遥测（默认关闭）

PsyClaw 的产品承诺是本地、私有：研究数据默认不离开本机。Sentry（错误与 tracing）和 PostHog（交互分析 / session replay）都是**显式 opt-in**。未设置对应环境变量时，进程不会 import SDK、不会初始化、不会发起遥测网络请求。

## 环境变量

| 变量 | 表面 | 用途 |
| --- | --- | --- |
| `SENTRY_DSN` | Node CLI / agent | 官方 `@sentry/node`：未捕获异常、Promise rejection、tracing |
| `SENTRY_DSN_WEB` | Panel、marketing website | 浏览器 Sentry。也可用 `PUBLIC_SENTRY_DSN` |
| `POSTHOG_KEY` | Node CLI / agent | `posthog-node`：少量粗粒度事件 |
| `PUBLIC_POSTHOG_KEY` | Panel、website | 浏览器 PostHog。未设时 panel 可回退到 `POSTHOG_KEY` |
| `POSTHOG_HOST` | 全部 | 默认 `https://us.posthog.com`。浏览器也可用 `PUBLIC_POSTHOG_HOST` |
| `SENTRY_RELEASE` | 可选 | 未设时用 `psyclaw@<package.json version>` / `psyclaw-web@…` |
| `SENTRY_ENVIRONMENT` | 可选 | 未设时用 `NODE_ENV` 或 `local` |

真实 DSN 与 `phc_` 项目 key **不要写入 Git**。仓库只提供 `.env.example` 占位符。维护者把值贴进本机环境或未跟踪的 `.env`。

## 各表面如何启用

**CLI / agent（Node）**  
`psyclaw` 入口在真正执行命令前读取环境变量；`--help` / `--version` 不会初始化 SDK。聊天子进程通过 Pi extension 同样 opt-in。

**Panel**  
本地面板由本地 HTTP 服务注入 `window.__PSYCLAW_OBS__`（来自上述环境变量），并加载 `/observability.js`。没有 key 时脚本是空操作。

**Website（静态 HTML）**  
`apps/website/index.html` 读取同一配置对象、空 meta 标签，或（仅本地调试）query：`sentryDsn`、`posthogKey`、`posthogHost`。部署时把 meta / `window.__PSYCLAW_OBS__` 填成占位替换，不要把真实 key 提交进仓库。

浏览器 snippet 只在 key 存在时才从 CDN 加载 `@sentry/browser` 与 `posthog-js`。

## 采集什么、不采集什么

启用后，Node 侧只发送粗粒度事件，例如：

- `research_run_started` / `research_run_finished`（`phase`、`status`、`duration_ms`、`mode`、`skill_count`）
- `gate_waiting_for_human`（`plan_approval` / `run_approval` / `tool_approval`）
- `agent_error`（错误类名与 phase，不含论文正文）

事件属性有白名单；研究目标、论文文本、路径、PII 不会作为属性发送。Sentry `beforeSend` 会再做一次密钥形态脱敏，并关闭 local variables / HTTP body / 默认 PII。

Panel 上的 PostHog 打开 autocapture、pageview 和 session replay，同时 `maskAllInputs`、屏蔽 `.markdown` / `.viewer-body` 等研究正文区域，autocapture 对 panel 使用 `mask_all_text`。

## 本地验证

```bash
export SENTRY_DSN="…"          # Node 项目 DSN
export SENTRY_DSN_WEB="…"      # 浏览器项目 DSN
export POSTHOG_KEY="phc_…"
export PUBLIC_POSTHOG_KEY="$POSTHOG_KEY"
pnpm build
# 触发一个会失败的 CLI 命令，或在 panel 中操作后查看 Sentry Issues / PostHog events
```

未 export 这些变量时，行为应与加遥测前一致。
