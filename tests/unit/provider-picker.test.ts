import { describe, expect, it, vi } from "vitest";
import { SecretInputComponent, TextInputComponent } from "../../src/tui/provider-picker.js";
import { PROVIDER_PRESETS } from "../../src/setup.js";

describe("Provider secret input", () => {
  it("completes only once when submit input is repeated", () => {
    const done = vi.fn();
    const component = new SecretInputComponent(
      "Provider",
      "TEST_API_KEY",
      { requestRender: vi.fn() } as never,
      { fg: (_color: string, text: string) => text, bold: (text: string) => text } as never,
      {
        matches: (data: string, action: string) => action === "tui.input.submit" && data === "\r",
      } as never,
      done,
    );
    component.handleInput("secret");
    component.handleInput("\r");
    component.handleInput("\r");
    expect(done).toHaveBeenCalledTimes(1);
    expect(done).toHaveBeenCalledWith({ type: "submit", value: "secret" });
  });
});

describe("Provider text input", () => {
  it("submits trimmed Base URL text", () => {
    const done = vi.fn();
    const component = new TextInputComponent(
      "Base URL",
      "hint",
      { requestRender: vi.fn() } as never,
      { fg: (_color: string, text: string) => text, bold: (text: string) => text } as never,
      {
        matches: (data: string, action: string) => action === "tui.input.submit" && data === "\r",
      } as never,
      done,
    );
    component.handleInput("https://api.example.com/v1");
    component.handleInput("\r");
    expect(done).toHaveBeenCalledWith({ type: "submit", value: "https://api.example.com/v1" });
  });
});

describe("custom provider preset", () => {
  it("keeps a dedicated custom OpenAI-compatible preset for /provider", () => {
    const custom = PROVIDER_PRESETS.find((preset) => preset.id === "custom");
    expect(custom).toEqual(expect.objectContaining({
      id: "custom",
      name: "自定义 OpenAI 兼容接口",
      api: "openai-completions",
      apiKeyEnv: "PSYCLAW_CUSTOM_API_KEY",
      models: [],
    }));
  });
});
