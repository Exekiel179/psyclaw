import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { ensurePsyClawTheme, ensureQuietStartup, PSYCLAW_IDENTITY_PROMPT } from "../../src/branding.js";
import { PSYCLAW_THEME_NAME } from "../../src/psyclaw-theme.js";

describe("psyclaw identity prompt", () => {
  it("identifies as PsyClaw and accurately discloses the official Pi runtime", () => {
    expect(PSYCLAW_IDENTITY_PROMPT).toContain("psyclaw");
    expect(PSYCLAW_IDENTITY_PROMPT).toContain("official Pi coding-agent harness");
    expect(PSYCLAW_IDENTITY_PROMPT).toContain("disclose that runtime accurately");
  });
});

describe("ensureQuietStartup", () => {
  it("writes quietStartup once (default false = show version header) and merges", async () => {
    const dir = await mkdtemp(join(tmpdir(), "psyclaw-branding-"));
    const path = join(dir, "agent", "settings.json");
    try {
      const first = await ensureQuietStartup(path);
      expect(first.wrote).toBe(true);
      expect(JSON.parse(await readFile(path, "utf8"))).toMatchObject({ quietStartup: false });

      const second = await ensureQuietStartup(path);
      expect(second.wrote).toBe(false);

      // An explicit `true` flips it (opt into the quiet screen).
      const flipped = await ensureQuietStartup(path, true);
      expect(flipped.wrote).toBe(true);
      expect(JSON.parse(await readFile(path, "utf8"))).toMatchObject({ quietStartup: true });

      // A pre-existing field survives the merge.
      await writeFile(path, JSON.stringify({ theme: "dark" }), "utf8");
      await ensureQuietStartup(path);
      expect(JSON.parse(await readFile(path, "utf8"))).toEqual({ theme: "dark", quietStartup: false });
    } finally {
      await rm(dir, { recursive: true, force: true });
    }
  });

  it("treats a malformed settings file as empty and rewrites it", async () => {
    const dir = await mkdtemp(join(tmpdir(), "psyclaw-branding-"));
    const path = join(dir, "settings.json");
    try {
      await writeFile(path, "{not json", "utf8");
      const result = await ensureQuietStartup(path);
      expect(result.wrote).toBe(true);
      expect(JSON.parse(await readFile(path, "utf8"))).toEqual({ quietStartup: false });
    } finally {
      await rm(dir, { recursive: true, force: true });
    }
  });
});

describe("ensurePsyClawTheme", () => {
  it("installs the theme file and sets it as the default, idempotently", async () => {
    const dir = await mkdtemp(join(tmpdir(), "psyclaw-theme-"));
    const themesDir = join(dir, "themes");
    const settingsPath = join(dir, "settings.json");
    try {
      const first = await ensurePsyClawTheme({ themesDir, settingsPath });
      expect(first.wroteTheme).toBe(true);
      expect(first.wroteSetting).toBe(true);

      const themeJson = JSON.parse(await readFile(join(themesDir, `${PSYCLAW_THEME_NAME}.json`), "utf8")) as { name: string };
      expect(themeJson.name).toBe(PSYCLAW_THEME_NAME);
      expect(JSON.parse(await readFile(settingsPath, "utf8"))).toMatchObject({ theme: PSYCLAW_THEME_NAME });

      const second = await ensurePsyClawTheme({ themesDir, settingsPath });
      expect(second.wroteTheme).toBe(false);
      expect(second.wroteSetting).toBe(false);
    } finally {
      await rm(dir, { recursive: true, force: true });
    }
  });

  it("preserves other settings when setting the theme", async () => {
    const dir = await mkdtemp(join(tmpdir(), "psyclaw-theme-"));
    const settingsPath = join(dir, "settings.json");
    try {
      await writeFile(settingsPath, JSON.stringify({ quietStartup: true }), "utf8");
      await ensurePsyClawTheme({ themesDir: join(dir, "themes"), settingsPath });
      expect(JSON.parse(await readFile(settingsPath, "utf8"))).toEqual({ quietStartup: true, theme: PSYCLAW_THEME_NAME });
    } finally {
      await rm(dir, { recursive: true, force: true });
    }
  });
});
