import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  BoundedOrchestrator,
  PlanSchemaError,
  planOnly,
  verifyWorkerCompletion,
  type WorkerExecutionResult,
} from "../../src/orchestration/runner.js";
import type { Plan, TaskNode, WorkerReport } from "../../src/orchestration/contracts.js";

const report = (task: TaskNode, dispatchId: string, filesModified: string[] = []): WorkerReport => ({
  schemaVersion: "psyclaw/worker-report/v1",
  taskId: task.id,
  dispatchId,
  outcome: "succeeded",
  summary: `completed ${task.id}`,
  filesModified,
  verification: [{ command: "fixture-check", exitCode: 0 }],
  blockers: [],
});

const task = (
  id: string,
  deps: string[] = [],
  ownedPaths: string[] = [],
  parallelSafe = true,
  completionContract: TaskNode["completionContract"] = {
    requiredArtifacts: [],
    requiredReceiptEffects: [],
    mustPassGates: [],
  },
): TaskNode => ({
  id,
  role: "researcher",
  objective: `objective ${id}`,
  deps,
  ownedPaths,
  parallelSafe,
  inputs: [],
  outputs: [],
  completionContract,
});

const plan = (tasks: TaskNode[], budget = { maxTurns: 20, maxWorkers: 2 }): Plan => ({
  schemaVersion: "psyclaw/plan/v1",
  runId: "run-fixture",
  tasks,
  budget,
});

describe("bounded orchestration runner", () => {
  it("accepts only schema-valid plans and never gives the planner an executor", async () => {
    let calls = 0;
    const valid = await planOnly(async (request) => {
      expect(request.goal).toBe("test goal");
      calls += 1;
      return plan([task("one")]);
    }, { goal: "test goal" });
    expect(valid.schemaVersion).toBe("psyclaw/plan/v1");
    expect(calls).toBe(1);
    await expect(planOnly(async () => ({ schemaVersion: "psyclaw/plan/v1" }), { goal: "bad" }))
      .rejects.toBeInstanceOf(PlanSchemaError);
  });

  it("runs a dependency DAG while respecting the hard four-worker cap", async () => {
    const tasks = [
      task("a", [], ["notes/a"]),
      task("b", [], ["notes/b"]),
      task("c", [], ["notes/c"]),
      task("d", [], ["notes/d"]),
      task("e", ["a", "b", "c", "d"], ["notes/e"]),
    ];
    const active: string[] = [];
    let maxActive = 0;
    const seen: string[] = [];
    const executor = async (current: TaskNode, context: { dispatchId: string }) => {
      active.push(current.id);
      maxActive = Math.max(maxActive, active.length);
      seen.push(current.id);
      await new Promise((resolve) => setTimeout(resolve, 5));
      active.splice(active.indexOf(current.id), 1);
      return report(current, context.dispatchId);
    };
    const result = await new BoundedOrchestrator({ executor, maxWorkers: 4 }).run(plan(tasks, { maxTurns: 20, maxWorkers: 4 }));
    expect(result.status).toBe("completed");
    expect(maxActive).toBe(4);
    expect(seen.slice(-1)).toEqual(["e"]);
    expect(result.reports.map((item) => item.taskId)).toEqual(["a", "b", "c", "d", "e"]);
  });

  it("fails closed for malformed reports and read-only worker side effects", async () => {
    const malformed = await new BoundedOrchestrator({
      executor: async () => ({ nope: true } as never),
    }).run(plan([task("bad")]));
    expect(malformed.status).toBe("blocked");
    expect(malformed.diagnostics.join(" ")).toMatch(/schema|worker/i);

    const writeAttempt = await new BoundedOrchestrator({
      executor: async (current, context) => report(current, context.dispatchId, ["notes/generated.md"]),
    }).run(plan([task("writer", [], ["notes/generated.md"])]));
    expect(writeAttempt.status).toBe("blocked");
    expect(writeAttempt.diagnostics.join(" ")).toMatch(/read-only|modification/i);

    const protectedPlan = plan([task("raw", [], ["notes/../data/raw/out.csv"])]);
    const protectedResult = await new BoundedOrchestrator({ executor: async () => ({ nope: true } as never) }).run(protectedPlan);
    expect(protectedResult.status).toBe("blocked");
    expect(protectedResult.diagnostics.join(" ")).toMatch(/protected|owned path/i);
  });

  it("requires completion artifacts, gates, and approved idempotent receipts", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-orchestrator-artifact-"));
    await mkdir(join(root, "notes"), { recursive: true });
    await writeFile(join(root, "notes", "report.md"), "verified fixture\n", "utf8");
    const currentTask = task("contract", [], ["notes/report.md"], true, {
      requiredArtifacts: ["notes/report.md"],
      requiredReceiptEffects: ["read", "write"],
      mustPassGates: ["evidence.sufficient"],
    });
    const executor = async (_task: TaskNode, context: { runId: string; dispatchId: string }): Promise<WorkerExecutionResult> => ({
      report: report(currentTask, context.dispatchId, ["notes/report.md"]),
      artifacts: [{ path: "notes/report.md", sha256: createHash("sha256").update("verified fixture\n").digest("hex") }],
      receipts: [
        {
          schemaVersion: "psyclaw/tool-receipt/v1",
          runId: context.runId,
          taskId: currentTask.id,
          tool: "read-fixture",
          effect: "read",
          approval: "not-needed",
          ok: true,
           startedAt: "2026-01-01T00:00:00.000Z",
           finishedAt: "2026-01-01T00:00:01.000Z",
        },
        {
          schemaVersion: "psyclaw/tool-receipt/v1",
          runId: context.runId,
          taskId: currentTask.id,
          tool: "write-fixture",
          effect: "write",
          approval: "approved",
          idempotencyKey: "write:contract:1",
          ok: true,
           startedAt: "2026-01-01T00:00:00.000Z",
           finishedAt: "2026-01-01T00:00:01.000Z",
        },
      ],
      passedGates: ["evidence.sufficient"],
    });
    try {
      const denied = await new BoundedOrchestrator({ root, executor }).run(plan([currentTask]));
      expect(denied.status).toBe("blocked");
      const accepted = await new BoundedOrchestrator({ root, executor, allowWrites: true }).run(plan([{ ...currentTask, allowedEffects: ["read", "write"] }]));
      expect(accepted.status, accepted.diagnostics.join(" | ")).toBe("completed");
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("writes a checkpoint, resumes unfinished tasks, and blocks input drift", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-orchestrator-"));
    try {
      const currentPlan = plan([
        task("a", [], ["notes/a"]),
        task("b", [], ["notes/b"]),
      ], { maxTurns: 1, maxWorkers: 2 });
      const calls: string[] = [];
      const executor = async (current: TaskNode, context: { dispatchId: string }) => {
        calls.push(current.id);
        return report(current, context.dispatchId);
      };
      const first = await new BoundedOrchestrator({ root, executor, inputDigest: "inputs-v1" }).run(currentPlan);
      expect(first.status).toBe("paused");
      expect(first.checkpoint?.budgetUsed).toBe(1);
      const checkpointPath = join(root, ".psyclaw", "runs", `${currentPlan.runId}.checkpoint.json`);
      expect(JSON.parse(await readFile(checkpointPath, "utf8")).schemaVersion).toBe("psyclaw/orchestrator-checkpoint/v1");

      const drift = await new BoundedOrchestrator({ root, executor, inputDigest: "inputs-v2", maxTurns: 4 }).resume(currentPlan);
      expect(drift.status).toBe("blocked");
      expect(drift.diagnostics.join(" ")).toMatch(/input digest drift/);

      const resumed = await new BoundedOrchestrator({ root, executor, inputDigest: "inputs-v1", maxTurns: 4 }).resume(currentPlan);
      expect(resumed.status).toBe("completed");
      expect(new Set(calls)).toEqual(new Set(["a", "b"]));
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("rejects stale dispatch results before they can satisfy a contract", () => {
    const currentTask = task("stale");
    const result = verifyWorkerCompletion(currentTask, {
      report: report(currentTask, "old-dispatch"),
    }, { readOnly: true, expectedDispatchId: "new-dispatch" });
    expect(result.ok).toBe(false);
    expect(result.reasons.join(" ")).toMatch(/stale|dispatch/i);
  });
});
