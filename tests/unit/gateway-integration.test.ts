import { describe, expect, it } from "vitest";
import { PROVIDER_PRESETS } from "../../src/setup.js";
import { UPSTREAM_MODELS, getUpstreamConfig, calculateCost } from "../../apps/gateway/src/proxy/upstream.js";

describe("PsyClaw 官方网关集成", () => {
  describe("客户端 Provider 预设", () => {
    it("应包含 psyclaw 官方预设", () => {
      const psyclawPreset = PROVIDER_PRESETS.find((p) => p.id === "psyclaw");
      expect(psyclawPreset).toBeDefined();
      expect(psyclawPreset).toMatchObject({
        id: "psyclaw",
        name: "PsyClaw 官方",
        baseUrl: "https://api.psyclaw.ai/v1",
        api: "openai-completions",
        apiKeyEnv: "PSYCLAW_GATEWAY_TOKEN",
      });
    });

    it("psyclaw 预设应包含支持的模型", () => {
      const psyclawPreset = PROVIDER_PRESETS.find((p) => p.id === "psyclaw");
      expect(psyclawPreset?.models).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ id: "deepseek-v4-flash" }),
          expect.objectContaining({ id: "deepseek-v4-pro" }),
          expect.objectContaining({ id: "claude-sonnet-4-6" }),
        ]),
      );
    });

    it("不应影响现有 Provider 预设顺序（custom 仍在末尾）", () => {
      const customIndex = PROVIDER_PRESETS.findIndex((p) => p.id === "custom");
      expect(customIndex).toBeGreaterThan(-1);
      expect(customIndex).toBe(PROVIDER_PRESETS.length - 1);
    });
  });

  describe("网关上游路由", () => {
    it("支持的模型应有完整上游配置", () => {
      const models = ["deepseek-v4-flash", "deepseek-v4-pro", "claude-sonnet-4-6"];
      for (const model of models) {
        const config = getUpstreamConfig(model);
        expect(config).toBeDefined();
        expect(config?.provider).toMatch(/^(deepseek|anthropic)$/);
        expect(config?.upstreamModel).toBeTruthy();
        expect(config?.baseUrl).toMatch(/^https:\/\//);
        expect(config?.pricingMultiplier).toBeGreaterThan(1);
      }
    });

    it("DeepSeek 模型应路由到 DeepSeek 上游", () => {
      const flashConfig = getUpstreamConfig("deepseek-v4-flash");
      expect(flashConfig?.provider).toBe("deepseek");
      expect(flashConfig?.upstreamModel).toBe("deepseek-v4-flash");
      expect(flashConfig?.baseUrl).toBe("https://api.deepseek.com");
    });

    it("Claude 模型应路由到 Anthropic 上游", () => {
      const claudeConfig = getUpstreamConfig("claude-sonnet-4-6");
      expect(claudeConfig?.provider).toBe("anthropic");
      expect(claudeConfig?.upstreamModel).toBe("claude-sonnet-4-6");
      expect(claudeConfig?.baseUrl).toBe("https://api.anthropic.com");
    });
  });

  describe("计价逻辑", () => {
    it("DeepSeek V4 Flash 应按 1.5x 加价计费", () => {
      const cost = calculateCost("deepseek-v4-flash", {
        input: 1_000_000, // 100 万 input tokens
        output: 1_000_000, // 100 万 output tokens
      });
      // 输入: 1M * 3.0 = 3.0 元
      // 输出: 1M * 12.0 = 12.0 元
      // 总计: 15.0 元 = 1500 分
      expect(cost).toBe(1500);
    });

    it("Claude Sonnet 应按 2.0x 加价计费", () => {
      const cost = calculateCost("claude-sonnet-4-6", {
        input: 1_000_000,
        output: 100_000, // 10 万 output tokens
      });
      // 输入: 1M * 43.2 = 43.2 元
      // 输出: 0.1M * 216.0 = 21.6 元
      // 总计: 64.8 元 = 6480 分（向上取整为 6481 分）
      expect(cost).toBe(6481);
    });

    it("应支持 cache read/write tokens", () => {
      const cost = calculateCost("deepseek-v4-flash", {
        input: 500_000,
        output: 500_000,
        cacheRead: 1_000_000,
        cacheWrite: 100_000,
      });
      // 输入: 0.5M * 3.0 = 1.5
      // 输出: 0.5M * 12.0 = 6.0
      // cache read: 1M * 0.75 = 0.75
      // cache write: 0.1M * 3.0 = 0.3
      // 总计: 8.55 元 = 855 分（向上取整为 856 分）
      expect(cost).toBe(856);
    });

    it("不支持的模型应抛出错误", () => {
      expect(() => calculateCost("unknown-model", { input: 1000 })).toThrow("Unsupported model");
    });
  });

  describe("网关模型与客户端一致性", () => {
    it("客户端预设的模型应全部存在于网关路由表", () => {
      const psyclawPreset = PROVIDER_PRESETS.find((p) => p.id === "psyclaw");
      const clientModels = psyclawPreset?.models.map((m) => m.id) ?? [];
      const gatewayModels = Object.keys(UPSTREAM_MODELS);

      for (const clientModel of clientModels) {
        expect(gatewayModels).toContain(clientModel);
      }
    });

    it("网关路由表的模型应全部出现在客户端预设", () => {
      const psyclawPreset = PROVIDER_PRESETS.find((p) => p.id === "psyclaw");
      const clientModels = psyclawPreset?.models.map((m) => m.id) ?? [];
      const gatewayModels = Object.keys(UPSTREAM_MODELS);

      for (const gatewayModel of gatewayModels) {
        expect(clientModels).toContain(gatewayModel);
      }
    });
  });
});
