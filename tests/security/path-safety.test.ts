import { mkdtemp, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { assertSafeProjectPath } from "../../src/project/paths.js";
import { validatePlan } from "../../src/orchestration/scheduler.js";
import { BoundedOrchestrator, verifyWorkerCompletion } from "../../src/orchestration/runner.js";
import type { Effect } from "../../src/core/contracts.js";
import type { Plan, TaskNode, WorkerReport } from "../../src/orchestration/contracts.js";

const report = (task: TaskNode, dispatchId: string, filesModified: string[] = []): WorkerReport => ({
  schemaVersion: "psyclaw/worker-report/v1",
  taskId: task.id,
  dispatchId,
  outcome: "succeeded",
  summary: "fixture",
  filesModified,
  verification: [{ command: "fixture", exitCode: 0 }],
  blockers: [],
});

const task = (id: string, ownedPaths: string[] = [], parallelSafe = true): TaskNode => ({
  id,
  role: "researcher",
  objective: `objective ${id}`,
  deps: [],
  ownedPaths,
  parallelSafe,
  inputs: [],
  outputs: [],
  completionContract: { requiredArtifacts: [], requiredReceiptEffects: [], mustPassGates: [] },
});

const plan = (tasks: TaskNode[]): Plan => ({
  schemaVersion: "psyclaw/plan/v1",
  runId: "run-sec",
  tasks,
  budget: { maxTurns: 10, maxWorkers: 2 },
});

describe("path traversal, symlink, and raw-data protection", () => {
  it("rejects cross-platform absolute and traversal project paths", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-pathsec-"));
    for (const bad of ["../outside.txt", "..", "/etc/passwd", "C:\\windows\\system32", "\\\\server\\share\\x"]) {
      await expect(assertSafeProjectPath(root, bad)).rejects.toThrow(/escapes|Protected/i);
    }
  });

  it("refuses a symlinked parent that would redirect a future write", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-pathsec-root-"));
    const outside = await mkdtemp(join(tmpdir(), "psyclaw-pathsec-out-"));
    await symlink(outside, join(root, "notes"), "junction");
    await expect(assertSafeProjectPath(root, "notes/file.md")).rejects.toThrow();
  });

  it("flags traversal and raw-data owned paths at plan validation", () => {
    const traversal = validatePlan(plan([task("t", ["notes/../outside"])]));
    expect(traversal.some((item) => /traversal/i.test(item.reason))).toBe(true);

    const raw = validatePlan(plan([task("t", ["data/raw/out.csv"])]));
    expect(raw.some((item) => /raw data is immutable/i.test(item.reason))).toBe(true);

    const credentials = validatePlan(plan([task("t", ["notes/credentials.env"])]));
    expect(credentials.some((item) => /credential/i.test(item.reason))).toBe(true);
  });

  it("blocks a plan whose owned path escapes or touches raw data", async () => {
    const rawPlan = plan([task("raw", ["data/raw/out.csv"])]);
    const rawResult = await new BoundedOrchestrator({ executor: async () => ({ nope: true } as never) }).run(rawPlan);
    expect(rawResult.status).toBe("blocked");
    expect(rawResult.diagnostics.join(" ")).toMatch(/raw|protected/i);

    const traversalPlan = plan([task("t", ["notes/../outside"])]);
    const traversalResult = await new BoundedOrchestrator({ executor: async () => ({ nope: true } as never) }).run(traversalPlan);
    expect(traversalResult.status).toBe("blocked");
    expect(traversalResult.diagnostics.join(" ")).toMatch(/traversal|owned path/i);
  });

  it("denies a worker report that writes protected paths or outside owned paths", () => {
    const currentTask = task("writer", ["notes/report.md"]);
    const base = {
      readOnly: false,
      allowedEffects: new Set<Effect>(["read", "write"]),
      expectedRunId: "run-sec",
      expectedTaskId: "writer",
      expectedDispatchId: "d",
      writtenPaths: [],
      reservedPaths: [],
    } as const;

    const rawWrite = verifyWorkerCompletion(currentTask, {
      report: report(currentTask, "d", ["notes/../data/raw/out.csv"]),
    }, base);
    expect(rawWrite.ok).toBe(false);
    expect(rawWrite.reasons.join(" ")).toMatch(/protected/i);

    const outsideWrite = verifyWorkerCompletion(currentTask, {
      report: report(currentTask, "d", ["notes/../../outside.txt"]),
    }, base);
    expect(outsideWrite.ok).toBe(false);
    expect(outsideWrite.reasons.join(" ")).toMatch(/outside owned paths/i);
  });
});
