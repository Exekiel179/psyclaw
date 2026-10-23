import { mkdtemp, readFile, writeFile, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  accessFor,
  loadDataAccess,
  redactScriptOnlyOutput,
  scriptOnlyBlock,
  setDataAccess,
} from "../../src/safety/data-access.js";
import { sessionModePrompt } from "../../src/session/modes.js";

const defaults = [
  { path: "data/secret", access: "script-only" as const },
];

describe("data access display levels", () => {
  it("keeps data/secret script-only until a longer path or the config says otherwise", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-data-access-"));
    const loaded = await loadDataAccess(root);
    expect(loaded.entries).toEqual(defaults);
    expect(accessFor("data/secret/scores.csv", loaded.entries)).toBe("script-only");
    expect(accessFor("data/raw/scores.csv", loaded.entries)).toBe("full");
    expect(accessFor("data/clean/ready.csv", loaded.entries)).toBe("full");

    const opened = await setDataAccess(root, "data/secret/public.csv", "full");
    expect(accessFor("data/secret/public.csv", opened)).toBe("full");
    expect(accessFor("data/secret/scores.csv", opened)).toBe("script-only");
    const saved = JSON.parse(await readFile(join(root, ".psyclaw/data-access.json"), "utf8"));
    expect(saved.schemaVersion).toBe("psyclaw/data-access/v1");
    expect(saved.entries).toEqual([{ path: "data/secret/public.csv", access: "full" }]);
  });

  it("blocks direct reads and dumps, and still allows a script entrypoint", () => {
    const secret = "data/secret/scores.csv";
    expect(scriptOnlyBlock("read", { path: secret }, defaults)).toContain("script-only");
    expect(scriptOnlyBlock("read", { path: "/work/data/secret/scores.csv" }, defaults, "/work")).toContain("script-only");
    expect(scriptOnlyBlock("read", { path: "data/raw/scores.csv" }, defaults)).toBeUndefined();
    expect(scriptOnlyBlock("grep", { path: "data/secret", pattern: "score" }, defaults)).toContain("script-only");
    expect(scriptOnlyBlock("grep", { pattern: "score" }, defaults)).toBeUndefined();
    expect(scriptOnlyBlock("psyclaw_data_profile", { path: secret }, defaults)).toBeUndefined();
    expect(scriptOnlyBlock("psyclaw_read_results", { path: secret }, defaults)).toContain("script-only");
    expect(scriptOnlyBlock("bash", { command: `head -n 5 ${secret}` }, defaults)).toContain("script-only");
    expect(scriptOnlyBlock("bash", { command: `python3 -c 'print(open("${secret}").read())'` }, defaults)).toContain("script-only");
    expect(scriptOnlyBlock("bash", { command: `python3 analysis/scripts/cat.py ${secret}` }, defaults)).toBeUndefined();
    expect(scriptOnlyBlock("bash", { command: `Rscript analysis/scripts/run_all.R ${secret}` }, defaults)).toBeUndefined();
    expect(scriptOnlyBlock("bash", { command: "Rscript analysis/scripts/run_all.R && cat data/secret/scores.csv" }, defaults)).toContain("script-only");
    expect(scriptOnlyBlock("edit", { path: ".psyclaw/data-access.json" }, defaults)).toContain("/data-access");
    expect(scriptOnlyBlock("bash", { command: "printf full > .psyclaw/data-access.json" }, defaults)).toContain("/data-access");
    expect(scriptOnlyBlock("read", { path: ".psyclaw/data-access.json" }, defaults)).toBeUndefined();
    expect(scriptOnlyBlock("read", { path: ".psyclaw/cache/tool-output/call.txt" }, defaults)).toContain("psyclaw_recall_output");
    expect(scriptOnlyBlock("psyclaw_recall_output", { path: ".psyclaw/cache/tool-output/call.txt" }, defaults)).toBeUndefined();
    expect(scriptOnlyBlock("bash", { command: "cat .psyclaw/cache/tool-output/call.txt" }, defaults)).toContain("psyclaw_recall_output");
  });

  it("drops grep lines that point at a script-only file", () => {
    const text = redactScriptOnlyOutput([
      "data/clean/ready.csv:1: id,score",
      "data/secret/scores.csv:2: 1,99",
      "data/raw/scores.csv:1: visible",
      ".psyclaw/cache/tool-output/call.txt:40: hidden-middle",
    ].join("\n"), defaults);
    expect(text).toContain("data/clean/ready.csv:1: id,score");
    expect(text).toContain("data/raw/scores.csv:1: visible");
    expect(text).not.toContain("99");
    expect(text).not.toContain("hidden-middle");
    expect(text).toContain("withheld 2");
  });

  it("does not let a broken config replace the data/secret default", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-data-access-bad-"));
    await mkdir(join(root, ".psyclaw"), { recursive: true });
    await writeFile(join(root, ".psyclaw/data-access.json"), "{", "utf8");
    const loaded = await loadDataAccess(root);
    expect(loaded.warning).toContain("无法读取");
    expect(accessFor("data/secret/scores.csv", loaded.entries)).toBe("script-only");
    await expect(setDataAccess(root, "data/other.csv", "script-only")).rejects.toThrow(/无法读取/);
  });

  it("tells analysis mode that data/secret is script-only", () => {
    expect(sessionModePrompt("analysis")).toContain("data/secret is script-only");
    expect(sessionModePrompt("analysis")).toContain("/data-access");
  });
});
