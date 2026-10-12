/**
 * PsyClaw 官方网关服务入口
 */

import Fastify from "fastify";
import { loadConfig } from "./config.js";

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

// 健康检查
fastify.get("/health", async () => {
  return { status: "ok", timestamp: new Date().toISOString() };
});

// TODO: 注册路由模块
// - /auth/* - 认证相关（登录、token）
// - /account/* - 账户查询（余额、订阅）
// - /v1/chat/completions - OpenAI 兼容代理
// - /payment/* - 支付相关（充值、订阅）
// - /webhooks/* - 支付回调

// 临时占位路由（待实现）
fastify.post("/auth/login", async () => {
  throw new Error("登录功能待实现：微信扫码/手机号验证码");
});

fastify.get("/account/balance", async (request) => {
  const authHeader = request.headers.authorization;
  if (!authHeader) {
    return { error: "Missing Authorization header" };
  }
  // TODO: 验证 token，查询余额
  return {
    balance: 12345,
    subscription: null,
  };
});

fastify.post("/v1/chat/completions", async (request, reply) => {
  const authHeader = request.headers.authorization;
  if (!authHeader) {
    reply.code(401);
    return { error: { message: "Missing Authorization header", type: "invalid_request_error" } };
  }

  // TODO: 代理逻辑
  reply.code(501);
  return { error: { message: "Proxy not implemented yet", type: "server_error" } };
});

fastify.post("/payment/topup", async (request, reply) => {
  const body = request.body as { amount: number; paymentMethod: "wechat" | "alipay" };

  if (!body.amount || !body.paymentMethod) {
    reply.code(400);
    return { error: "Missing required fields: amount, paymentMethod" };
  }

  // TODO: 创建支付订单
  reply.code(501);
  return { error: "Payment not implemented yet" };
});

fastify.get("/payment/order/:orderId", async (request) => {
  const { orderId } = request.params as { orderId: string };
  // TODO: 查询订单状态
  return { orderId, status: "unpaid" };
});

fastify.post("/webhooks/wechat", async (request) => {
  // TODO: 处理微信支付回调
  return { code: "SUCCESS", message: "ok" };
});

fastify.post("/webhooks/alipay", async (request) => {
  // TODO: 处理支付宝回调
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
  await fastify.close();
  process.exit(0);
};

process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
