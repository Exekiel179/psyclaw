/**
 * PsyClaw 官方网关服务入口
 */

import Fastify from "fastify";
import { loadConfig } from "./config.js";
import { createDbPool } from "./db/client.js";
import { JwtTokenService } from "./auth/token.js";
import { createAuthMiddleware } from "./auth/middleware.js";
import { PgBalanceService } from "./billing/balance.js";
import { OpenAIProxyHandler } from "./proxy/handler.js";

const config = loadConfig();
const fastify = Fastify({
  logger: {
    level: config.logLevel,
  },
});

// CORS 配置（允许客户端调用）
await fastify.register(import("@fastify/cors"), {
  origin: true, // 开发环境允许所有来源，生产环境应配置白名单
});

// Rate limiting（防止滥用）
await fastify.register(import("@fastify/rate-limit"), {
  max: 100,
  timeWindow: "1 minute",
});

// 初始化服务
const db = await createDbPool(config);
const tokenService = new JwtTokenService(config.jwt.secret);
const balanceService = new PgBalanceService(db);
const proxyHandler = new OpenAIProxyHandler(config, balanceService, db);
const authMiddleware = createAuthMiddleware(tokenService);

// 健康检查
fastify.get("/health", async () => {
  return { status: "ok", timestamp: new Date().toISOString() };
});

// 认证相关
fastify.post("/auth/login", async () => {
  throw new Error("登录功能待实现：微信扫码/手机号验证码");
});

// 账户查询（需要认证）
fastify.get("/account/balance", { preHandler: authMiddleware }, async (request) => {
  const userId = (request as never as { userId: string }).userId;
  const balance = await balanceService.getBalance(userId);

  return {
    balance: balance.balance,
    subscription: balance.subscription
      ? {
        plan_id: balance.subscription.planId,
        status: "active",
        expire_at: balance.subscription.expireAt.toISOString(),
        quota: {
          used: balance.subscription.quotaUsed,
          total: balance.subscription.quotaTotal,
          unit: "tokens",
        },
      }
      : null,
  };
});

// OpenAI 兼容代理（需要认证）
fastify.post("/v1/chat/completions", { preHandler: authMiddleware }, async (request, reply) => {
  await proxyHandler.handle(request, reply);
});

// 支付相关（临时占位）
fastify.post("/payment/topup", { preHandler: authMiddleware }, async (request, reply) => {
  const body = request.body as { amount: number; paymentMethod: "wechat" | "alipay" };

  if (!body.amount || !body.paymentMethod) {
    reply.code(400);
    return { error: "Missing required fields: amount, paymentMethod" };
  }

  reply.code(501);
  return { error: "Payment not implemented yet" };
});

fastify.get("/payment/order/:orderId", { preHandler: authMiddleware }, async (request) => {
  const { orderId } = request.params as { orderId: string };
  return { orderId, status: "unpaid" };
});

// 支付回调（无需认证）
fastify.post("/webhooks/wechat", async (request) => {
  return { code: "SUCCESS", message: "ok" };
});

fastify.post("/webhooks/alipay", async (request) => {
  return "success"; // 支付宝要求返回纯文本 "success"
});

// 启动服务
try {
  await fastify.listen({ port: config.port, host: "0.0.0.0" });
  fastify.log.info(`PsyClaw Gateway 启动成功: ${config.gateway.baseUrl}`);
  fastify.log.info(`环境: ${config.nodeEnv}`);
  fastify.log.info(`支付方式: 微信支付、支付宝${config.payment.stripe ? "、Stripe（次要）" : ""}`);
} catch (error) {
  fastify.log.error(error);
  process.exit(1);
}

// 优雅退出
const shutdown = async () => {
  fastify.log.info("收到退出信号，正在关闭服务...");
  await db.end();
  await fastify.close();
  process.exit(0);
};

process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
