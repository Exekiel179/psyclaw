import { describe, expect, it } from "vitest";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  ensureAcademicModeKeybindings,
  PI_DEFAULT_THINKING_CYCLE_KEY,
  PSYCLAW_THINKING_CYCLE_KEY,
} from "../../src/ars/keybindings.js";

describe("ensureAcademicModeKeybindings", () => {
  it("moves thinking cycle off shift+tab when unset or default", async () => {
    const dir = await mkdtemp(join(tmpdir(), "psyclaw-kb-"));
    const first = await ensureAcademicModeKeybindings(dir);
    expect(first.updated).toBe(true);
    expect(first.thinkingCycleKey).toBe(PSYCLAW_THINKING_CYCLE_KEY);
    const written = JSON.parse(await readFile(join(dir, "keybindings.json"), "utf8")) as Record<string, string>;
    expect(written["app.thinking.cycle"]).toBe(PSYCLAW_THINKING_CYCLE_KEY);

    await writeFile(join(dir, "keybindings.json"), `${JSON.stringify({ "app.thinking.cycle": PI_DEFAULT_THINKING_CYCLE_KEY }, null, 2)}\n`);
    const second = await ensureAcademicModeKeybindings(dir);
    expect(second.updated).toBe(true);
  });

  it("migrates legacy ctrl+shift+tab to ctrl+shift+t", async () => {
    const dir = await mkdtemp(join(tmpdir(), "psyclaw-kb-"));
    await writeFile(join(dir, "keybindings.json"), `${JSON.stringify({ "app.thinking.cycle": "ctrl+shift+tab" }, null, 2)}\n`);
    const result = await ensureAcademicModeKeybindings(dir);
    expect(result.updated).toBe(true);
    expect(result.thinkingCycleKey).toBe("ctrl+shift+t");
  });

  it("preserves a custom thinking-cycle binding", async () => {
    const dir = await mkdtemp(join(tmpdir(), "psyclaw-kb-"));
    await writeFile(join(dir, "keybindings.json"), `${JSON.stringify({ "app.thinking.cycle": "alt+t" }, null, 2)}\n`);
    const result = await ensureAcademicModeKeybindings(dir);
    expect(result.updated).toBe(false);
    expect(result.thinkingCycleKey).toBe("alt+t");
    const written = JSON.parse(await readFile(join(dir, "keybindings.json"), "utf8")) as Record<string, string>;
    expect(written["app.thinking.cycle"]).toBe("alt+t");
  });
});
