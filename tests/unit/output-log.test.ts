import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { persistToolOutput, recallToolOutput } from "../../src/analysis/output-log.js";

describe("tool output recall", () => {
  it("saves a long output once and recalls the middle line", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-output-log-"));
    const text = ["HEAD", "m".repeat(3_000), "BETA 0.42", "z".repeat(3_000), "TAIL"].join("\n");
    const saved = await persistToolOutput(root, "call-middle", text, 2_080);
    expect(saved).toBe(".psyclaw/cache/tool-output/call-middle.txt");
    expect(await persistToolOutput(root, "call-middle", text, 2_080)).toBe(saved);
    const recalled = await recallToolOutput(root, saved ?? "", 3, 1);
    expect(recalled).toContain("3|BETA 0.42");
    expect(recalled).not.toContain("zzz");
    expect(recalled.length).toBeLessThan(2_080);
    await expect(recallToolOutput(root, "data/secret/scores.csv", 1, 1)).rejects.toThrow(/tool-output/);
  });

  it("does not save a result that already fits the settled window", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-output-log-short-"));
    expect(await persistToolOutput(root, "short", "n = 12", 2_080)).toBeUndefined();
  });
});
