import { mkdtemp, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { bootstrapProject } from "../../src/project/bootstrap.js";
import { appendClaim, appendClaimEvidenceLink, appendEvidence } from "../../src/research/ledger.js";
import { RunEventLog } from "../../src/panel/events.js";
import { listRuns, projectRunSnapshot } from "../../src/panel/projection.js";

describe("panel projection", () => {
  it("derives a redacted, read-only run snapshot from the fact sources", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-projection-"));
    await bootstrapProject({ root, goal: "Goal with secret token=abc123", paradigm: "survey-observational" });
    await appendEvidence(root, {
      id: "e-1",
      source: { kind: "file", locator: "source.md" },
      level: "abstract",
      retrievedAt: "2026-01-01T00:00:00.000Z",
      accessStatus: "verified",
      locators: [{ kind: "section", value: "Abstract" }],
    });
    await appendClaim(root, { id: "c-1", text: "A definition", kind: "definition", evidenceIds: ["e-1"], status: "supported" });
    await appendClaimEvidenceLink(root, { claimId: "c-1", evidenceId: "e-1", relation: "supports", rationale: "stated" });

    const log = new RunEventLog(root, "run-panel");
    await log.append({ type: "planned", at: "2026-01-01T00:00:00.000Z" });
    await log.append({ type: "started", at: "2026-01-01T00:00:01.000Z", message: "secret=sk-abcdefghijklmnopqrstuvwx" });
    await log.append({ type: "completed", at: "2026-01-01T00:00:02.000Z" });

    const snapshot = await projectRunSnapshot(root, "run-panel");
    expect(snapshot.schemaVersion).toBe("psyclaw/run-snapshot/v1");
    expect(snapshot.phase).toBe("completed");
    expect(snapshot.blocked).toBe(false);
    expect(snapshot.eventCount).toBe(3);
    expect(snapshot.evidenceCoverage).toMatchObject({ totalClaims: 1, supportedClaims: 1, totalEvidence: 1 });
    expect(snapshot.gates[0]?.ok).toBe(true);
    // goal and event messages must be scrubbed before projection
    expect(JSON.stringify(snapshot)).not.toContain("token=abc123");
    expect(snapshot.goal).toContain("[REDACTED:credential-assignment]");
  });

  it("marks a blocked run and lists discovered runs", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-projection-blocked-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "survey-observational" });
    await appendClaim(root, { id: "c-1", text: "No evidence", kind: "definition", evidenceIds: [], status: "supported" });
    const log = new RunEventLog(root, "run-blocked");
    await log.append({ type: "planned", at: "2026-01-01T00:00:00.000Z" });
    await log.append({ type: "blocked", at: "2026-01-01T00:00:01.000Z", message: "gate failed" });

    const snapshot = await projectRunSnapshot(root, "run-blocked");
    expect(snapshot.phase).toBe("blocked");
    expect(snapshot.blocked).toBe(true);
    expect(snapshot.waitingOnHuman.length).toBeGreaterThan(0);

    const runs = await listRuns(root);
    expect(runs.map((item) => item.runId)).toEqual(["run-blocked"]);
  });

  it("reports a forged terminal event as unknown, not completed", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-projection-forged-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "survey-observational" });
    const log = new RunEventLog(root, "run-forged");
    await log.append({ type: "completed", at: "2026-01-01T00:00:00.000Z", message: "forged" });

    const snapshot = await projectRunSnapshot(root, "run-forged");
    expect(snapshot.phase).toBe("unknown");
    expect(snapshot.blocked).toBe(false);
  });

  it("reports a corrupt event log as unknown with a stable diagnostic", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-projection-corrupt-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "survey-observational" });
    const { mkdir } = await import("node:fs/promises");
    await mkdir(join(root, ".psyclaw", "runs"), { recursive: true });
    await writeFile(join(root, ".psyclaw", "runs", "run-corrupt.jsonl"), "this is not json\n", "utf8");

    const snapshot = await projectRunSnapshot(root, "run-corrupt");
    expect(snapshot.phase).toBe("unknown");
    expect(snapshot.waitingOnHuman).toContain("run event log is corrupt or unavailable");
  });

  it("reports a corrupt checkpoint as unknown instead of trusting a terminal event", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-projection-checkpoint-corrupt-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "survey-observational" });
    const log = new RunEventLog(root, "run-checkpoint-corrupt");
    await log.append({ type: "planned", at: "2026-01-01T00:00:00.000Z" });
    await log.append({ type: "completed", at: "2026-01-01T00:00:01.000Z" });
    await writeFile(join(root, ".psyclaw", "runs", "run-checkpoint-corrupt.checkpoint.json"), "{not-json", "utf8");

    const snapshot = await projectRunSnapshot(root, "run-checkpoint-corrupt");
    expect(snapshot.phase).toBe("unknown");
    expect(snapshot.waitingOnHuman).toContain("run checkpoint is corrupt or unavailable");
  });

  it("rejects a symlinked run event log instead of reading outside the project", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-projection-event-symlink-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "survey-observational" });
    const outside = await mkdtemp(join(tmpdir(), "psyclaw-projection-event-outside-"));
    const outsideFile = join(outside, "events.jsonl");
    await writeFile(outsideFile, JSON.stringify({ schemaVersion: "psyclaw/run-event/v1", runId: "run-symlink", type: "completed", at: "2026-01-01T00:00:00.000Z" }) + "\n", "utf8");
    const eventPath = join(root, ".psyclaw", "runs", "run-symlink.jsonl");
    await symlink(outsideFile, eventPath, "file");

    const snapshot = await projectRunSnapshot(root, "run-symlink");
    expect(snapshot.phase).toBe("unknown");
    expect(snapshot.waitingOnHuman).toContain("run event log is corrupt or unavailable");
  });
});
