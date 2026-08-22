import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { BoundedOrchestrator, verifyWorkerCompletion } from "../../src/orchestration/runner.js";
import type { Effect } from "../../src/core/contracts.js";
import type { Plan, TaskNode, WorkerReport } from "../../src/orchestration/contracts.js";

const report = (task: TaskNode, dispatchId: string, filesModified: string[] = []): WorkerReport => ({
  schemaVersion: "psyclaw/worker-report/v1",
  taskId: task.id,
  dispatchId,
  outcome: "succeeded",
  summary: `done ${task.id}`,
  filesModified,
  verification: [{ command: "fixture", exitCode: 0 }],
  blockers: [],
});

const task = (id: string, ownedPaths: string[] = []): TaskNode => ({
  id,
  role: "researcher",
  objective: `objective ${id}`,
  deps: [],
  ownedPaths,
  parallelSafe: true,
  inputs: [],
  outputs: [],
  completionContract: { requiredArtifacts: [], requiredReceiptEffects: [], mustPassGates: [] },
});

const plan = (tasks: TaskNode[], maxWorkers = 2): Plan => ({
  schemaVersion: "psyclaw/plan/v1",
  runId: "run-parallel",
  tasks,
  budget: { maxTurns: 10, maxWorkers },
});

describe("read-only parallel orchestration", () => {
  it("fans out independent read-only tasks and merges their reports", async () => {
    const tasks = [task("a"), task("b"), task("c")];
    let active = 0;
    let maxActive = 0;
    const executor = async (current: TaskNode, context: { dispatchId: string }) => {
      active += 1;
      maxActive = Math.max(maxActive, active);
      await new Promise((resolve) => setTimeout(resolve, 10));
      active -= 1;
      return report(current, context.dispatchId);
    };
    const result = await new BoundedOrchestrator({ executor, maxWorkers: 3 }).run(plan(tasks, 3));
    expect(result.status).toBe("completed");
    expect(maxActive).toBe(3);
    expect(result.reports.map((item) => item.taskId).sort()).toEqual(["a", "b", "c"]);
  });

  it("rejects any write attempt from a read-only worker", async () => {
    const result = await new BoundedOrchestrator({
      executor: async (current, context) => report(current, context.dispatchId, ["notes/out.md"]),
    }).run(plan([task("writer", ["notes/out.md"])]));
    expect(result.status).toBe("blocked");
    expect(result.diagnostics.join(" ")).toMatch(/read-only|modification/i);
  });

  it("rejects a duplicate idempotency key across receipts", () => {
    const current = task("t");
    const receipt = (key: string, tool: string) => ({
      schemaVersion: "psyclaw/tool-receipt/v1" as const,
      runId: "run-parallel",
      taskId: "t",
      tool,
      effect: "read" as const,
      approval: "not-needed" as const,
      idempotencyKey: key,
      ok: true,
      startedAt: "2026-01-01T00:00:00.000Z",
      finishedAt: "2026-01-01T00:00:01.000Z",
    });
    const result = verifyWorkerCompletion(current, {
      report: report(current, "d"),
      receipts: [receipt("shared:key", "tool-a"), receipt("shared:key", "tool-b")],
    }, {
      readOnly: true,
      expectedRunId: "run-parallel",
      expectedTaskId: "t",
      expectedDispatchId: "d",
      allowedEffects: new Set<Effect>(["read"]),
    });
    expect(result.ok).toBe(false);
    expect(result.reasons.join(" ")).toMatch(/duplicate idempotency/i);
  });

  it("requires an approved idempotent write receipt for any file modification", () => {
    const current = task("writer", ["notes/out.md"]);
    const result = verifyWorkerCompletion(current, {
      report: report(current, "d", ["notes/out.md"]),
    }, {
      readOnly: false,
      writtenPaths: [],
      reservedPaths: [],
      expectedRunId: "run-parallel",
      expectedTaskId: "writer",
      expectedDispatchId: "d",
      allowedEffects: new Set<Effect>(["read", "write"]),
    });
    expect(result.ok).toBe(false);
    expect(result.reasons.join(" ")).toMatch(/write receipt/i);
  });
});

describe("D3 runner hardening", () => {
  const receiptBase = () => ({
    schemaVersion: "psyclaw/tool-receipt/v1" as const,
    runId: "run-d3",
    taskId: "t",
    tool: "tool",
    effect: "read" as const,
    approval: "not-needed" as const,
    ok: true,
    startedAt: "2026-01-01T00:00:00.000Z",
    finishedAt: "2026-01-01T00:00:01.000Z",
  });

  const requiredTask = (artifact: string, ownedPaths: string[] = []): TaskNode => ({
    ...task("t", ownedPaths),
    completionContract: { requiredArtifacts: [artifact], requiredReceiptEffects: [], mustPassGates: [] },
  });

  it("rejects a pre-existing file impersonating a required artifact", () => {
    const current = requiredTask("package.json");
    const result = verifyWorkerCompletion(current, {
      report: report(current, "d"),
      artifacts: [{ path: "package.json", sha256: "a".repeat(64) }],
    }, { readOnly: true, allowedEffects: new Set<Effect>(["read"]) });
    expect(result.ok).toBe(false);
    expect(result.reasons.join(" ")).toMatch(/outside owned paths\/outputs/);
  });

  it("requires a sha256 for a required artifact", () => {
    const current = requiredTask("notes/out.md", ["notes/out.md"]);
    const result = verifyWorkerCompletion(current, {
      report: report(current, "d"),
      artifacts: [{ path: "notes/out.md" }],
    }, { readOnly: true, allowedEffects: new Set<Effect>(["read"]) });
    expect(result.ok).toBe(false);
    expect(result.reasons.join(" ")).toMatch(/missing a valid sha256/);
  });

  it("rejects receipts with empty ids or inverted timestamps", () => {
    const current = task("t");
    const emptyId = verifyWorkerCompletion(current, {
      report: report(current, "d"),
      receipts: [{ ...receiptBase(), runId: "" }],
    }, { readOnly: true, allowedEffects: new Set<Effect>(["read"]) });
    expect(emptyId.reasons.join(" ")).toMatch(/receipt schema invalid/);

    const inverted = verifyWorkerCompletion(current, {
      report: report(current, "d"),
      receipts: [{ ...receiptBase(), startedAt: "2026-01-01T00:00:02.000Z", finishedAt: "2026-01-01T00:00:01.000Z" }],
    }, { readOnly: true, allowedEffects: new Set<Effect>(["read"]) });
    expect(inverted.reasons.join(" ")).toMatch(/receipt schema invalid/);
  });

  it("rejects non-ISO receipt timestamps", () => {
    const current = task("t");
    const result = verifyWorkerCompletion(current, {
      report: report(current, "d"),
      receipts: [{ ...receiptBase(), startedAt: "0", finishedAt: "1" }],
    }, { readOnly: true, allowedEffects: new Set<Effect>(["read"]) });
    expect(result.ok).toBe(false);
    expect(result.reasons.join(" ")).toMatch(/receipt schema invalid/);
  });

  it("denies network and destructive effects without their own approval", () => {
    const current = task("t");
    const base = {
      readOnly: false,
      allowedEffects: new Set<Effect>(["read", "write"]),
      expectedRunId: "run-d3",
      expectedTaskId: "t",
      expectedDispatchId: "d",
    };
    const network = verifyWorkerCompletion(current, {
      report: report(current, "d"),
      receipts: [{ ...receiptBase(), effect: "network" as const }],
    }, base);
    expect(network.reasons.join(" ")).toMatch(/undeclared network/);

    const destructive = verifyWorkerCompletion(current, {
      report: report(current, "d"),
      receipts: [{ ...receiptBase(), effect: "destructive" as const }],
    }, base);
    expect(destructive.reasons.join(" ")).toMatch(/undeclared destructive/);
  });

  it("blocks resume when the checkpoint plan hash is tampered", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-d3-"));
    try {
      const currentPlan: Plan = {
        schemaVersion: "psyclaw/plan/v1",
        runId: "run-tamper",
        tasks: [task("a"), task("b")],
        budget: { maxTurns: 1, maxWorkers: 1 },
      };
      const executor = async (current: TaskNode, context: { dispatchId: string }) => report(current, context.dispatchId);
      const first = await new BoundedOrchestrator({ root, executor }).run(currentPlan);
      expect(first.status).toBe("paused");

      const checkpointPath = join(root, ".psyclaw", "runs", "run-tamper.checkpoint.json");
      const tampered = JSON.parse(await readFile(checkpointPath, "utf8")) as { planHash: string };
      tampered.planHash = "0".repeat(64);
      await writeFile(checkpointPath, JSON.stringify(tampered), "utf8");

      const resumed = await new BoundedOrchestrator({ root, executor }).resume(currentPlan);
      expect(resumed.status).toBe("blocked");
      expect(resumed.diagnostics.join(" ")).toMatch(/plan hash/i);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});
