# PsyClaw 官方网关设计文档

## 1. 概述

为用户提供开箱即用的官方模型服务，免去自备 API Key 的门槛。用户可以通过充值或订阅使用 DeepSeek、Claude 等模型，无需自己注册各家 Provider。

**核心原则**：
- 官方网关是**可选增值服务**，不改变现有自定义 Provider 行为
- 已配置自定义 Provider 的用户保持现有工作流，不会被静默切换
- 国内用户优先：微信支付/支付宝为主要支付方式，价格以人民币计

## 2. 架构分层

```text
CLI/Panel（客户端）
    |
    ├─ 自定义 Provider 路径（现有，不变）
    |   └─ 用户自备 Key → 直接调用上游 API
    |
    └─ 官方 Provider 路径（新增）
        └─ PsyClaw Token → 官方网关 → 上游 API
                |
                ├─ 认证、计量、扣费
                └─ DeepSeek V4 / Claude
```

### 2.1 客户端（src/）

- **Provider 注册**：在 `PROVIDER_PRESETS` 中新增 `"psyclaw"` 条目
  - id: `"psyclaw"`
  - name: `"PsyClaw 官方"`
  - baseUrl: `"https://api.psyclaw.ai/v1"` （可配置为国内节点）
  - api: `"openai-completions"`
  - apiKeyEnv: `"PSYCLAW_GATEWAY_TOKEN"`
  - 模型列表：`deepseek-v4-flash`, `deepseek-v4-pro`, `claude-sonnet-4-6`（网关支持的模型子集）

- **登录流程**：`/provider psyclaw` 触发
  1. 检查本地是否已有 token（`auth.json` 或环境变量）
  2. 无 token：引导用户到 `https://console.psyclaw.ai/login`（微信扫码/手机号）
  3. 登录后用户复制 token，粘贴回 CLI
  4. token 存入 Pi auth store

- **余额展示**：Panel Provider 页面和 `/provider psyclaw` 显示
  - 当前余额（CNY）
  - 套餐状态（若有订阅）
  - Out-of-credit 时显示充值/订阅链接

- **遥测维度**：`observability/llm.ts` 的 `$ai_generation` 事件新增：
  - `provider_type: "official" | "custom"`
  - 区分官方网关流量与自定义 Provider 流量

### 2.2 网关服务（apps/gateway/）

**技术栈**：
- Node.js + TypeScript
- Web 框架：`express` 或 `fastify`（轻量级）
- 数据库：PostgreSQL（用户、余额、订单、订阅）
- Redis：token 会话、rate limiting

**核心模块**：

#### 2.2.1 认证模块（`src/auth/`）

```ts
interface User {
  id: string;
  phone?: string; // 手机号（脱敏）
  wechatOpenid?: string;
  balance: number; // CNY 分为单位
  createdAt: Date;
}

interface GatewayToken {
  token: string; // JWT or opaque token
  userId: string;
  expiresAt: Date;
}
```

- `/auth/login`：微信扫码/手机号验证码（具体实现待定，PR 中标为待决事项）
- `/auth/token`：生成访问 token
- `/auth/refresh`：刷新 token

#### 2.2.2 代理模块（`src/proxy/`）

```ts
// POST /v1/chat/completions
async function proxyCompletion(req: AuthenticatedRequest) {
  const user = req.user;
  const { model, ...body } = req.body;

  // 1. 鉴权
  if (!user.hasActiveSubscription && user.balance <= 0) {
    return { error: "insufficient_credits", message: "余额不足，请充值或订阅" };
  }

  // 2. 路由到上游
  const upstreamConfig = getUpstreamForModel(model);
  const response = await fetch(upstreamConfig.url, {
    method: "POST",
    headers: { Authorization: `Bearer ${upstreamConfig.apiKey}` },
    body: JSON.stringify({ model: upstreamConfig.model, ...body }),
  });

  // 3. 计量与扣费
  const usage = response.usage;
  const cost = calculateCost(model, usage);
  await deductBalance(user.id, cost);

  // 4. 记录审计
  await logUsage({ userId: user.id, model, usage, cost });

  return response;
}
```

**上游路由表**：

| 网关模型 ID | 上游 Provider | 上游模型 ID | 加价比例 |
|------------|---------------|-------------|----------|
| `deepseek-v4-flash` | DeepSeek | `deepseek-v4-flash` | 1.5x |
| `deepseek-v4-pro` | DeepSeek | `deepseek-v4-pro` | 1.5x |
| `claude-sonnet-4-6` | Anthropic | `claude-sonnet-4-6` | 2.0x |

- 加价比例可通过环境变量或数据库配置

#### 2.2.3 支付模块（`src/payment/`）

**接口设计**（pluggable）：

```ts
interface PaymentProvider {
  name: string;

  // 充值：生成订单 + 支付二维码/链接
  createTopUpOrder(params: {
    userId: string;
    amount: number; // CNY
    paymentMethod: "wechat" | "alipay";
  }): Promise<{
    orderId: string;
    qrCodeUrl?: string; // Native 支付二维码
    h5Url?: string; // H5 跳转链接（移动端）
  }>;

  // 订阅：生成订阅订单
  createSubscription(params: {
    userId: string;
    planId: string; // "monthly" | "yearly"
    paymentMethod: "wechat" | "alipay";
  }): Promise<{
    subscriptionId: string;
    qrCodeUrl?: string;
    h5Url?: string;
  }>;

  // 处理异步回调通知
  handleNotification(rawBody: string, signature: string): Promise<{
    orderId?: string;
    subscriptionId?: string;
    status: "success" | "failed" | "pending";
  }>;

  // 查询订单状态（用于轮询）
  queryOrderStatus(orderId: string): Promise<{
    status: "unpaid" | "paid" | "expired" | "refunded";
    paidAt?: Date;
  }>;
}
```

**微信支付实现** (`src/payment/wechat.ts`):

```ts
export class WeChatPayProvider implements PaymentProvider {
  name = "wechat";

  constructor(
    private config: {
      mchId: string; // 商户号
      apiKey: string; // API v3 密钥
      certPath: string; // 商户证书路径
      notifyUrl: string; // 回调 URL
    }
  ) {}

  async createTopUpOrder(params) {
    // 调用微信 Native 支付 API
    const response = await wechatApi.post("/v3/pay/transactions/native", {
      mchid: this.config.mchId,
      out_trade_no: generateOrderId(),
      description: `PsyClaw 充值 ${params.amount / 100} 元`,
      notify_url: this.config.notifyUrl,
      amount: { total: params.amount, currency: "CNY" },
    });
    return {
      orderId: response.out_trade_no,
      qrCodeUrl: response.code_url, // 用于生成二维码
    };
  }

  async handleNotification(rawBody, signature) {
    // 验证签名
    if (!verifySignature(rawBody, signature, this.config.certPath)) {
      throw new Error("Invalid signature");
    }

    const data = JSON.parse(rawBody);
    // 解密通知内容
    const decrypted = decrypt(data.resource.ciphertext, this.config.apiKey);
    const { out_trade_no, trade_state } = decrypted;

    if (trade_state === "SUCCESS") {
      // 入账逻辑
      await creditUser(out_trade_no);
      return { orderId: out_trade_no, status: "success" };
    }

    return { orderId: out_trade_no, status: "pending" };
  }

  async queryOrderStatus(orderId) {
    const response = await wechatApi.get(
      `/v3/pay/transactions/out-trade-no/${orderId}`,
      { mchid: this.config.mchId }
    );
    return {
      status: response.trade_state === "SUCCESS" ? "paid" : "unpaid",
      paidAt: response.success_time ? new Date(response.success_time) : undefined,
    };
  }
}
```

**支付宝实现** (`src/payment/alipay.ts`):

类似结构，调用支付宝当面付 API (`alipay.trade.precreate`) 生成二维码，通过异步通知 (`notify_url`) 接收支付结果。

**Stripe 实现** (`src/payment/stripe.ts`):

作为次要选项，仅提供 stub：

```ts
export class StripePaymentProvider implements PaymentProvider {
  name = "stripe";

  async createTopUpOrder() {
    throw new Error("Stripe payment not implemented yet");
  }

  // ...其他方法同样 throw
}
```

#### 2.2.4 余额与订阅管理（`src/billing/`）

```ts
interface Transaction {
  id: string;
  userId: string;
  type: "recharge" | "deduction" | "refund";
  amount: number; // CNY 分
  balanceBefore: number;
  balanceAfter: number;
  orderId?: string;
  usageLogId?: string; // 关联到使用记录
  createdAt: Date;
}

interface Subscription {
  id: string;
  userId: string;
  planId: string; // "monthly" | "yearly"
  status: "active" | "expired" | "canceled";
  startAt: Date;
  expireAt: Date;
  autoRenew: boolean;
}

// 扣费逻辑
async function deductBalance(userId: string, costCny: number): Promise<void> {
  const user = await db.users.findOne({ id: userId });

  // 优先级：订阅 > 余额
  if (user.hasActiveSubscription) {
    // 订阅用户不扣余额（或额度单独计算）
    return;
  }

  if (user.balance < costCny) {
    throw new Error("Insufficient balance");
  }

  const newBalance = user.balance - costCny;
  await db.users.update({ id: userId }, { balance: newBalance });
  await db.transactions.insert({
    userId,
    type: "deduction",
    amount: costCny,
    balanceBefore: user.balance,
    balanceAfter: newBalance,
  });
}
```

#### 2.2.5 审计与日志（`src/audit/`）

```ts
interface UsageLog {
  id: string;
  userId: string;
  model: string;
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens: number;
  cacheWriteTokens: number;
  costCny: number; // 本次费用
  upstreamCostCny: number; // 上游成本
  marginCny: number; // 利润
  timestamp: Date;
}
```

- 每次请求记录 `UsageLog`
- 定期导出到 PostHog 或数据仓库做分析

### 2.3 部署与配置

**环境变量**（`.env.example`）：

```bash
# 服务端口
PORT=3000

# 数据库
DATABASE_URL=postgresql://user:pass@localhost:5432/psyclaw_gateway
REDIS_URL=redis://localhost:6379

# 上游 Provider 凭据
UPSTREAM_DEEPSEEK_API_KEY=sk-xxx
UPSTREAM_ANTHROPIC_API_KEY=sk-ant-xxx

# 微信支付
WECHAT_PAY_MCH_ID=1234567890
WECHAT_PAY_API_KEY=xxx
WECHAT_PAY_CERT_PATH=/path/to/cert.pem
WECHAT_PAY_NOTIFY_URL=https://api.psyclaw.ai/webhooks/wechat

# 支付宝
ALIPAY_APP_ID=2021001234567890
ALIPAY_PRIVATE_KEY=xxx
ALIPAY_PUBLIC_KEY=xxx
ALIPAY_NOTIFY_URL=https://api.psyclaw.ai/webhooks/alipay

# JWT 签名密钥
JWT_SECRET=random-secret

# 网关公网地址
GATEWAY_BASE_URL=https://api.psyclaw.ai
```

**部署方案**：
- **国内节点**：阿里云/腾讯云，优先级最高（DeepSeek 可直达，Claude 需要代理或香港节点）
- **国际节点**：作为备用（若国内无法访问上游）
- **ICP 备案**：标记为待决事项（需域名备案）

## 3. 国内可访问性考虑

### 3.1 网关部署

- **国内服务器**：阿里云华东/华北，延迟低
- **上游可达性**：
  - DeepSeek：国内可直连 `https://api.deepseek.com`
  - Anthropic Claude：需要香港/海外节点转发，或使用国内代理商（如阿里云 PAI、Azure China）

### 3.2 域名与备案

**待决事项（PR 中说明）**：
- 域名 `api.psyclaw.ai` / `console.psyclaw.ai` 是否需要 ICP 备案？
- 若需备案，备案主体（个人/企业）与时间表？
- 备案前可用临时 IP + 端口访问，或使用已备案的现有域名子路径

### 3.3 合规

**待决事项（PR 中说明）**：
- 支付牌照：微信支付/支付宝需商户资质（企业主体、营业执照）
- 数据安全：用户数据存储、日志留存（等保要求）
- 内容审核：模型输出内容是否需要接入审核服务（取决于规模和监管要求）

## 4. 定价策略

**待决事项（PR 中说明）**：

### 4.1 充值档位（建议）

| 充值金额（CNY） | 赠送 | 实际到账 |
|----------------|------|----------|
| ¥50 | 0% | ¥50 |
| ¥100 | 5% | ¥105 |
| ¥500 | 10% | ¥550 |
| ¥1000 | 15% | ¥1150 |

### 4.2 订阅套餐（建议）

| 套餐 | 价格（CNY/月） | 额度 | 适用模型 |
|------|---------------|------|----------|
| 轻量版 | ¥99 | 每月 1000 万 tokens | DeepSeek V4 Flash |
| 标准版 | ¥299 | 每月 5000 万 tokens | DeepSeek V4 Flash/Pro |
| 专业版 | ¥999 | 每月 2 亿 tokens + 500 万 Claude tokens | 全部模型 |

- 订阅用户超出额度后按充值余额扣费
- 订阅不抵扣充值余额

### 4.3 模型单价（相对上游加价）

| 模型 | 上游价格（CNY/1M tokens） | 网关价格（CNY/1M tokens） | 加价比例 |
|------|--------------------------|--------------------------|----------|
| DeepSeek V4 Flash | 输入 2.0 / 输出 8.0 | 输入 3.0 / 输出 12.0 | 1.5x |
| DeepSeek V4 Pro | 输入 2.0 / 输出 8.0 | 输入 3.0 / 输出 12.0 | 1.5x |
| Claude Sonnet 4.6 | 输入 21.6 / 输出 108 | 输入 43.2 / 输出 216 | 2.0x |

- 上游价格按官方 CNY 列表价或 USD 汇率换算
- 加价用于覆盖运营成本、支付手续费（~0.6%）、利润

## 5. 测试策略

### 5.1 单元测试

- **自定义 Provider 不变性**：
  - `tests/unit/provider-presets.test.ts`：验证新增 `"psyclaw"` 预设不影响现有列表
  - `tests/unit/provider-routing.test.ts`：确保自定义 Provider 仍走原路径，无静默切换

- **官方 Provider 认证**：
  - `tests/unit/gateway-auth.test.ts`：token 验证、过期处理

- **计量与扣费**：
  - `tests/unit/billing.test.ts`：余额不足拒绝、订阅优先级、扣费原子性

- **支付回调**：
  - `tests/unit/wechat-payment.test.ts`：签名验证、解密、幂等性
  - `tests/unit/alipay-payment.test.ts`：同上

### 5.2 集成测试

- **端到端流程**（需 mock 上游和支付）：
  1. CLI 用户登录 → 获取 token
  2. 调用 `/v1/chat/completions` → 网关认证、代理、扣费
  3. 余额不足 → 返回明确错误
  4. 充值回调 → 余额增加 → 重试成功

### 5.3 遥测验证

- `tests/integration/observability.test.ts`：
  - 官方 Provider 请求带 `provider_type: "official"`
  - 自定义 Provider 请求带 `provider_type: "custom"`
  - PostHog 收到两类维度的事件

## 6. 未来扩展

- **更多模型**：Qwen、GLM、Gemini（优先级低）
- **企业订阅**：团队共享额度、发票
- **API 管理**：用户生成子 token、限流策略
- **海外支付**：Stripe、PayPal（服务海外用户）
- **国内合规版**：对接审核服务、敏感词过滤

## 7. 开放决策（PR 待讨论）

1. **定价与套餐**：充值档位、订阅额度是否合理？加价比例过高/过低？
2. **支付商户**：谁持有微信支付/支付宝商户号？个人 vs 企业主体？
3. **ICP 备案**：域名是否需要备案？备案主体与进度？
4. **上游路由**：Claude 国内访问方案（香港节点 vs 国内代理商）？
5. **托管方案**：自建 vs 云服务（如阿里云 PAI）？成本与运维权衡？
6. **发布时间**：何时上线 MVP？充值/订阅先后顺序？

## 8. PR Checklist

- [ ] 客户端：新增 `"psyclaw"` Provider 预设
- [ ] 客户端：登录流程（token 输入与存储）
- [ ] 客户端：余额展示（Panel + CLI）
- [ ] 客户端：out-of-credit 提示与充值链接
- [ ] 客户端：遥测维度 `provider_type`
- [ ] 网关：认证中间件
- [ ] 网关：OpenAI 兼容代理
- [ ] 网关：上游路由表与加价计算
- [ ] 网关：余额扣费逻辑
- [ ] 网关：微信支付实现（Native + 回调）
- [ ] 网关：支付宝实现（当面付 + 回调）
- [ ] 网关：Stripe stub
- [ ] 网关：订单状态轮询 API
- [ ] 网关：订阅管理（stub，后续实现）
- [ ] 测试：自定义 Provider 不变性
- [ ] 测试：官方认证与计量
- [ ] 测试：支付回调幂等性
- [ ] 测试：遥测维度验证
- [ ] 文档：`apps/gateway/README.md`（部署、配置、环境变量）
- [ ] 文档：国内可访问性与合规待决事项
- [ ] 文档：定价策略待讨论

## 9. 里程碑

- **M1**：客户端集成（预设、登录、余额展示）+ 网关 MVP（认证、代理、扣费）
- **M2**：微信支付 + 支付宝完整流程（充值）
- **M3**：订阅功能
- **M4**：国内部署、ICP 备案、合规审查
