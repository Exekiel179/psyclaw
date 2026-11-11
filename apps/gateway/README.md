# PsyClaw 官方网关服务

## 概述

PsyClaw 官方网关是一个 OpenAI 兼容的 API 代理，为用户提供开箱即用的模型服务。用户通过充值或订阅使用 DeepSeek、Claude 等模型，无需自备各家 Provider 的 API Key。

**核心特性**：
- OpenAI 兼容接口（`/v1/chat/completions`）
- 微信支付、支付宝充值（国内用户优先）
- 订阅套餐支持
- 按 token 用量计费，价格以人民币计
- 支持国内部署（DeepSeek 可直连，Claude 需香港/海外节点）

**重要说明**：
- 官方网关是**可选服务**，不影响现有自定义 Provider 功能
- 用户可以在官方网关和自定义 Provider 之间自由切换

## 快速开始

### 1. 环境要求

- Node.js >= 22.19.0
- PostgreSQL >= 14
- Redis >= 6

### 2. 安装依赖

```bash
cd apps/gateway
pnpm install
```

### 3. 配置环境变量

复制 `.env.example` 为 `.env` 并填写：

```bash
# 服务端口
PORT=3000

# 数据库
DATABASE_URL=postgresql://user:pass@localhost:5432/psyclaw_gateway
REDIS_URL=redis://localhost:6379

# 上游 Provider 凭据（从环境变量读取，不提交到仓库）
UPSTREAM_DEEPSEEK_API_KEY=sk-xxx
UPSTREAM_ANTHROPIC_API_KEY=sk-ant-xxx

# 微信支付配置
WECHAT_PAY_MCH_ID=1234567890
WECHAT_PAY_API_KEY=your-api-v3-key
WECHAT_PAY_CERT_PATH=/path/to/apiclient_cert.pem
WECHAT_PAY_NOTIFY_URL=https://api.psyclaw.ai/webhooks/wechat

# 支付宝配置
ALIPAY_APP_ID=2021001234567890
ALIPAY_PRIVATE_KEY=your-private-key
ALIPAY_PUBLIC_KEY=alipay-public-key
ALIPAY_NOTIFY_URL=https://api.psyclaw.ai/webhooks/alipay

# JWT 签名密钥
JWT_SECRET=your-random-secret-min-32-chars

# 网关公网地址
GATEWAY_BASE_URL=https://api.psyclaw.ai

# 可选：国内节点地址（用于客户端配置）
# GATEWAY_CHINA_NODE=https://api-cn.psyclaw.ai
```

### 4. 初始化数据库

```bash
pnpm db:migrate
```

### 5. 启动服务

```bash
# 开发模式（带热重载）
pnpm dev

# 生产模式
pnpm build
pnpm start
```

## API 文档

### 认证相关

#### POST /auth/login
生成访问 token（具体登录方式待实现：微信扫码/手机号验证码）。

**请求**：
```json
{
  "method": "wechat_qr" | "phone_sms",
  "credential": "扫码凭证 or 手机号+验证码"
}
```

**响应**：
```json
{
  "token": "eyJhbGc...",
  "expiresAt": "2026-11-12T10:09:00Z",
  "userId": "usr_xxx"
}
```

#### GET /account/balance
查询当前余额和订阅状态。

**请求头**：
```
Authorization: Bearer <token>
```

**响应**：
```json
{
  "balance": 12345,
  "subscription": {
    "plan_id": "standard_monthly",
    "status": "active",
    "expire_at": "2026-11-30T00:00:00Z",
    "quota": {
      "used": 50000000,
      "total": 100000000,
      "unit": "tokens"
    }
  }
}
```

### 模型调用

#### POST /v1/chat/completions
OpenAI 兼容的聊天接口。

**请求头**：
```
Authorization: Bearer <token>
Content-Type: application/json
```

**请求体**（与 OpenAI 一致）：
```json
{
  "model": "deepseek-v4-flash",
  "messages": [
    { "role": "user", "content": "你好" }
  ],
  "stream": false
}
```

**响应**（与 OpenAI 一致）：
```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "created": 1697000000,
  "model": "deepseek-v4-flash",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "你好！有什么可以帮助你的吗？"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 20,
    "total_tokens": 30
  }
}
```

**错误响应（余额不足）**：
```json
{
  "error": {
    "message": "余额不足，请充值或订阅",
    "type": "insufficient_credits",
    "code": "balance_low",
    "param": null
  }
}
```

### 支付相关

#### POST /payment/topup
创建充值订单。

**请求**：
```json
{
  "amount": 10000,
  "paymentMethod": "wechat" | "alipay"
}
```

**响应（Native 支付）**：
```json
{
  "orderId": "ord_xxx",
  "qrCodeUrl": "weixin://wxpay/bizpayurl?pr=xxx",
  "expireAt": "2026-10-12T10:19:00Z"
}
```

**响应（H5 支付）**：
```json
{
  "orderId": "ord_xxx",
  "h5Url": "https://wx.tenpay.com/cgi-bin/mmpayweb-bin/checkmweb?..."
}
```

#### GET /payment/order/:orderId
查询订单状态（用于轮询）。

**响应**：
```json
{
  "orderId": "ord_xxx",
  "status": "unpaid" | "paid" | "expired" | "refunded",
  "amount": 10000,
  "paidAt": "2026-10-12T10:15:30Z"
}
```

#### POST /webhooks/wechat
微信支付异步通知接口（由微信服务器调用）。

#### POST /webhooks/alipay
支付宝异步通知接口（由支付宝服务器调用）。

## 项目结构

```
apps/gateway/
├── src/
│   ├── index.ts                 # 服务入口
│   ├── config.ts                # 环境变量配置
│   ├── auth/
│   │   ├── middleware.ts        # 认证中间件
│   │   ├── token.ts             # Token 生成与验证
│   │   └── login.ts             # 登录逻辑（待实现）
│   ├── proxy/
│   │   ├── handler.ts           # /v1/chat/completions 代理
│   │   ├── upstream.ts          # 上游路由配置
│   │   └── pricing.ts           # 计价逻辑
│   ├── payment/
│   │   ├── interface.ts         # PaymentProvider 接口
│   │   ├── wechat.ts            # 微信支付实现
│   │   ├── alipay.ts            # 支付宝实现
│   │   └── stripe.ts            # Stripe stub
│   ├── billing/
│   │   ├── balance.ts           # 余额管理
│   │   ├── subscription.ts      # 订阅管理
│   │   └── transaction.ts       # 交易记录
│   ├── db/
│   │   ├── schema.ts            # 数据库 schema
│   │   ├── migrations/          # 迁移脚本
│   │   └── client.ts            # 数据库客户端
│   └── audit/
│       └── usage-log.ts         # 使用审计
├── tests/
│   ├── auth.test.ts
│   ├── proxy.test.ts
│   ├── billing.test.ts
│   └── payment.test.ts
├── package.json
├── tsconfig.json
├── .env.example
└── README.md
```

## 支持的模型

| 网关模型 ID | 上游 Provider | 计费价格（CNY/1M tokens） |
|------------|---------------|--------------------------|
| `deepseek-v4-flash` | DeepSeek | 输入 ¥3.0 / 输出 ¥12.0 |
| `deepseek-v4-pro` | DeepSeek | 输入 ¥3.0 / 输出 ¥12.0 |
| `claude-sonnet-4-6` | Anthropic | 输入 ¥43.2 / 输出 ¥216.0 |

*上游官方价格的 1.5x - 2.0x 加价，用于覆盖运营成本和支付手续费*

## 定价策略（草案）

### 充值档位

| 充值金额 | 赠送 | 实际到账 |
|---------|-----|---------|
| ¥50 | 0% | ¥50 |
| ¥100 | 5% | ¥105 |
| ¥500 | 10% | ¥550 |
| ¥1000 | 15% | ¥1150 |

### 订阅套餐（待实现）

| 套餐 | 价格/月 | 额度 | 适用模型 |
|------|--------|------|----------|
| 轻量版 | ¥99 | 1000 万 tokens | DeepSeek V4 Flash |
| 标准版 | ¥299 | 5000 万 tokens | DeepSeek V4 Flash/Pro |
| 专业版 | ¥999 | 2 亿 tokens + 500 万 Claude tokens | 全部模型 |

## 国内可访问性

### 部署方案

- **推荐**：阿里云华东/华北节点（延迟低，DeepSeek 可直连）
- **Claude 路由**：
  - 方案 A：香港节点转发
  - 方案 B：使用国内代理商 API（如阿里云 PAI、Azure China）

### ICP 备案（待决事项）

- 域名 `api.psyclaw.ai` 是否需要备案？
- 备案主体：个人 vs 企业？
- 备案前使用临时 IP 或已备案域名子路径

## 合规要求（待决事项）

1. **支付资质**：
   - 微信支付/支付宝商户号（需企业主体、营业执照）
   - 支付手续费：约 0.6%

2. **数据安全**：
   - 用户数据加密存储
   - 日志留存（根据等保要求）

3. **内容审核**：
   - 模型输出是否需要接入审核服务？（取决于规模和监管要求）

## 开发指南

### 添加新模型

1. 在 `src/proxy/upstream.ts` 添加路由配置：
   ```ts
   export const UPSTREAM_MODELS = {
     "new-model-id": {
       provider: "provider-name",
       upstreamModel: "upstream-model-id",
       apiKeyEnv: "UPSTREAM_PROVIDER_API_KEY",
       baseUrl: "https://api.provider.com/v1",
       pricingMultiplier: 1.5, // 加价比例
     },
   };
   ```

2. 在客户端 `src/setup.ts` 的 `psyclaw` 预设中添加模型：
   ```ts
   models: [
     // ... 现有模型
     { id: "new-model-id", name: "New Model Name" },
   ]
   ```

### 添加新支付方式

1. 实现 `PaymentProvider` 接口（参考 `src/payment/interface.ts`）
2. 在 `src/config.ts` 中注册新 provider
3. 添加对应的 webhook 路由

## 运维

### 日志

所有请求和错误日志输出到 stdout，可使用日志收集工具（如 Logstash、Fluentd）。

**关键日志**：
- `[AUTH]`：认证成功/失败
- `[PROXY]`：上游请求开始/完成
- `[BILLING]`：扣费操作
- `[PAYMENT]`：支付回调

### 监控指标

建议监控：
- 请求延迟（P50/P95/P99）
- 上游 API 错误率
- 余额不足拒绝率
- 支付回调成功率
- 数据库连接池状态

### 备份

- PostgreSQL：每日全量备份 + WAL 归档
- Redis：定期 RDB 快照（用户会话数据可接受短期丢失）

## 安全

- **环境变量隔离**：上游 API Key、支付密钥等敏感信息仅通过环境变量读取，不提交代码
- **签名验证**：所有支付回调必须验证签名
- **Rate Limiting**：防止滥用（基于 Redis + IP/用户）
- **HTTPS only**：生产环境强制 HTTPS

## 故障排查

### 常见问题

**Q: 微信支付回调签名验证失败**
A: 检查商户证书路径、API v3 密钥是否正确，确保使用微信提供的平台公钥

**Q: DeepSeek 调用超时**
A: 检查网络连通性，确认服务器可访问 `https://api.deepseek.com`

**Q: Claude 调用失败（国内）**
A: 需要香港/海外节点或使用代理商 API

**Q: 用户反馈余额显示不准**
A: 检查 `transactions` 表的一致性，运行余额校对脚本

## License

PsyClaw Gateway 服务代码遵循 CC-BY-NC-4.0 许可证（与主项目一致）。

## 联系与支持

- GitHub Issues: https://github.com/Exekiel179/psyclaw/issues
- 文档：https://github.com/Exekiel179/psyclaw/docs/gateway-design.md
