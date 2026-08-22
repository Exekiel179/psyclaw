/**
 * Per-1M-token pricing used to (a) estimate cost from token usage and (b)
 * give Pi a real `cost` field so it records actual usage cost.
 *
 * USD values are approximate list prices for common providers; local
 * providers (ollama) cost 0. For display, Chinese providers also carry
 * official RMB (元) list prices; non-listed providers fall back to a fixed
 * USD→CNY rate so the panel can always show 人民币.
 */

export interface UsdPricing {
  input: number;
  output: number;
  cacheRead: number;
  cacheWrite: number;
}

export const DEFAULT_PRICING: UsdPricing = { input: 1, output: 3, cacheRead: 0.1, cacheWrite: 1 };

const DEEPSEEK: UsdPricing = { input: 0.27, output: 1.1, cacheRead: 0.07, cacheWrite: 0.27 };
const OPENAI: UsdPricing = { input: 1.25, output: 10, cacheRead: 0.125, cacheWrite: 1.25 };
const ANTHROPIC: UsdPricing = { input: 3, output: 15, cacheRead: 0.3, cacheWrite: 3.75 };
const QWEN: UsdPricing = { input: 0.5, output: 2, cacheRead: 0.05, cacheWrite: 0.5 };
const GLM: UsdPricing = { input: 0.5, output: 2, cacheRead: 0.05, cacheWrite: 0.5 };
const MOONSHOT: UsdPricing = { input: 0.3, output: 0.6, cacheRead: 0.03, cacheWrite: 0.3 };
const GOOGLE: UsdPricing = { input: 1.25, output: 5, cacheRead: 0.125, cacheWrite: 1.25 };
const LOCAL: UsdPricing = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 };

/** Exact match by provider id (lowercased). */
export const PROVIDER_PRICING: Record<string, UsdPricing> = {
  deepseek: DEEPSEEK,
  openai: OPENAI,
  anthropic: ANTHROPIC,
  qwen: QWEN,
  dashscope: QWEN,
  zhipu: GLM,
  glm: GLM,
  moonshot: MOONSHOT,
  kimi: MOONSHOT,
  google: GOOGLE,
  gemini: GOOGLE,
  ollama: LOCAL,
  local: LOCAL,
};

/** Family keys that match by substring (for model ids like "gpt-5.5"). */
const FAMILY_KEYS: Array<[string[], UsdPricing]> = [
  [["deepseek"], DEEPSEEK],
  [["gpt", "openai"], OPENAI],
  [["claude", "anthropic"], ANTHROPIC],
  [["qwen", "dashscope"], QWEN],
  [["glm", "zhipu"], GLM],
  [["moonshot", "kimi"], MOONSHOT],
  [["gemini", "google"], GOOGLE],
  [["ollama", "local"], LOCAL],
];

/** Resolve pricing for a provider id (exact) or a provider/model string (family match). */
export function pricingFor(provider: string, model: string): UsdPricing {
  const normalized = provider.trim().toLowerCase();
  const exact = PROVIDER_PRICING[normalized];
  if (exact !== undefined) return exact;
  const haystack = `${normalized} ${model.toLowerCase()}`;
  for (const [keys, pricing] of FAMILY_KEYS) {
    if (keys.some((key) => haystack.includes(key))) return pricing;
  }
  return DEFAULT_PRICING;
}

/** Fixed USD→CNY fallback for providers without official RMB list prices. */
export const USD_CNY_RATE = 7.2;

/** Official RMB (元) list prices per 1M tokens for Chinese providers. */
const CNY_PRICING: Record<string, UsdPricing> = {
  deepseek: { input: 2, output: 8, cacheRead: 0.5, cacheWrite: 2 },
  qwen: { input: 1.6, output: 6.4, cacheRead: 0.16, cacheWrite: 1.6 },
  dashscope: { input: 1.6, output: 6.4, cacheRead: 0.16, cacheWrite: 1.6 },
  zhipu: { input: 5, output: 5, cacheRead: 0.5, cacheWrite: 5 },
  glm: { input: 5, output: 5, cacheRead: 0.5, cacheWrite: 5 },
  moonshot: { input: 12, output: 12, cacheRead: 1.2, cacheWrite: 12 },
  kimi: { input: 12, output: 12, cacheRead: 1.2, cacheWrite: 12 },
  ollama: LOCAL,
  local: LOCAL,
};

/** CNY pricing for a provider, or null when the provider has no official RMB price. */
export function pricingCnyFor(provider: string, _model: string): UsdPricing | null {
  const normalized = provider.trim().toLowerCase();
  const exact = CNY_PRICING[normalized];
  if (exact !== undefined) return exact;
  // Family fallback for Chinese providers matched by model string.
  const haystack = `${normalized} ${_model.toLowerCase()}`;
  const families: Array<[string[], UsdPricing]> = [
    [["deepseek"], CNY_PRICING.deepseek!],
    [["qwen", "dashscope"], CNY_PRICING.qwen!],
    [["glm", "zhipu"], CNY_PRICING.zhipu!],
    [["moonshot", "kimi"], CNY_PRICING.moonshot!],
    [["ollama", "local"], LOCAL],
  ];
  for (const [keys, pricing] of families) {
    if (keys.some((key) => haystack.includes(key))) return pricing;
  }
  return null;
}

function estimateWith(usage: { input?: unknown; output?: unknown; cacheRead?: unknown; cacheWrite?: unknown }, pricing: UsdPricing): number {
  const num = (value: unknown): number => (typeof value === "number" && Number.isFinite(value) ? value : 0);
  return (
    num(usage.input) * pricing.input +
    num(usage.output) * pricing.output +
    num(usage.cacheRead) * pricing.cacheRead +
    num(usage.cacheWrite) * pricing.cacheWrite
  ) / 1e6;
}

/** Estimated cost in USD for one usage record. */
export function estimateUsageCost(
  usage: { input?: unknown; output?: unknown; cacheRead?: unknown; cacheWrite?: unknown },
  provider: string,
  model: string,
): number {
  return estimateWith(usage, pricingFor(provider, model));
}

/** Estimated cost in 人民币 (CNY) for one usage record: official RMB list price where available, else USD×rate. */
export function estimateUsageCostCny(
  usage: { input?: unknown; output?: unknown; cacheRead?: unknown; cacheWrite?: unknown },
  provider: string,
  model: string,
): number {
  const cny = pricingCnyFor(provider, model);
  return cny !== null ? estimateWith(usage, cny) : estimateUsageCost(usage, provider, model) * USD_CNY_RATE;
}
