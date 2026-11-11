/**
 * 数据库表结构定义（PostgreSQL）
 */

export interface User {
  id: string; // UUID
  phone?: string; // 手机号（脱敏存储，仅用于登录）
  wechat_openid?: string; // 微信 OpenID
  balance: number; // 余额（CNY 分）
  created_at: Date;
  updated_at: Date;
}

export interface Transaction {
  id: string; // UUID
  user_id: string;
  type: "recharge" | "deduction" | "refund" | "bonus";
  amount: number; // CNY 分（正数为入账，负数为扣款）
  balance_before: number;
  balance_after: number;
  order_id?: string; // 关联到充值订单
  usage_log_id?: string; // 关联到使用记录
  description: string;
  created_at: Date;
}

export interface PaymentOrder {
  id: string; // ord_xxx
  user_id: string;
  type: "topup" | "subscription";
  amount: number; // CNY 分
  payment_method: "wechat" | "alipay" | "stripe";
  status: "unpaid" | "paid" | "expired" | "refunded";
  transaction_id?: string; // 第三方支付平台交易号
  qr_code_url?: string; // 支付二维码内容
  h5_url?: string; // H5 支付链接
  expire_at: Date;
  paid_at?: Date;
  created_at: Date;
  updated_at: Date;
}

export interface Subscription {
  id: string; // UUID
  user_id: string;
  plan_id: string; // "monthly" | "yearly"
  status: "active" | "expired" | "canceled";
  start_at: Date;
  expire_at: Date;
  auto_renew: boolean;
  quota_used: number; // 已使用 token 数
  quota_total: number; // 总额度
  created_at: Date;
  updated_at: Date;
}

export interface UsageLog {
  id: string; // UUID
  user_id: string;
  model: string; // 网关模型 ID
  upstream_model: string; // 上游模型 ID
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  cost_cny: number; // 扣费金额（CNY 分）
  upstream_cost_cny: number; // 上游成本（CNY 分）
  margin_cny: number; // 利润（CNY 分）
  latency_ms: number; // 请求延迟
  error: boolean;
  error_message?: string;
  created_at: Date;
}

/** 数据库初始化 SQL */
export const SCHEMA_SQL = `
CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  phone VARCHAR(20) UNIQUE,
  wechat_openid VARCHAR(128) UNIQUE,
  balance INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS transactions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id),
  type VARCHAR(20) NOT NULL,
  amount INTEGER NOT NULL,
  balance_before INTEGER NOT NULL,
  balance_after INTEGER NOT NULL,
  order_id VARCHAR(64),
  usage_log_id UUID,
  description TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_transactions_user_id ON transactions(user_id);
CREATE INDEX idx_transactions_created_at ON transactions(created_at);

CREATE TABLE IF NOT EXISTS payment_orders (
  id VARCHAR(64) PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id),
  type VARCHAR(20) NOT NULL,
  amount INTEGER NOT NULL,
  payment_method VARCHAR(20) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'unpaid',
  transaction_id VARCHAR(128),
  qr_code_url TEXT,
  h5_url TEXT,
  expire_at TIMESTAMP NOT NULL,
  paid_at TIMESTAMP,
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_payment_orders_user_id ON payment_orders(user_id);
CREATE INDEX idx_payment_orders_status ON payment_orders(status);

CREATE TABLE IF NOT EXISTS subscriptions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id),
  plan_id VARCHAR(32) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'active',
  start_at TIMESTAMP NOT NULL,
  expire_at TIMESTAMP NOT NULL,
  auto_renew BOOLEAN NOT NULL DEFAULT FALSE,
  quota_used BIGINT NOT NULL DEFAULT 0,
  quota_total BIGINT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_subscriptions_user_id ON subscriptions(user_id);
CREATE INDEX idx_subscriptions_status ON subscriptions(status);

CREATE TABLE IF NOT EXISTS usage_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id),
  model VARCHAR(64) NOT NULL,
  upstream_model VARCHAR(64) NOT NULL,
  input_tokens INTEGER NOT NULL,
  output_tokens INTEGER NOT NULL,
  cache_read_tokens INTEGER NOT NULL DEFAULT 0,
  cache_write_tokens INTEGER NOT NULL DEFAULT 0,
  cost_cny INTEGER NOT NULL,
  upstream_cost_cny INTEGER NOT NULL,
  margin_cny INTEGER NOT NULL,
  latency_ms INTEGER NOT NULL,
  error BOOLEAN NOT NULL DEFAULT FALSE,
  error_message TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_usage_logs_user_id ON usage_logs(user_id);
CREATE INDEX idx_usage_logs_created_at ON usage_logs(created_at);
`;
