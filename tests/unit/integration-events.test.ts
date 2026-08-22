import { describe, expect, it } from "vitest";
import { mkdtemp, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { LazyMcpIntegration } from "../../src/integrations/mcp.js";
import { RunEventLog } from "../../src/panel/events.js";

describe("MCP and run-event boundaries", () => {
  it("keeps untrusted or unavailable MCP servers fail-closed", async () => {
    const integration = new LazyMcpIntegration({ id: "fixture", command: "server", args: [], trusted: true, enabled: true });
    expect(await integration.list()).toEqual([]);
    expect((await integration.health()).ok).toBe(false);
    const receipt = await integration.invoke(
      { runId: "r1", taskId: "t1", tool: "fixture.tool", input: {}, idempotencyKey: "k1" },
      { decision: "approved", actor: "researcher", reason: "fixture" },
    );
    expect(receipt.ok).toBe(false);
    expect(receipt.approval).toBe("denied");
    expect(receipt.reasonCode).toBe("mcp.transport-disabled");
    expect(receipt.resultHash).toMatch(/^[a-f0-9]{64}$/);
    expect(receipt.resultHash).not.toContain("MCP");
  });

  it("persists append-only run events and can replay them", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-events-"));
    const log = new RunEventLog(root, "run-1");
    await Promise.all([
      log.append({ type: "planned", at: "2026-01-01T00:00:00.000Z", message: "one" }),
      log.append({ type: "started", at: "2026-01-01T00:00:01.000Z", message: "two" }),
    ]);
    const events = await log.snapshot();
    expect(events).toHaveLength(2);
    expect(events.every((event) => event.schemaVersion === "psyclaw/run-event/v1")).toBe(true);
  });

  it("does not append through a symlinked event file", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-events-symlink-"));
    const outside = await mkdtemp(join(tmpdir(), "psyclaw-events-outside-"));
    const outsideFile = join(outside, "events.jsonl");
    await writeFile(outsideFile, "", "utf8");
    await import("node:fs/promises").then(({ mkdir }) => mkdir(join(root, ".psyclaw", "runs"), { recursive: true }));
    await symlink(outsideFile, join(root, ".psyclaw", "runs", "run-link.jsonl"), "file");

    const log = new RunEventLog(root, "run-link");
    await expect(log.append({ type: "planned", at: "2026-01-01T00:00:00.000Z" })).rejects.toThrow(/symlink|regular file|path/i);
    await expect((await import("node:fs/promises")).readFile(outsideFile, "utf8")).resolves.toBe("");
  });
});
