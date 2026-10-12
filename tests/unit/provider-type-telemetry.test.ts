import { describe, expect, it } from "vitest";
import { posthogAiGenerationProperties } from "../../src/observability/llm.js";

describe("Provider type 遥测维度", () => {
  const baseOptions = { distinctId: "test-user", sessionId: "test-session" };

  it("psyclaw provider 应标记为 official", () => {
    const properties = posthogAiGenerationProperties(
      {
        provider: "psyclaw",
        model: "deepseek-v4-flash",
        usage: { input: 100, output: 200 },
      },
      baseOptions,
    );

    expect(properties.provider_type).toBe("official");
  });

  it("自定义 provider 应标记为 custom", () => {
    const providers = ["deepseek", "openai", "anthropic", "custom", "ollama"];

    for (const provider of providers) {
      const properties = posthogAiGenerationProperties(
        {
          provider,
          model: "some-model",
          usage: { input: 100, output: 200 },
        },
        baseOptions,
      );

      expect(properties.provider_type).toBe("custom");
    }
  });

  it("明确指定 providerType 时应优先使用", () => {
    const properties = posthogAiGenerationProperties(
      {
        provider: "deepseek",
        model: "deepseek-v4-flash",
        usage: { input: 100, output: 200 },
        providerType: "official", // 显式指定
      },
      baseOptions,
    );

    expect(properties.provider_type).toBe("official");
  });

  it("未指定 provider 时应默认为 custom", () => {
    const properties = posthogAiGenerationProperties(
      {
        model: "unknown-model",
        usage: { input: 100, output: 200 },
      },
      baseOptions,
    );

    expect(properties.provider_type).toBe("custom");
  });

  it("provider_type 应出现在遥测属性中", () => {
    const properties = posthogAiGenerationProperties(
      {
        provider: "psyclaw",
        model: "deepseek-v4-flash",
        usage: { input: 100, output: 200 },
      },
      baseOptions,
    );

    expect(properties).toHaveProperty("provider_type");
    expect(typeof properties.provider_type).toBe("string");
  });
});
