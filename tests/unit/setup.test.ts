import { access, mkdir, mkdtemp, readFile, utimes, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { hasConfiguredProvider, providerCredentialSource, PROVIDER_PRESETS, saveProviderConfig, setupProviders, decideProviderKeyPrompt, missingApiKeyUserMessage } from "../../src/setup.js";

describe("provider setup and first-run detection", () => {
  it("reports unconfigured before setup and configured after", async () => {
    const agentDir = await mkdtemp(join(tmpdir(), "psyclaw-setup-"));
    const envNames = PROVIDER_PRESETS.map((preset) => preset.apiKeyEnv);
    const previous = new Map(envNames.map((name) => [name, process.env[name]]));
    for (const name of envNames) delete process.env[name];
    try {
      await expect(hasConfiguredProvider({ agentDir })).resolves.toBe(false);
      const result = await setupProviders({ agentDir, providers: ["deepseek"] });
      expect(result.providers).toEqual(["deepseek"]);
      await expect(hasConfiguredProvider({ agentDir })).resolves.toBe(true);
    } finally {
      for (const [name, value] of previous) {
        if (value === undefined) delete process.env[name]; else process.env[name] = value;
      }
    }
  });

  it("recognizes a built-in provider credential without models.json", async () => {
    const agentDir = await mkdtemp(join(tmpdir(), "psyclaw-setup-"));
    const previous = process.env.OPENAI_API_KEY;
    process.env.OPENAI_API_KEY = "test-secret-never-returned";
    try {
      await expect(hasConfiguredProvider({ agentDir })).resolves.toBe(true);
    } finally {
      if (previous === undefined) delete process.env.OPENAI_API_KEY;
      else process.env.OPENAI_API_KEY = previous;
    }
  });

  it("writes only environment-variable references, never a literal API key", async () => {
    const agentDir = await mkdtemp(join(tmpdir(), "psyclaw-setup-"));
    const result = await setupProviders({ agentDir });
    const text = await readFile(result.path, "utf8");
    for (const preset of PROVIDER_PRESETS) {
      expect(text).toContain(`$${preset.apiKeyEnv}`);
    }
    expect(text).not.toMatch(/sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}/);
  });

  it("merges into existing providers without clobbering them", async () => {
    const agentDir = await mkdtemp(join(tmpdir(), "psyclaw-setup-"));
    await setupProviders({ agentDir, providers: ["deepseek"] });
    const second = await setupProviders({ agentDir, providers: ["openai"] });
    expect(second.providers).toEqual(["openai"]);
    const { readJson } = await import("node:fs/promises");
    const parsed = JSON.parse(await readFile(second.path, "utf8")) as { providers: Record<string, unknown> };
    expect(Object.keys(parsed.providers).sort()).toEqual(["deepseek", "openai"]);
  });

  it("does not create credential storage without an explicitly supplied key", async () => {
    const agentDir = await mkdtemp(join(tmpdir(), "psyclaw-setup-"));
    const preset = PROVIDER_PRESETS.find((item) => item.id === "google")!;
    await saveProviderConfig(preset, { agentDir });
    await expect(access(join(agentDir, "auth.json"))).rejects.toThrow();
  });

  it("includes the Google Gemini preset", () => {
    expect(PROVIDER_PRESETS).toContainEqual(expect.objectContaining({
      id: "google",
      name: "Google Gemini",
      apiKeyEnv: "GEMINI_API_KEY",
      models: expect.arrayContaining([expect.objectContaining({ id: "gemini-2.5-pro" })]),
    }));
  });

  it("detects a process environment credential without exposing it", async () => {
    const previous = process.env.GEMINI_API_KEY;
    process.env.GEMINI_API_KEY = "test-secret-never-returned";
    try {
      await expect(providerCredentialSource({ id: "google", apiKeyEnv: "GEMINI_API_KEY" })).resolves.toBe("process-env");
    } finally {
      if (previous === undefined) delete process.env.GEMINI_API_KEY;
      else process.env.GEMINI_API_KEY = previous;
    }
  });

  it("fails closed instead of overwriting a corrupt provider catalog", async () => {
    const agentDir = await mkdtemp(join(tmpdir(), "psyclaw-setup-"));
    const modelsPath = join(agentDir, "models.json");
    await writeFile(modelsPath, "{broken", "utf8");
    await expect(setupProviders({ agentDir, providers: ["google"] })).rejects.toThrow();
    await expect(readFile(modelsPath, "utf8")).resolves.toBe("{broken");
  });

  it("recovers a stale provider catalog lock", async () => {
    const agentDir = await mkdtemp(join(tmpdir(), "psyclaw-setup-"));
    const lockPath = join(agentDir, "models.json.psyclaw.lock");
    await mkdir(lockPath);
    const old = new Date(Date.now() - 60_000);
    await utimes(lockPath, old, old);
    await expect(setupProviders({ agentDir, providers: ["google"] })).resolves.toMatchObject({ providers: ["google"] });
    await expect(access(lockPath)).rejects.toThrow();
  });

  it("stores a directly entered key only in the user auth store", async () => {
    const agentDir = await mkdtemp(join(tmpdir(), "psyclaw-setup-"));
    const preset = PROVIDER_PRESETS.find((item) => item.id === "google")!;
    const result = await saveProviderConfig({ ...preset, apiKey: "direct-entry-secret" }, { agentDir });
    expect(await readFile(result.path, "utf8")).not.toContain("direct-entry-secret");
    expect(await readFile(join(agentDir, "auth.json"), "utf8")).toContain("direct-entry-secret");
    await expect(providerCredentialSource(preset, { agentDir })).resolves.toBe("auth-store");
  });
});

describe("provider key prompt decisions", () => {
  it("asks the user to enter a key when none exists, without treating it as a crash", () => {
    expect(decideProviderKeyPrompt("", "missing", "OPENCODE_API_KEY")).toEqual({
      kind: "need-key",
      message: missingApiKeyUserMessage("OPENCODE_API_KEY"),
    });
    expect(missingApiKeyUserMessage("OPENCODE_API_KEY")).toBe("未找到 OPENCODE_API_KEY；请输入 API Key 后再继续");
  });

  it("keeps an existing credential on empty submit and cancels when the prompt is dismissed", () => {
    expect(decideProviderKeyPrompt("", "process-env", "OPENCODE_API_KEY")).toEqual({ kind: "proceed" });
    expect(decideProviderKeyPrompt(undefined, "missing", "OPENCODE_API_KEY")).toEqual({ kind: "cancel" });
    expect(decideProviderKeyPrompt("sk-test", "missing", "OPENCODE_API_KEY")).toEqual({
      kind: "proceed",
      apiKey: "sk-test",
    });
  });
});
