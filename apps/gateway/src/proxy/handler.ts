/**
 * OpenAI 兼容代理：转发请求到上游 Provider，计量并扣费
 */

import type { FastifyRequest, FastifyReply } from "fastify";
import type { Pool } from "pg";
import type { AuthenticatedRequest } from "../auth/middleware.js";
import type { BalanceService } from "../billing/balance.js";
import { getUpstreamConfig, calculateCost } from "./upstream.js";
import type { GatewayConfig } from "../config.js";

export interface CompletionRequest {
  model: string;
  messages: Array<{ role: string; content: string }>;
  stream?: boolean;
  temperature?: number;
  max_tokens?: number;
  [key: string]: unknown;
}

export interface CompletionResponse {
  id: string;
  object: string;
  created: number;
  model: string;
  choices: Array<{
    index: number;
    message: { role: string; content: string };
    finish_reason: string;
  }>;
  usage: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
}

export interface ProxyHandler {
  handle(request: FastifyRequest, reply: FastifyReply): Promise<void>;
}

export class OpenAIProxyHandler implements ProxyHandler {
  constructor(
    private readonly config: GatewayConfig,
    private readonly balanceService: BalanceService,
    private readonly db: Pool,
  ) {}

  async handle(request: FastifyRequest, reply: FastifyReply): Promise<void> {
    const userId = (request as AuthenticatedRequest).userId;
    const body = request.body as CompletionRequest;

    if (!body.model) {
      reply.code(400).send({
        error: {
          message: "Missing required field: model",
          type: "invalid_request_error",
          code: "missing_model",
        },
      });
      return;
    }

    // 获取上游配置
    const upstreamConfig = getUpstreamConfig(body.model);
    if (!upstreamConfig) {
      reply.code(400).send({
        error: {
          message: `Unsupported model: ${body.model}`,
          type: "invalid_request_error",
          code: "unsupported_model",
        },
      });
      return;
    }

    // 检查余额
    const balanceInfo = await this.balanceService.getBalance(userId);
    if (!balanceInfo.hasActiveSubscription && balanceInfo.balance <= 0) {
      reply.code(402).send({
        error: {
          message: "余额不足，请充值或订阅",
          type: "insufficient_credits",
          code: "balance_low",
          balance: balanceInfo.balance,
          topup_url: `${this.config.gateway.baseUrl}/console/topup`,
        },
      });
      return;
    }

    // 获取上游 API Key
    const apiKey = this.getUpstreamApiKey(upstreamConfig.apiKeyEnv);
    if (!apiKey) {
      reply.code(500).send({
        error: {
          message: "Upstream provider not configured",
          type: "server_error",
          code: "upstream_config_error",
        },
      });
      return;
    }

    // 构造上游请求
    const upstreamBody = {
      ...body,
      model: upstreamConfig.upstreamModel,
    };

    const startTime = Date.now();
    let upstreamResponse: CompletionResponse;
    let error = false;
    let errorMessage: string | undefined;

    try {
      // 调用上游 API（DeepSeek 使用 OpenAI 兼容接口）
      const response = await fetch(`${upstreamConfig.baseUrl}/v1/chat/completions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${apiKey}`,
        },
        body: JSON.stringify(upstreamBody),
      });

      if (!response.ok) {
        error = true;
        errorMessage = `Upstream error: ${response.status} ${response.statusText}`;
        const errorBody = await response.text();
        reply.code(response.status).send({
          error: {
            message: errorMessage,
            type: "upstream_error",
            code: "upstream_failed",
            upstream_body: errorBody.slice(0, 500),
          },
        });
        return;
      }

      upstreamResponse = await response.json() as CompletionResponse;
    } catch (err) {
      error = true;
      errorMessage = err instanceof Error ? err.message : "Unknown upstream error";
      reply.code(500).send({
        error: {
          message: errorMessage,
          type: "upstream_error",
          code: "upstream_request_failed",
        },
      });
      return;
    }

    const latencyMs = Date.now() - startTime;

    // 计算费用
    const usage = upstreamResponse.usage;
    const costCny = calculateCost(body.model, {
      input: usage.prompt_tokens,
      output: usage.completion_tokens,
    });

    // 计算上游成本（按原价 / 加价比例）
    const upstreamCostCny = Math.ceil(costCny / upstreamConfig.pricingMultiplier);
    const marginCny = costCny - upstreamCostCny;

    // 记录使用日志
    const usageLogResult = await this.db.query(
      `INSERT INTO usage_logs
       (user_id, model, upstream_model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
        cost_cny, upstream_cost_cny, margin_cny, latency_ms, error, error_message)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
       RETURNING id`,
      [
        userId,
        body.model,
        upstreamConfig.upstreamModel,
        usage.prompt_tokens,
        usage.completion_tokens,
        0,
        0,
        costCny,
        upstreamCostCny,
        marginCny,
        latencyMs,
        error,
        errorMessage ?? null,
      ],
    );

    const usageLogId = usageLogResult.rows[0]!.id as string;

    // 扣费
    try {
      await this.balanceService.deduct(userId, costCny, usageLogId);
    } catch (deductError) {
      // 扣费失败（余额不足），但已经调用了上游，记录日志并返回 402
      reply.code(402).send({
        error: {
          message: "余额不足，请充值",
          type: "insufficient_credits",
          code: "balance_insufficient",
          cost: costCny,
          topup_url: `${this.config.gateway.baseUrl}/console/topup`,
        },
      });
      return;
    }

    // 返回上游响应
    reply.send(upstreamResponse);
  }

  private getUpstreamApiKey(envName: string): string | undefined {
    return process.env[envName];
  }
}
