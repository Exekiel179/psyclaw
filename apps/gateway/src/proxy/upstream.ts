/**
 * 上游 Provider 路由表和计价配置
 */

export interface UpstreamModelConfig {
  provider: "deepseek" | "anthropic";
  upstreamModel: string; // 上游实际模型 ID
  apiKeyEnv: string; // 环境变量名
  baseUrl: string;
  pricingMultiplier: number; // 相对上游官方价格的加价比例
  // CNY 价格（每 1M tokens）
  inputPriceCny: number;
  outputPriceCny: number;
  cacheReadPriceCny: number;
  cacheWritePriceCny: number;
}

/**
 * 网关支持的模型列表及其上游路由配置
 * 价格以 CNY 计（已包含加价）
 */
export const UPSTREAM_MODELS: Record<string, UpstreamModelConfig> = {
  "deepseek-v4-flash": {
    provider: "deepseek",
    upstreamModel: "deepseek-v4-flash",
    apiKeyEnv: "UPSTREAM_DEEPSEEK_API_KEY",
    baseUrl: "https://api.deepseek.com",
    pricingMultiplier: 1.5,
    inputPriceCny: 3.0, // 上游 2.0 * 1.5
    outputPriceCny: 12.0, // 上游 8.0 * 1.5
    cacheReadPriceCny: 0.75, // 上游 0.5 * 1.5
    cacheWritePriceCny: 3.0,
  },
  "deepseek-v4-pro": {
    provider: "deepseek",
    upstreamModel: "deepseek-v4-pro",
    apiKeyEnv: "UPSTREAM_DEEPSEEK_API_KEY",
    baseUrl: "https://api.deepseek.com",
    pricingMultiplier: 1.5,
    inputPriceCny: 3.0,
    outputPriceCny: 12.0,
    cacheReadPriceCny: 0.75,
    cacheWritePriceCny: 3.0,
  },
  "claude-sonnet-4-6": {
    provider: "anthropic",
    upstreamModel: "claude-sonnet-4-6",
    apiKeyEnv: "UPSTREAM_ANTHROPIC_API_KEY",
    baseUrl: "https://api.anthropic.com",
    pricingMultiplier: 2.0,
    inputPriceCny: 43.2, // 上游 21.6 * 2.0
    outputPriceCny: 216.0, // 上游 108.0 * 2.0
    cacheReadPriceCny: 4.32,
    cacheWritePriceCny: 54.0,
  },
};

/** 根据网关模型 ID 获取上游配置 */
export function getUpstreamConfig(model: string): UpstreamModelConfig | undefined {
  return UPSTREAM_MODELS[model];
}

/** 计算费用（CNY 分） */
export function calculateCost(
  model: string,
  usage: {
    input?: number;
    output?: number;
    cacheRead?: number;
    cacheWrite?: number;
  },
): number {
  const config = getUpstreamConfig(model);
  if (!config) {
    throw new Error(`Unsupported model: ${model}`);
  }

  const inputTokens = usage.input ?? 0;
  const outputTokens = usage.output ?? 0;
  const cacheReadTokens = usage.cacheRead ?? 0;
  const cacheWriteTokens = usage.cacheWrite ?? 0;

  // 计算费用（元）
  const costYuan =
    (inputTokens * config.inputPriceCny) / 1_000_000 +
    (outputTokens * config.outputPriceCny) / 1_000_000 +
    (cacheReadTokens * config.cacheReadPriceCny) / 1_000_000 +
    (cacheWriteTokens * config.cacheWritePriceCny) / 1_000_000;

  // 转换为分
  return Math.ceil(costYuan * 100);
}
