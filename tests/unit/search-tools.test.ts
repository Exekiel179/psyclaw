import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { createNodeFindTool, createNodeGrepTool } from "../../src/adapters/pi/search-tools.js";

const roots: string[] = [];

async function fixture(): Promise<string> {
  const root = await mkdtemp(join(tmpdir(), "psyclaw-search-"));
  roots.push(root);
  await mkdir(join(root, "src"), { recursive: true });
  await mkdir(join(root, ".psyclaw", "data", "raw"), { recursive: true });
  await writeFile(join(root, "src", "study.ts"), "const topic = 'resilience';\n", "utf8");
  await writeFile(join(root, "src", "binary.bin"), Buffer.from([0, 1, 2, 3]));
  await writeFile(join(root, ".psyclaw", "data", "raw", "secret.txt"), "resilience\n", "utf8");
  return root;
}

afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
});

describe("Node search fallbacks", () => {
  it("finds matching files without external binaries and excludes raw data", async () => {
    const root = await fixture();
    const tool = createNodeFindTool();
    const result = await tool.execute("find-1", { pattern: "**/*.ts" }, undefined, undefined, { cwd: root } as never);
    expect(result.content[0]).toMatchObject({ type: "text", text: "src/study.ts" });

    const raw = await tool.execute("find-2", { pattern: "**/*.txt" }, undefined, undefined, { cwd: root } as never);
    expect(raw.content[0]).toMatchObject({ type: "text", text: "No files found matching pattern" });
  });

  it("searches text and skips binary and raw-data files", async () => {
    const root = await fixture();
    const tool = createNodeGrepTool();
    const result = await tool.execute("grep-1", { pattern: "RESILIENCE", ignoreCase: true }, undefined, undefined, { cwd: root } as never);
    expect(result.content[0]).toMatchObject({ type: "text", text: expect.stringContaining("src/study.ts:1:") });
    expect((result.content[0] as { text: string }).text).not.toContain("secret.txt");
    expect((result.content[0] as { text: string }).text).not.toContain("binary.bin");
  });

  it("rejects a raw-data directory used as the search root", async () => {
    const root = await fixture();
    const context = { cwd: root } as never;
    await expect(createNodeFindTool().execute(
      "find-raw", { pattern: "**/*", path: ".psyclaw/data/raw" }, undefined, undefined, context,
    )).rejects.toThrow("Raw-data directories cannot be searched");
    await expect(createNodeGrepTool().execute(
      "grep-raw", { pattern: "resilience", path: ".psyclaw/data/raw" }, undefined, undefined, context,
    )).rejects.toThrow("Raw-data directories cannot be searched");
  });

  it("rejects excluded metadata and dependency roots", async () => {
    const root = await fixture();
    await mkdir(join(root, ".git"), { recursive: true });
    await expect(createNodeFindTool().execute(
      "find-git", { pattern: "**/*", path: ".git" }, undefined, undefined, { cwd: root } as never,
    )).rejects.toThrow("cannot be searched");
  });
});
