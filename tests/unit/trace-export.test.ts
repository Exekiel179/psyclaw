import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { exportTraces } from "../../src/telemetry/export.js";

describe("trace export", () => {
  it("exports session and workflow paths without content, ids, or absolute paths", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-trace-project-"));
    const agentDir = await mkdtemp(join(tmpdir(), "psyclaw-trace-agent-"));
    const sessions = join(agentDir, "sessions", "fixture");
    const runs = join(root, ".psyclaw", "runs");
    await mkdir(sessions, { recursive: true });
    await mkdir(runs, { recursive: true });
    const secret = "private-research-question-XYZ";
    await writeFile(join(sessions, "session.jsonl"), [
      JSON.stringify({ type: "session", id: "original-session-id", cwd: root, timestamp: "2026-08-29T10:00:00.000Z" }),
      JSON.stringify({ type: "message", id: "user-id", timestamp: "2026-08-29T10:00:01.000Z", message: { role: "user", content: [{ type: "text", text: secret }] } }),
      JSON.stringify({ type: "message", id: "assistant-id", timestamp: "2026-08-29T10:00:02.000Z", message: { role: "assistant", content: [{ type: "toolCall", name: "psyclaw_workbench", arguments: { path: "/private/file.pdf" } }] } }),
    ].join("\n"), "utf8");
    await writeFile(join(runs, "run.jsonl"), [
      JSON.stringify({ schemaVersion: "psyclaw/run-event/v1", runId: "original-run-id", type: "planned", at: "2026-08-29T10:01:00.000Z", message: secret }),
      JSON.stringify({ schemaVersion: "psyclaw/run-event/v1", runId: "original-run-id", type: "completed", at: "2026-08-29T10:01:01.000Z" }),
    ].join("\n"), "utf8");

    const result = await exportTraces({ root, agentDir, output: "outputs/traces.json" });
    expect(result).toMatchObject({ traces: 2, sources: { sessions: 1, workflowRuns: 1 } });
    const text = await readFile(result.output, "utf8");
    expect(text).toContain("conversation.user_turn");
    expect(text).toContain("tool.research_workbench");
    expect(text).toContain("workflow.completed");
    expect(text).not.toContain(secret);
    expect(text).not.toContain("original-session-id");
    expect(text).not.toContain("original-run-id");
    expect(text).not.toContain(root);
    expect(text).not.toContain("/private/file.pdf");
  });

  it("rejects an output outside the current project", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-trace-project-"));
    await expect(exportTraces({ root, output: "../outside.json" })).rejects.toThrow(/inside the current project/);
  });
});
