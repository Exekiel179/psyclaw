import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { hasConfiguredProvider, PROVIDER_PRESETS, setupProviders } from "../../src/setup.js";

describe("provider setup and first-run detection", () => {
  it("reports unconfigured before setup and configured after", async () => {
    const agentDir = await mkdtemp(join(tmpdir(), "psyclaw-setup-"));
    await expect(hasConfiguredProvider({ agentDir })).resolves.toBe(false);
    const result = await setupProviders({ agentDir, providers: ["deepseek"] });
    expect(result.providers).toEqual(["deepseek"]);
    await expect(hasConfiguredProvider({ agentDir })).resolves.toBe(true);
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
});
