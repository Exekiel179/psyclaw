import { describe, expect, it } from "vitest";
import { nextReadyBatch, validatePlan } from "../../src/orchestration/scheduler.js";
import type { Plan } from "../../src/orchestration/contracts.js";

const task = (id: string, deps: string[] = [], ownedPaths = [`notes/${id}`], parallelSafe = true) => ({
  id,
  role: "researcher" as const,
  objective: id,
  deps,
  ownedPaths,
  parallelSafe,
  inputs: [],
  outputs: ownedPaths,
  completionContract: { requiredArtifacts: [], requiredReceiptEffects: ["read" as const], mustPassGates: [] },
});

describe("bounded scheduler", () => {
  it("detects cycles, raw writes, and worker budget violations", () => {
    const plan: Plan = {
      schemaVersion: "psyclaw/plan/v1",
      runId: "r1",
      tasks: [task("a", ["b"], ["data/raw/a"]), task("b", ["a"])],
      budget: { maxTurns: 10, maxWorkers: 5 },
    };
    const reasons = validatePlan(plan).map((item) => item.reason);
    expect(reasons).toContain("maxWorkers must be between 1 and 4");
    expect(reasons).toContain("raw data is immutable");
    expect(reasons).toContain("task dependency cycle");
  });

  it("returns deterministic dependency-ready batches with path isolation", () => {
    const plan: Plan = {
      schemaVersion: "psyclaw/plan/v1",
      runId: "r1",
      tasks: [task("a"), task("b", [], ["notes/a/detail.md"]), task("c", ["a"])],
      budget: { maxTurns: 10, maxWorkers: 3 },
    };
    expect(nextReadyBatch(plan, new Set())).toEqual([plan.tasks[0]]);
    expect(nextReadyBatch(plan, new Set(["a"])).map((item) => item.id)).toEqual(["b", "c"]);
  });

  it("fails closed for unknown completed ids and tampered running tasks", () => {
    const plan: Plan = {
      schemaVersion: "psyclaw/plan/v1",
      runId: "r1",
      tasks: [task("a"), task("b", ["a"])],
      budget: { maxTurns: 10, maxWorkers: 2 },
    };
    expect(nextReadyBatch(plan, new Set(["not-in-plan"]))).toEqual([]);
    expect(nextReadyBatch(plan, new Set(), [{ ...plan.tasks[0]!, ownedPaths: ["notes/other"] }])).toEqual([]);
    expect(nextReadyBatch({ ...plan, tasks: [{ ...plan.tasks[0]!, deps: "bad" as never }] }, new Set())).toEqual([]);
  });
});
