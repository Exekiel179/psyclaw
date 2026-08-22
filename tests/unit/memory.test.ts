import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { JsonlMemoryStore } from "../../src/memory/store.js";

const record = {
  id: "m1",
  kind: "lesson" as const,
  scope: "project" as const,
  content: { text: "Keep evidence before prose" },
  sourceRefs: ["run-1"],
  confidence: 0.8,
  status: "pending" as const,
  createdAt: "2026-01-01T00:00:00.000Z",
  updatedAt: "2026-01-01T00:00:00.000Z",
};

describe("JsonlMemoryStore", () => {
  it("requires pending drafts and explicit approval", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-memory-"));
    const store = new JsonlMemoryStore(root);
    await store.draft(record);
    expect(await store.search("evidence")).toEqual([]);
    await store.approve("m1");
    expect((await store.search("evidence"))[0]?.status).toBe("active");
  });

  it("preserves history when archiving", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-memory-"));
    const store = new JsonlMemoryStore(root);
    await store.draft(record);
    await store.approve("m1");
    await store.archive("m1", "superseded by a newer decision");
    expect(await store.search("evidence")).toEqual([]);
    const rows: unknown[] = [];
    for await (const row of store.audit()) rows.push(row);
    expect(rows).toHaveLength(3);
  });
});
