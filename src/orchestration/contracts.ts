import type { Effect, ToolReceipt } from "../core/contracts.js";

export type AgentRole = "planner" | "researcher" | "analyst" | "critic" | "writer" | "verifier";

export interface CompletionContract {
  requiredArtifacts: string[];
  requiredReceiptEffects: Effect[];
  mustPassGates: string[];
}

/** Optional effect ceiling supplied by a trusted coordinator. Omitted means
 * read-only; the runner may never infer network/destructive permission. */
export interface TaskEffects {
  allowedEffects?: Effect[];
}

export interface TaskNode extends TaskEffects {
  id: string;
  role: AgentRole;
  objective: string;
  deps: string[];
  ownedPaths: string[];
  parallelSafe: boolean;
  inputs: string[];
  outputs: string[];
  completionContract: CompletionContract;
}

export interface Plan {
  schemaVersion: "psyclaw/plan/v1";
  runId: string;
  tasks: TaskNode[];
  budget: { maxTurns: number; maxWorkers: number };
  /** Long-horizon policy: checkpointed plan-act cycles with explicit reflection. */
  horizon?: {
    strategy: "hierarchical-plan-act-reflect";
    maxIterations: number;
    reflectionEvery: number;
  };
}

export interface WorkerReport {
  schemaVersion: "psyclaw/worker-report/v1";
  taskId: string;
  dispatchId: string;
  outcome: "succeeded" | "blocked" | "failed";
  summary: string;
  filesModified: string[];
  verification: { command: string; exitCode: number; outputDigest?: string }[];
  blockers: string[];
}

export interface RunEvent {
  schemaVersion: "psyclaw/run-event/v1";
  runId: string;
  type: "planned" | "started" | "receipt" | "gate" | "checkpoint" | "completed" | "blocked";
  at: string;
  taskId?: string;
  receipt?: ToolReceipt;
  message?: string;
}
