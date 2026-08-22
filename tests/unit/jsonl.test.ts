import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { appendJsonlIfMissing, atomicWriteFile, readJsonl } from "../../src/project/jsonl.js";

describe("JSONL persistence", () => {
  it("deduplicates concurrent records inside one process", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-jsonl-"));
    const path = join(root, "nested", "records.jsonl");
    const results = await Promise.all(
      Array.from({ length: 12 }, (_, index) => appendJsonlIfMissing(path, { id: "same", index }, (row) => row.id)),
    );
    expect(results.filter((result) => result.appended)).toHaveLength(1);
    expect(await readJsonl<{ id: string; index: number }>(path)).toHaveLength(1);
  });

  it("replaces a destination without leaving partial content", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-jsonl-"));
    const path = join(root, "result.json");
    await atomicWriteFile(path, "first\n");
    await atomicWriteFile(path, "second\n");
    expect(await readFile(path, "utf8")).toBe("second\n");
  });
});
