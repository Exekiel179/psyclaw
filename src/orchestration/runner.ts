import { createHash, randomUUID } from "node:crypto";
import { isAbsolute, join, relative, resolve } from "node:path";
import { lstatSync, readFileSync, realpathSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { Type, type Static } from "typebox";
import { Compile } from "typebox/compile";
import type { Effect, ToolReceipt } from "../core/contracts.js";
import { sha256Text } from "../core/hash.js";
import { atomicWriteFile } from "../project/jsonl.js";
import { projectPaths } from "../project/paths.js";
import { JsonlMemoryStore } from "../memory/store.js";
import type { Plan, TaskNode, WorkerReport } from "./contracts.js";
import { nextReadyBatch, validatePlan, type PlanDiagnostic } from "./scheduler.js";

/**
 * The planner boundary intentionally has no tool or filesystem capability.
 * A caller gives us an opaque planner result and we only accept a strict Plan.
 */
export interface PlannerRequest {
  goal: string;
  paradigm?: string;
  runId?: string;
}

export type Planner = (request: PlannerRequest) => unknown | Promise<unknown>;

const EffectSchema = Type.Union([
  Type.Literal("read"),
  Type.Literal("write"),
  Type.Literal("network"),
  Type.Literal("destructive"),
]);

const CompletionContractSchema = Type.Object({
  requiredArtifacts: Type.Array(Type.String({ minLength: 1 })),
  requiredReceiptEffects: Type.Array(EffectSchema),
  mustPassGates: Type.Array(Type.String({ minLength: 1 })),
}, { additionalProperties: false });

const TaskNodeSchema = Type.Object({
  id: Type.String({ minLength: 1 }),
  role: Type.Union([
    Type.Literal("planner"),
    Type.Literal("researcher"),
    Type.Literal("analyst"),
    Type.Literal("critic"),
    Type.Literal("writer"),
    Type.Literal("verifier"),
  ]),
  objective: Type.String({ minLength: 1 }),
  deps: Type.Array(Type.String({ minLength: 1 })),
  ownedPaths: Type.Array(Type.String({ minLength: 1 })),
  parallelSafe: Type.Boolean(),
  inputs: Type.Array(Type.String()),
  outputs: Type.Array(Type.String()),
  // Kept optional for compatibility with existing v1 plans. Runtime still
  // defaults to read-only and never implicitly grants network/destructive.
  allowedEffects: Type.Optional(Type.Array(EffectSchema)),
  completionContract: CompletionContractSchema,
}, { additionalProperties: false });

export const PlanSchema = Type.Object({
  schemaVersion: Type.Literal("psyclaw/plan/v1"),
  runId: Type.String({ minLength: 1 }),
  tasks: Type.Array(TaskNodeSchema, { minItems: 1 }),
  budget: Type.Object({
    maxTurns: Type.Integer({ minimum: 1 }),
    maxWorkers: Type.Integer({ minimum: 1, maximum: 4 }),
  }, { additionalProperties: false }),
  horizon: Type.Optional(Type.Object({
    strategy: Type.Literal("hierarchical-plan-act-reflect"),
    maxIterations: Type.Integer({ minimum: 1 }),
    reflectionEvery: Type.Integer({ minimum: 1 }),
  }, { additionalProperties: false })),
}, { additionalProperties: false });

type PlanShape = Static<typeof PlanSchema>;
const compiledPlan = Compile(PlanSchema);

export class PlanSchemaError extends Error {
  public readonly diagnostics: string[];

  public constructor(diagnostics: string[]) {
    super(`Plan schema invalid: ${diagnostics.join("; ")}`);
    this.name = "PlanSchemaError";
    this.diagnostics = diagnostics;
  }
}

/** Parse and validate the only value a planner is allowed to hand to runtime. */
export function validatePlanSchema(value: unknown): Plan {
  if (!compiledPlan.Check(value)) {
    const diagnostics = [...compiledPlan.Errors(value)].map((error) => {
      const path = "path" in error && typeof error.path === "string" ? error.path : "/";
      return `${path}: ${error.message}`;
    });
    throw new PlanSchemaError(diagnostics);
  }
  const plan = value as PlanShape;
  const diagnostics: string[] = [];
  if (!isSafeRunId(plan.runId)) diagnostics.push("/runId: unsafe run id");
  const ids = new Set<string>();
  for (const [index, task] of plan.tasks.entries()) {
    if (!isSafeTaskId(task.id)) diagnostics.push(`/tasks/${index}/id: unsafe task id`);
    if (ids.has(task.id)) diagnostics.push(`/tasks/${index}/id: duplicate task id`);
    ids.add(task.id);
    if (task.allowedEffects && new Set(task.allowedEffects).size !== task.allowedEffects.length) {
      diagnostics.push(`/tasks/${index}/allowedEffects: duplicate effect`);
    }
    for (const [depIndex, dep] of task.deps.entries()) {
      if (!isSafeTaskId(dep)) diagnostics.push(`/tasks/${index}/deps/${depIndex}: unsafe task id`);
    }
  }
  if (diagnostics.length > 0) throw new PlanSchemaError(diagnostics);
  return plan;
}

/** Alias used by integrations that call the boundary an "accepted plan". */
export const acceptPlan = validatePlanSchema;

/** Execute a planner with no ambient tool context, then enforce the Plan schema. */
export async function planOnly(planner: Planner, request: PlannerRequest): Promise<Plan> {
  return validatePlanSchema(await planner(request));
}

export interface WorkerArtifact {
  path: string;
  sha256?: string;
}

type TaskWithEffects = TaskNode & { allowedEffects?: Effect[] };

export interface WorkerExecutionResult {
  report: WorkerReport;
  artifacts?: (string | WorkerArtifact)[];
  receipts?: ToolReceipt[];
  passedGates?: string[];
  /** Optional revision generated by the coordinator; stale revisions are rejected. */
  specRevision?: string;
}

export interface WorkerContext {
  runId: string;
  dispatchId: string;
  attempt: number;
  task: TaskNode;
  /** MVP workers receive this as true and should only inspect inputs. */
  readOnly: boolean;
  signal: AbortSignal;
}

export type WorkerExecutor = (
  task: TaskNode,
  context: WorkerContext,
) => WorkerExecutionResult | WorkerReport | Promise<WorkerExecutionResult | WorkerReport>;

export interface OrchestratorOptions {
  executor: WorkerExecutor;
  /** Project root used for the default checkpoint location. */
  root?: string;
  checkpointPath?: string;
  /** An input fingerprint that must remain stable across resume. */
  inputDigest?: string;
  /** Coordinator revision that must remain stable across resume. */
  specRevision?: string;
  /** Runtime budget; a resume may explicitly raise this after human approval. */
  maxTurns?: number;
  /** Can only lower the plan's worker count; never raises the hard cap of four. */
  maxWorkers?: number;
  /** Explicit human-approved write mode. It is false by default. */
  allowWrites?: boolean;
  /** Grants network effects. `allowWrites` never implies this. */
  allowNetwork?: boolean;
  /** Grants destructive effects. `allowWrites` never implies this. */
  allowDestructive?: boolean;
  now?: () => string;
  onEvent?: (event: RunnerEvent) => void | Promise<void>;
  /** Cooperative pause hook checked between task batches. */
  pauseRequested?: () => boolean | Promise<boolean>;
}

export interface RunnerEvent {
  type: "planned" | "started" | "completed" | "blocked" | "checkpoint";
  runId: string;
  at: string;
  taskId?: string;
  dispatchId?: string;
  message?: string;
}

export type TaskRunStatus = "pending" | "running" | "succeeded" | "failed" | "blocked";

export interface TaskCheckpoint {
  status: TaskRunStatus;
  dispatchId?: string;
  attempt: number;
  report?: WorkerReport;
  artifacts: string[];
  artifactRecords?: WorkerArtifact[];
  receipts: ToolReceipt[];
  passedGates: string[];
}

export interface RunnerCheckpoint {
  schemaVersion: "psyclaw/orchestrator-checkpoint/v1";
  runId: string;
  planHash: string;
  inputDigest?: string;
  specRevision?: string;
  budgetLimit: number;
  budgetUsed: number;
  tasks: Record<string, TaskCheckpoint>;
  writtenPaths: string[];
  updatedAt: string;
}

export interface OrchestrationResult {
  runId: string;
  status: "completed" | "paused" | "blocked";
  planHash: string;
  budgetUsed: number;
  checkpoint?: RunnerCheckpoint;
  reports: WorkerReport[];
  diagnostics: string[];
}

export interface NormalizedWorkerResult {
  report: WorkerReport;
  artifacts: string[];
  artifactRecords?: WorkerArtifact[];
  artifactErrors?: string[];
  receipts: ToolReceipt[];
  passedGates: string[];
  specRevision?: string;
  schemaValid: boolean;
}

interface InternalState {
  checkpoint: RunnerCheckpoint;
  reportByTask: Map<string, WorkerReport>;
}

/**
 * A deliberately small coordinator. It owns scheduling and acceptance, while
 * the executor owns the actual Pi/skill/MCP call. No model output can mutate
 * task state without passing the checks below.
 */
export class BoundedOrchestrator {
  private readonly options: OrchestratorOptions;
  private checkpointWrite: Promise<void> = Promise.resolve();

  public constructor(options: OrchestratorOptions) {
    this.options = options;
  }

  public async run(planValue: unknown): Promise<OrchestrationResult> {
    let plan: Plan;
    try {
      plan = validatePlanSchema(planValue);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Plan schema invalid";
      return this.blockedWithoutPlan(String(message));
    }
    const diagnostics = validatePlan(plan);
    const policyDiagnostics = validateRunnerPolicy(plan, this.options);
    const allDiagnostics = [...diagnostics, ...policyDiagnostics].filter((item) => item.severity === "block").map((item) => item.reason);
    if (allDiagnostics.length > 0) {
      return this.blocked(plan, allDiagnostics);
    }
    const checkpoint = emptyCheckpoint(plan, this.options);
    const state: InternalState = { checkpoint, reportByTask: new Map() };
    await this.persist(state.checkpoint);
    await this.emit({ type: "planned", runId: plan.runId, at: this.timestamp() });
    return this.execute(plan, state);
  }

  public async resume(planValue: unknown): Promise<OrchestrationResult> {
    let plan: Plan;
    try {
      plan = validatePlanSchema(planValue);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Plan schema invalid";
      return this.blockedWithoutPlan(String(message));
    }
    const diagnostics = [...validatePlan(plan), ...validateRunnerPolicy(plan, this.options)]
      .filter((item) => item.severity === "block").map((item) => item.reason);
    if (diagnostics.length > 0) return this.blocked(plan, diagnostics);
    const path = this.checkpointPath(plan.runId);
    if (!path) return this.blocked(plan, ["checkpoint path is required for resume"]);
    let checkpoint: RunnerCheckpoint;
    try {
      this.assertCheckpointPath(path);
      checkpoint = parseCheckpoint(JSON.parse(await readFile(path, "utf8")));
    } catch (error) {
      return this.blocked(plan, [`checkpoint unavailable or invalid: ${error instanceof Error ? error.message : String(error)}`]);
    }
    const expectedHash = hashPlan(plan);
    if (checkpoint.runId !== plan.runId) return this.blocked(plan, ["checkpoint run id mismatch"]);
    if (checkpoint.planHash !== expectedHash) return this.blocked(plan, ["checkpoint plan hash mismatch"]);
    if (this.options.inputDigest !== undefined && checkpoint.inputDigest !== this.options.inputDigest) {
      return this.blocked(plan, ["checkpoint input digest drift"]);
    }
    if (checkpoint.inputDigest !== undefined && this.options.inputDigest === undefined) {
      return this.blocked(plan, ["checkpoint input digest must be supplied for resume"]);
    }
    if (this.options.specRevision !== undefined && checkpoint.specRevision !== this.options.specRevision) {
      return this.blocked(plan, ["checkpoint spec revision drift"]);
    }
    if (checkpoint.specRevision !== undefined && this.options.specRevision === undefined) {
      return this.blocked(plan, ["checkpoint spec revision must be supplied for resume"]);
    }
    // A process crash can leave a task marked running. It has no live worker
    // after restart, so make it pending and issue a fresh dispatch id. A
    // result carrying the old id can then never overwrite the resumed task.
    for (const item of Object.values(checkpoint.tasks)) {
      if (item.status === "running") {
        item.status = "pending";
        delete item.dispatchId;
      }
    }
    if (checkpoint.budgetUsed > effectiveBudget(plan, this.options)) {
      return this.blocked(plan, ["checkpoint budget already exceeds the requested budget"]);
    }
    const planTaskIds = new Set(plan.tasks.map((task) => task.id));
    const checkpointTaskIds = new Set(Object.keys(checkpoint.tasks));
    if (planTaskIds.size !== checkpointTaskIds.size || [...planTaskIds].some((id) => !checkpointTaskIds.has(id))) {
      return this.blocked(plan, ["checkpoint task set does not match plan"]);
    }
    // A persisted success is only a hint. Re-run the exact completion
    // contract before allowing its dependants to proceed; files and receipts
    // may have changed while the process was down.
    for (const task of plan.tasks) {
      const item = checkpoint.tasks[task.id];
      if (item?.status !== "succeeded") continue;
      const reaccepted = item.report
        ? verifyWorkerCompletion(task, {
          report: item.report,
          artifacts: item.artifactRecords ?? item.artifacts,
          receipts: item.receipts,
          passedGates: item.passedGates,
        }, {
          readOnly: this.taskIsReadOnly(task),
          ...(this.options.root !== undefined ? { artifactRoot: this.options.root } : {}),
          expectedRunId: plan.runId,
          expectedTaskId: task.id,
          ...(item.dispatchId !== undefined ? { expectedDispatchId: item.dispatchId } : {}),
          ...(this.options.specRevision !== undefined ? { expectedSpecRevision: this.options.specRevision } : {}),
          allowedEffects: this.allowedEffects(task),
        })
        : { ok: false, reasons: ["succeeded checkpoint has no worker report"] };
      if (!reaccepted.ok) {
        item.status = "pending";
        delete item.dispatchId;
        delete item.report;
        item.artifacts = [];
        delete item.artifactRecords;
        item.receipts = [];
        item.passedGates = [];
      }
    }
    const state: InternalState = {
      checkpoint: {
        ...checkpoint,
        budgetLimit: effectiveBudget(plan, this.options),
        updatedAt: this.timestamp(),
      },
      reportByTask: new Map(
        Object.entries(checkpoint.tasks)
          .filter(([, item]) => item.status === "succeeded" && item.report !== undefined)
          .map(([id, item]) => [id, item.report as WorkerReport]),
      ),
    };
    await this.persist(state.checkpoint);
    return this.execute(plan, state);
  }

  private async execute(plan: Plan, state: InternalState): Promise<OrchestrationResult> {
    const diagnostics: string[] = [];
    const tasks = state.checkpoint.tasks;
    const completed = new Set(Object.entries(tasks).filter(([, item]) => item.status === "succeeded").map(([id]) => id));
    const maxWorkers = effectiveWorkers(plan, this.options);
    const controller = new AbortController();

    while (completed.size < plan.tasks.length) {
      if (await this.options.pauseRequested?.()) {
        await this.persist(state.checkpoint);
        await this.emit({ type: "checkpoint", runId: plan.runId, at: this.timestamp(), message: "pause requested by human" });
        return this.result(plan, state, "paused", [...diagnostics, "pause requested by human"]);
      }
      const running = Object.entries(tasks)
        .filter(([, item]) => item.status === "running")
        .map(([id]) => plan.tasks.find((task) => task.id === id))
        .filter((task): task is TaskNode => task !== undefined);
      const ready = nextReadyBatch(plan, completed, running).slice(0, maxWorkers);
      const pending = plan.tasks.filter((task) => tasks[task.id]?.status === "pending");
      if (ready.length === 0) {
        if (pending.length === 0) break;
        const unresolved = pending.map((task) => task.id).join(", ");
        const reason = `no schedulable tasks; unresolved or failed dependencies: ${unresolved}`;
        diagnostics.push(reason);
        await this.markBlocked(state, reason);
        return this.result(plan, state, "blocked", diagnostics);
      }

      const remainingBudget = state.checkpoint.budgetLimit - state.checkpoint.budgetUsed;
      if (remainingBudget <= 0) {
        diagnostics.push("worker turn budget exhausted");
        await this.persist(state.checkpoint);
        return this.result(plan, state, "paused", diagnostics);
      }
      const dispatchable = ready.slice(0, remainingBudget);
      if (dispatchable.length < ready.length) diagnostics.push("worker turn budget will pause before all ready tasks run");
      const dispatches = dispatchable.map((task) => this.dispatch(plan, state, task, controller.signal));
      await Promise.all(dispatches);
      for (const task of dispatchable) {
        if (tasks[task.id]?.status === "succeeded") completed.add(task.id);
        if (tasks[task.id]?.status === "failed" || tasks[task.id]?.status === "blocked") {
          const reason = tasks[task.id]?.report?.blockers.join("; ") || `task ${task.id} failed`;
          diagnostics.push(reason);
          await this.persist(state.checkpoint);
          return this.result(plan, state, "blocked", diagnostics);
        }
      }
      if (dispatchable.length < ready.length) {
        await this.persist(state.checkpoint);
        return this.result(plan, state, "paused", diagnostics);
      }
    }

    await this.persist(state.checkpoint);
    await this.emit({ type: "completed", runId: plan.runId, at: this.timestamp(), message: "all task completion contracts passed" });
    return this.result(plan, state, "completed", diagnostics);
  }

  private async dispatch(plan: Plan, state: InternalState, task: TaskNode, signal: AbortSignal): Promise<void> {
    const entry = state.checkpoint.tasks[task.id];
    if (!entry || entry.status !== "pending") return;
    const attempt = entry.attempt + 1;
    const dispatchId = `${plan.runId}:${task.id}:${attempt}:${randomUUID().slice(0, 8)}`;
    entry.status = "running";
    entry.attempt = attempt;
    entry.dispatchId = dispatchId;
    state.checkpoint.budgetUsed += 1;
    await this.persist(state.checkpoint);
    await this.emit({ type: "started", runId: plan.runId, at: this.timestamp(), taskId: task.id, dispatchId });

    let raw: WorkerExecutionResult | WorkerReport;
    try {
      raw = await this.options.executor(task, {
        runId: plan.runId,
        dispatchId,
        attempt,
        task,
          readOnly: this.taskIsReadOnly(task),
        signal,
      });
    } catch (error) {
      // A thrown executor result is never treated as success.
      entry.status = "failed";
      entry.report = failedReport(task.id, dispatchId, `executor threw: ${error instanceof Error ? error.message : String(error)}`);
      await this.draftReflection(plan, task, entry.report.summary, entry.report.blockers);
      await this.persist(state.checkpoint);
      return;
    }

    // The entry may have been superseded by a resume/abort while the worker
    // was away. A late result is observed but cannot overwrite current state.
    if (entry.status !== "running" || entry.dispatchId !== dispatchId) return;
    const normalized = normalizeWorkerResult(raw);
    const acceptance = verifyWorkerCompletion(task, normalized, {
      readOnly: this.taskIsReadOnly(task),
      writtenPaths: state.checkpoint.writtenPaths,
      reservedPaths: plan.tasks
        .filter((candidate) => candidate.id !== task.id && state.checkpoint.tasks[candidate.id]?.status === "running")
        .flatMap((candidate) => candidate.ownedPaths),
      expectedRunId: plan.runId,
      expectedTaskId: task.id,
      expectedDispatchId: dispatchId,
      ...(this.options.specRevision !== undefined ? { expectedSpecRevision: this.options.specRevision } : {}),
      ...(this.options.root !== undefined ? { artifactRoot: this.options.root } : {}),
      allowedEffects: this.allowedEffects(task),
      seenIdempotencyKeys: Object.values(state.checkpoint.tasks).flatMap((item) => item.receipts
        .map((receipt) => receipt.idempotencyKey)
        .filter((key): key is string => typeof key === "string")),
    });
    if (!acceptance.ok) {
      entry.status = "blocked";
      entry.report = failedReport(task.id, dispatchId, acceptance.reasons.join("; "), normalized.report);
      await this.draftReflection(plan, task, entry.report.summary, entry.report.blockers);
      await this.persist(state.checkpoint);
      await this.emit({ type: "blocked", runId: plan.runId, at: this.timestamp(), taskId: task.id, dispatchId, message: acceptance.reasons.join("; ") });
      return;
    }
    entry.status = "succeeded";
    entry.report = normalized.report;
    entry.artifacts = normalized.artifacts;
    if (normalized.artifactRecords && normalized.artifactRecords.length > 0) {
      entry.artifactRecords = normalized.artifactRecords;
    }
    entry.receipts = normalized.receipts;
    entry.passedGates = normalized.passedGates;
    for (const path of normalized.report.filesModified) state.checkpoint.writtenPaths.push(normalizePath(path));
    state.reportByTask.set(task.id, normalized.report);
    await this.persist(state.checkpoint);
    await this.emit({ type: "completed", runId: plan.runId, at: this.timestamp(), taskId: task.id, dispatchId });
  }

  /** Persist failure experience as a pending lesson; human approval promotes it. */
  private async draftReflection(plan: Plan, task: TaskNode, summary: string, blockers: readonly string[]): Promise<void> {
    if (!this.options.root) return;
    const now = this.timestamp();
    try {
      await new JsonlMemoryStore(this.options.root).draft({
        id: `lesson_${plan.runId}_${task.id}_${Date.now()}`,
        kind: "lesson",
        scope: "project",
        content: { strategy: plan.horizon?.strategy ?? "plan-act", task: task.objective, summary, blockers: [...blockers] },
        sourceRefs: [`run:${plan.runId}`, `task:${task.id}`],
        confidence: 0.5,
        status: "pending",
        createdAt: now,
        updatedAt: now,
      });
    } catch {
      // Reflection must never turn an already-recorded worker failure into a new failure.
    }
  }

  private checkpointPath(runId: string): string | undefined {
    return this.options.checkpointPath ?? (this.options.root ? join(projectPaths(this.options.root).runs, `${runId}.checkpoint.json`) : undefined);
  }

  private allowedEffects(task: TaskNode): Set<Effect> {
    const declared = (task as TaskWithEffects).allowedEffects;
    // `allowWrites` is a host ceiling, not an implicit task permission. A
    // planner must explicitly declare `allowedEffects: ["read", "write"]`
    // before a write can be accepted; omitted declarations remain read-only.
    const requested: Effect[] = declared === undefined ? ["read"] : declared;
    // Each effect class needs its own explicit host approval: write from
    // allowWrites, network from allowNetwork, destructive from allowDestructive.
    // allowWrites never implicitly grants network or destructive.
    const effective: Effect[] = [];
    for (const effect of requested) {
      if (effect === "read") effective.push("read");
      else if (effect === "write" && this.options.allowWrites) effective.push("write");
      else if (effect === "network" && this.options.allowNetwork) effective.push("network");
      else if (effect === "destructive" && this.options.allowDestructive) effective.push("destructive");
    }
    return new Set<Effect>(effective);
  }

  private taskAllowsWrite(task: TaskNode): boolean {
    return this.allowedEffects(task).has("write");
  }

  private taskIsReadOnly(task: TaskNode): boolean {
    return [...this.allowedEffects(task)].every((effect) => effect === "read");
  }

  private async persist(checkpoint: RunnerCheckpoint): Promise<void> {
    const path = this.checkpointPath(checkpoint.runId);
    if (!path) return;
    this.assertCheckpointPath(path);
    const operation = this.checkpointWrite.catch(() => undefined).then(async () => {
      checkpoint.updatedAt = this.timestamp();
      await atomicWriteFile(path, `${JSON.stringify(checkpoint, null, 2)}\n`);
      await this.emit({ type: "checkpoint", runId: checkpoint.runId, at: checkpoint.updatedAt });
    });
    this.checkpointWrite = operation.catch(() => undefined);
    await operation;
  }

  private async markBlocked(state: InternalState, reason: string): Promise<void> {
    for (const item of Object.values(state.checkpoint.tasks)) {
      if (item.status === "pending") item.status = "blocked";
    }
    await this.persist(state.checkpoint);
    await this.emit({ type: "blocked", runId: state.checkpoint.runId, at: this.timestamp(), message: reason });
  }

  private async emit(event: RunnerEvent): Promise<void> {
    await this.options.onEvent?.(event);
  }

  private timestamp(): string {
    return (this.options.now ?? (() => new Date().toISOString()))();
  }

  private assertCheckpointPath(path: string): void {
    if (!this.options.root) {
      if (this.options.checkpointPath) throw new Error("custom checkpoint path requires a project root");
      return;
    }
    const base = resolve(this.options.root);
    const candidate = resolve(path);
    const rel = relative(base, candidate).replaceAll("\\", "/");
    if (!rel || rel === ".." || rel.startsWith("../") || isAbsolute(rel) || rel.toLowerCase().startsWith(".git/") || rel.toLowerCase() === ".git") {
      throw new Error("checkpoint path must remain inside the project root");
    }
    // Check existing paths and every ancestor. A symlink introduced after the
    // lexical check must not redirect an atomic checkpoint write outside root.
    const rootReal = realpathSync(base);
    let current = candidate;
    while (true) {
      try {
        const stat = lstatSync(current);
        if (stat.isSymbolicLink()) throw new Error("checkpoint path ancestor symlink is not allowed");
        const real = realpathSync(current);
        const realRel = relative(rootReal, real).replaceAll("\\", "/");
        if (realRel === ".." || realRel.startsWith("../") || isAbsolute(realRel)) {
          throw new Error("checkpoint path resolves outside the project root");
        }
        if (realRel === "" && current !== base) throw new Error("checkpoint path resolves to project root");
        return;
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
        const parent = resolve(current, "..");
        if (parent === current) throw new Error("checkpoint path has no existing project ancestor");
        current = parent;
      }
    }
  }

  private blocked(plan: Plan, diagnostics: string[]): OrchestrationResult {
    const checkpoint = emptyCheckpoint(plan, this.options);
    for (const task of plan.tasks) {
      const item = checkpoint.tasks[task.id];
      if (item) item.status = "blocked";
    }
    return {
      runId: plan.runId,
      status: "blocked",
      planHash: hashPlan(plan),
      budgetUsed: 0,
      checkpoint,
      reports: [],
      diagnostics,
    };
  }

  private blockedWithoutPlan(reason: string): OrchestrationResult {
    return { runId: "unknown", status: "blocked", planHash: "", budgetUsed: 0, reports: [], diagnostics: [reason] };
  }

  private result(plan: Plan, state: InternalState, status: OrchestrationResult["status"], diagnostics: string[]): OrchestrationResult {
    return {
      runId: plan.runId,
      status,
      planHash: state.checkpoint.planHash,
      budgetUsed: state.checkpoint.budgetUsed,
      checkpoint: state.checkpoint,
      reports: [...state.reportByTask.values()],
      diagnostics,
    };
  }
}

/** Alias kept short for callers that do not need the implementation name. */
export const Orchestrator = BoundedOrchestrator;

export async function runPlan(plan: unknown, options: OrchestratorOptions): Promise<OrchestrationResult> {
  return new BoundedOrchestrator(options).run(plan);
}

export async function resumePlan(plan: unknown, options: OrchestratorOptions): Promise<OrchestrationResult> {
  return new BoundedOrchestrator(options).resume(plan);
}

export interface CompletionAcceptance {
  ok: boolean;
  reasons: string[];
}

export function verifyWorkerCompletion(
  task: TaskNode,
  result: NormalizedWorkerResult | WorkerExecutionResult,
  policy: {
    readOnly: boolean;
    writtenPaths?: readonly string[];
    artifactRoot?: string;
    allowedEffects?: ReadonlySet<Effect>;
    seenIdempotencyKeys?: readonly string[];
    expectedRunId?: string;
    expectedTaskId?: string;
    expectedDispatchId?: string;
    expectedSpecRevision?: string;
    reservedPaths?: readonly string[];
  } = { readOnly: true },
): CompletionAcceptance {
  const normalized = normalizeWorkerResult(result);
  const reasons: string[] = [];
  if (!normalized.schemaValid) return { ok: false, reasons: ["worker report schema invalid"] };
  const report = normalized.report;
  if (report.taskId !== task.id) reasons.push("worker report task id mismatch");
  if (policy.expectedTaskId !== undefined && report.taskId !== policy.expectedTaskId) reasons.push("worker report task id does not match dispatch");
  if (policy.expectedDispatchId !== undefined && report.dispatchId !== policy.expectedDispatchId) reasons.push("late or stale worker dispatch result");
  if (report.outcome !== "succeeded") reasons.push(`worker outcome is ${report.outcome}`);
  if (report.verification.some((item) => item.exitCode !== 0)) reasons.push("worker verification command failed");
  if (normalized.specRevision !== undefined && normalized.specRevision.trim() === "") reasons.push("worker spec revision is empty");
  if (policy.expectedSpecRevision !== undefined && normalized.specRevision !== policy.expectedSpecRevision) {
    reasons.push("worker spec revision mismatch or missing");
  }

  const modifications = report.filesModified.map(normalizePath);
  if (policy.readOnly && modifications.length > 0) reasons.push("read-only worker reported file modifications");
  for (const path of modifications) {
    if (isProtectedPath(path)) reasons.push(`protected path modification denied: ${path}`);
    if (!policy.readOnly && !isOwnedPath(task.ownedPaths, path)) reasons.push(`file modification outside owned paths: ${path}`);
    if (policy.writtenPaths?.some((existing) => pathsOverlap(existing, path))) reasons.push(`parallel write overlap: ${path}`);
    if (policy.reservedPaths?.some((reserved) => pathsOverlap(reserved, path))) reasons.push(`parallel write overlap: ${path}`);
  }

  const contract = task.completionContract;
  const artifactRecords: WorkerArtifact[] = normalized.artifactRecords ?? normalized.artifacts.map((path): WorkerArtifact => ({ path }));
  if (contract.requiredArtifacts.length > 0 && !policy.artifactRoot) {
    reasons.push("required artifacts cannot be verified without a project root");
  }
  for (const artifact of artifactRecords) {
    if (typeof artifact.path !== "string" || artifact.path.trim() === "") {
      reasons.push("artifact path must be a non-empty string");
      continue;
    }
    if (artifact.sha256 !== undefined && !isSha256(artifact.sha256)) {
      reasons.push(`artifact hash is invalid: ${artifact.path}`);
      continue;
    }
    if (policy.artifactRoot) {
      const check = verifyArtifactOnDisk(policy.artifactRoot, artifact);
      if (!check.ok) reasons.push(check.reason);
    }
  }
  for (const error of normalized.artifactErrors ?? []) reasons.push(error);
  for (const required of contract.requiredArtifacts) {
    const requiredPath = normalizePath(required);
    const record = artifactRecords.find((artifact) => normalizePath(artifact.path) === requiredPath);
    if (!record) {
      reasons.push(`missing required artifact: ${required}`);
      continue;
    }
    // A required artifact must be produced under this task's owned paths or
    // outputs; a pre-existing arbitrary file (e.g. package.json) cannot stand in.
    if (!isOwnedOrOutput(task, requiredPath)) {
      reasons.push(`required artifact outside owned paths/outputs: ${required}`);
    }
    if (record.sha256 === undefined || !isSha256(record.sha256)) {
      reasons.push(`required artifact missing a valid sha256: ${required}`);
    }
    if (policy.artifactRoot) {
      const check = verifyArtifactOnDisk(policy.artifactRoot, record);
      if (!check.ok) reasons.push(check.reason);
    }
  }
  for (const requiredEffect of contract.requiredReceiptEffects) {
    if (!normalized.receipts.some((receipt) => isReceipt(receipt) && receipt.effect === requiredEffect && receipt.ok && receipt.approval !== "denied")) {
      reasons.push(`missing successful receipt effect: ${requiredEffect}`);
    }
  }
  if (modifications.length > 0 && !normalized.receipts.some((receipt) => (
    isReceipt(receipt) && receipt.effect === "write" && receipt.ok && receipt.approval === "approved" &&
    typeof receipt.idempotencyKey === "string" && receipt.idempotencyKey.length > 0
  ))) {
    reasons.push("file modification lacks approved idempotent write receipt");
  }
  for (const gate of contract.mustPassGates) {
    if (!normalized.passedGates.includes(gate)) reasons.push(`required gate not passed: ${gate}`);
  }
  const seenKeys = new Set(policy.seenIdempotencyKeys ?? []);
  for (const receipt of normalized.receipts) {
    if (!isReceipt(receipt)) {
      reasons.push("worker receipt schema invalid");
      continue;
    }
    if (policy.expectedRunId !== undefined && receipt.runId !== policy.expectedRunId) reasons.push("worker receipt run id mismatch");
    if (policy.expectedTaskId !== undefined && receipt.taskId !== policy.expectedTaskId) reasons.push("worker receipt task id mismatch");
    if (policy.readOnly && receipt.effect !== "read") reasons.push(`read-only worker requested ${receipt.effect} effect`);
    if (policy.allowedEffects && !policy.allowedEffects.has(receipt.effect)) {
      reasons.push(`undeclared ${receipt.effect} effect: ${receipt.tool}`);
    }
    if (receipt.effect !== "read" && (receipt.approval !== "approved" || !isValidIdempotencyKey(receipt.idempotencyKey))) {
      reasons.push(`side-effect receipt lacks approval/idempotency: ${receipt.tool}`);
    }
    if (receipt.idempotencyKey !== undefined) {
      if (seenKeys.has(receipt.idempotencyKey)) reasons.push(`duplicate idempotency key: ${receipt.idempotencyKey}`);
      seenKeys.add(receipt.idempotencyKey);
    }
  }
  return { ok: reasons.length === 0, reasons: [...new Set(reasons)] };
}

function normalizeWorkerResult(raw: unknown): NormalizedWorkerResult {
  if (isNormalizedResult(raw)) return raw;
  if (isExecutionResult(raw)) {
    const schemaValid = isWorkerReport(raw.report);
    const report = schemaValid ? raw.report : invalidReport(raw.report);
    const artifactRecords: WorkerArtifact[] = [];
    const artifactErrors: string[] = [];
    if (raw.artifacts !== undefined && !Array.isArray(raw.artifacts)) artifactErrors.push("worker artifacts must be an array");
    const supplied = Array.isArray(raw.artifacts) ? raw.artifacts : report.filesModified;
    for (const item of supplied) {
      if (typeof item === "string") artifactRecords.push({ path: item });
      else if (typeof item === "object" && item !== null && typeof item.path === "string" &&
        (item.sha256 === undefined || typeof item.sha256 === "string")) {
        artifactRecords.push({ path: item.path, ...(item.sha256 !== undefined ? { sha256: item.sha256 } : {}) });
      } else artifactErrors.push("worker artifact record invalid");
    }
    return {
      report,
      artifacts: artifactRecords.map((item) => item.path),
      artifactRecords,
      artifactErrors,
      receipts: Array.isArray(raw.receipts) ? raw.receipts : reportReceipts(report),
      passedGates: Array.isArray(raw.passedGates) && raw.passedGates.every((item) => typeof item === "string")
        ? raw.passedGates
        : reportGates(report),
      ...(raw.specRevision !== undefined ? { specRevision: raw.specRevision } : {}),
      schemaValid,
    };
  }
  const schemaValid = isWorkerReport(raw);
  const report = schemaValid ? raw : invalidReport(raw);
  return {
    report,
    artifacts: report.filesModified,
    artifactRecords: report.filesModified.map((path) => ({ path })),
    artifactErrors: [],
    receipts: reportReceipts(report),
    passedGates: reportGates(report),
    schemaValid,
  };
}

function isExecutionResult(value: unknown): value is WorkerExecutionResult {
  return typeof value === "object" && value !== null && "report" in value;
}

function isNormalizedResult(value: unknown): value is NormalizedWorkerResult {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<NormalizedWorkerResult>;
  return typeof candidate.schemaValid === "boolean" &&
    Array.isArray(candidate.artifactRecords) &&
    Array.isArray(candidate.artifacts) &&
    candidate.report !== undefined;
}

function invalidReport(value: unknown): WorkerReport {
  const candidate = typeof value === "object" && value !== null ? value as Partial<WorkerReport> : {};
  return {
    schemaVersion: candidate.schemaVersion === "psyclaw/worker-report/v1" ? candidate.schemaVersion : "psyclaw/worker-report/v1",
    taskId: typeof candidate.taskId === "string" ? candidate.taskId : "",
    dispatchId: typeof candidate.dispatchId === "string" ? candidate.dispatchId : "",
    outcome: "failed",
    summary: typeof candidate.summary === "string" ? candidate.summary : "invalid worker report",
    filesModified: Array.isArray(candidate.filesModified) && candidate.filesModified.every((item) => typeof item === "string") ? candidate.filesModified : [],
    verification: Array.isArray(candidate.verification) ? candidate.verification as WorkerReport["verification"] : [],
    blockers: ["worker report schema invalid"],
  };
}

function reportReceipts(report: WorkerReport): ToolReceipt[] {
  const candidate = (report as WorkerReport & { receipts?: unknown }).receipts;
  return Array.isArray(candidate) ? candidate as ToolReceipt[] : [];
}

function reportGates(report: WorkerReport): string[] {
  const candidate = (report as WorkerReport & { passedGates?: unknown }).passedGates;
  return Array.isArray(candidate) && candidate.every((item) => typeof item === "string") ? candidate as string[] : [];
}

function isWorkerReport(value: unknown): value is WorkerReport {
  if (typeof value !== "object" || value === null) return false;
  const report = value as Partial<WorkerReport>;
  return (
    report.schemaVersion === "psyclaw/worker-report/v1" &&
    typeof report.taskId === "string" && report.taskId.length > 0 &&
    typeof report.dispatchId === "string" && report.dispatchId.length > 0 &&
    (report.outcome === "succeeded" || report.outcome === "blocked" || report.outcome === "failed") &&
    typeof report.summary === "string" &&
    Array.isArray(report.filesModified) && report.filesModified.every((item) => typeof item === "string") &&
    Array.isArray(report.verification) && report.verification.every((item) => (
      typeof item === "object" && item !== null && typeof item.command === "string" &&
      typeof item.exitCode === "number" && Number.isInteger(item.exitCode)
    )) &&
    Array.isArray(report.blockers) && report.blockers.every((item) => typeof item === "string")
  );
}

function isReceipt(value: unknown): value is ToolReceipt {
  if (typeof value !== "object" || value === null) return false;
  const receipt = value as Partial<ToolReceipt>;
  return receipt.schemaVersion === "psyclaw/tool-receipt/v1" &&
    typeof receipt.runId === "string" && receipt.runId.length > 0 &&
    typeof receipt.taskId === "string" && receipt.taskId.length > 0 &&
    typeof receipt.tool === "string" && receipt.tool.length > 0 &&
    (receipt.effect === "read" || receipt.effect === "write" || receipt.effect === "network" || receipt.effect === "destructive") &&
    (receipt.approval === "not-needed" || receipt.approval === "approved" || receipt.approval === "denied") &&
    typeof receipt.ok === "boolean" &&
    typeof receipt.startedAt === "string" && isTimestamp(receipt.startedAt) &&
    typeof receipt.finishedAt === "string" && isTimestamp(receipt.finishedAt) &&
    new Date(receipt.finishedAt).getTime() >= new Date(receipt.startedAt).getTime() &&
    (receipt.idempotencyKey === undefined || isValidIdempotencyKey(receipt.idempotencyKey));
}

function isSafeRunId(value: string): boolean {
  return /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(value) && value !== "." && value !== "..";
}

function isSafeTaskId(value: string): boolean {
  return /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(value) && value !== "." && value !== "..";
}

function isTimestamp(value: string): boolean {
  // Date.parse accepts surprising values such as `0` or locale strings. A
  // receipt is an audit boundary, so require an unambiguous UTC ISO form.
  return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z$/.test(value) && Number.isFinite(Date.parse(value));
}

function isSha256(value: string): boolean {
  return /^[a-f0-9]{64}$/i.test(value);
}

function isValidIdempotencyKey(value: unknown): value is string {
  return typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$/.test(value);
}

function verifyArtifactOnDisk(root: string, artifact: WorkerArtifact): { ok: true } | { ok: false; reason: string } {
  const normalized = artifact.path.trim().replaceAll("\\", "/");
  if (isAbsoluteOrTraversal(normalized)) return { ok: false, reason: `artifact path escapes project root: ${artifact.path}` };
  const candidate = resolve(root, normalized);
  const base = resolve(root);
  const rel = relative(base, candidate).replaceAll("\\", "/");
  if (!rel || rel === ".." || rel.startsWith("../") || isAbsolute(rel)) {
    return { ok: false, reason: `artifact path escapes project root: ${artifact.path}` };
  }
  try {
    const stat = lstatSync(candidate);
    if (!stat.isFile() || stat.isSymbolicLink()) return { ok: false, reason: `required artifact is not a regular file: ${artifact.path}` };
    const rootReal = realpathSync(base);
    const real = realpathSync(candidate);
    const realRel = relative(rootReal, real).replaceAll("\\", "/");
    if (!realRel || realRel === ".." || realRel.startsWith("../") || isAbsolute(realRel)) {
      return { ok: false, reason: `artifact resolves outside project root: ${artifact.path}` };
    }
    if (artifact.sha256 !== undefined) {
      const actual = createHash("sha256").update(readFileSync(candidate)).digest("hex");
      if (actual.toLowerCase() !== artifact.sha256.toLowerCase()) return { ok: false, reason: `artifact hash mismatch: ${artifact.path}` };
    }
    return { ok: true };
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return { ok: false, reason: `required artifact does not exist: ${artifact.path}` };
    return { ok: false, reason: `artifact could not be verified: ${artifact.path}` };
  }
}

function failedReport(taskId: string, dispatchId: string, reason: string, base?: WorkerReport): WorkerReport {
  return {
    schemaVersion: "psyclaw/worker-report/v1",
    taskId,
    dispatchId,
    outcome: "failed",
    summary: base?.summary ?? "worker did not satisfy completion contract",
    filesModified: base?.filesModified ?? [],
    verification: base?.verification ?? [],
    blockers: [...(base?.blockers ?? []), reason],
  };
}

function emptyCheckpoint(plan: Plan, options: OrchestratorOptions): RunnerCheckpoint {
  const tasks: Record<string, TaskCheckpoint> = {};
  for (const task of plan.tasks) {
    tasks[task.id] = { status: "pending", attempt: 0, artifacts: [], receipts: [], passedGates: [] };
  }
  const inputDigest = options.inputDigest;
  const specRevision = options.specRevision;
  return {
    schemaVersion: "psyclaw/orchestrator-checkpoint/v1",
    runId: plan.runId,
    planHash: hashPlan(plan),
    ...(inputDigest !== undefined ? { inputDigest } : {}),
    ...(specRevision !== undefined ? { specRevision } : {}),
    budgetLimit: effectiveBudget(plan, options),
    budgetUsed: 0,
    tasks,
    writtenPaths: [],
    updatedAt: (options.now ?? (() => new Date().toISOString()))(),
  };
}

function parseCheckpoint(value: unknown): RunnerCheckpoint {
  if (typeof value !== "object" || value === null) throw new Error("checkpoint must be an object");
  const checkpoint = value as Partial<RunnerCheckpoint>;
  if (checkpoint.schemaVersion !== "psyclaw/orchestrator-checkpoint/v1" ||
      typeof checkpoint.runId !== "string" || typeof checkpoint.planHash !== "string" ||
      typeof checkpoint.budgetLimit !== "number" || !Number.isInteger(checkpoint.budgetLimit) || checkpoint.budgetLimit < 1 ||
      typeof checkpoint.budgetUsed !== "number" || !Number.isInteger(checkpoint.budgetUsed) || checkpoint.budgetUsed < 0 ||
      typeof checkpoint.tasks !== "object" || checkpoint.tasks === null || !Array.isArray(checkpoint.writtenPaths) ||
      !checkpoint.writtenPaths.every((item) => typeof item === "string")) {
    throw new Error("checkpoint schema invalid");
  }
  if (!isSafeRunId(checkpoint.runId) || !isSha256(checkpoint.planHash) || !isTimestamp(checkpoint.updatedAt ?? "")) {
    throw new Error("checkpoint identity or timestamp invalid");
  }
  if (!Object.getPrototypeOf(checkpoint.tasks as object) || Object.getPrototypeOf(checkpoint.tasks as object) !== Object.prototype) {
    throw new Error("checkpoint tasks prototype invalid");
  }
  const tasks: Record<string, TaskCheckpoint> = {};
  for (const [id, raw] of Object.entries(checkpoint.tasks as Record<string, unknown>)) {
    if (!isSafeTaskId(id)) throw new Error(`checkpoint task id invalid: ${id}`);
    if (!isTaskCheckpoint(raw)) throw new Error(`checkpoint task invalid: ${id}`);
    tasks[id] = raw;
  }
  return {
    schemaVersion: "psyclaw/orchestrator-checkpoint/v1",
    runId: checkpoint.runId,
    planHash: checkpoint.planHash,
    ...(typeof checkpoint.inputDigest === "string" ? { inputDigest: checkpoint.inputDigest } : {}),
    ...(typeof checkpoint.specRevision === "string" ? { specRevision: checkpoint.specRevision } : {}),
    budgetLimit: checkpoint.budgetLimit,
    budgetUsed: checkpoint.budgetUsed,
    tasks,
    writtenPaths: checkpoint.writtenPaths,
    updatedAt: typeof checkpoint.updatedAt === "string" && checkpoint.updatedAt.length > 0
      ? checkpoint.updatedAt
      : new Date().toISOString(),
  };
}

function isTaskCheckpoint(value: unknown): value is TaskCheckpoint {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Partial<TaskCheckpoint>;
  return (item.status === "pending" || item.status === "running" || item.status === "succeeded" || item.status === "failed" || item.status === "blocked") &&
    typeof item.attempt === "number" && Number.isInteger(item.attempt) && item.attempt >= 0 &&
    Array.isArray(item.artifacts) && item.artifacts.every((entry) => typeof entry === "string") &&
    (item.artifactRecords === undefined || (Array.isArray(item.artifactRecords) && item.artifactRecords.every((entry) => (
      typeof entry === "object" && entry !== null && typeof entry.path === "string" &&
      (entry.sha256 === undefined || (typeof entry.sha256 === "string" && isSha256(entry.sha256)))
    )))) &&
    Array.isArray(item.receipts) && item.receipts.every((entry) => isReceipt(entry)) &&
    Array.isArray(item.passedGates) && item.passedGates.every((entry) => typeof entry === "string") &&
    (item.report === undefined || isWorkerReport(item.report));
}

function validateRunnerPolicy(plan: Plan, options: OrchestratorOptions): PlanDiagnostic[] {
  const diagnostics: PlanDiagnostic[] = [];
  const allowWrites = options.allowWrites ?? false;
  const maxWorkers = effectiveWorkers(plan, options);
  if (options.maxWorkers !== undefined && (!Number.isInteger(options.maxWorkers) || options.maxWorkers < 1 || options.maxWorkers > 4)) {
    diagnostics.push({ severity: "block", reason: "maxWorkers override must be between 1 and 4" });
  }
  if (maxWorkers < 1 || maxWorkers > 4) diagnostics.push({ severity: "block", reason: "effective maxWorkers must be between 1 and 4" });
  if (options.maxTurns !== undefined && (!Number.isInteger(options.maxTurns) || options.maxTurns < 1)) {
    diagnostics.push({ severity: "block", reason: "maxTurns must be a positive integer" });
  }
  for (const task of plan.tasks) {
    for (const rawPath of [...task.ownedPaths, ...task.outputs]) {
      if (isAbsoluteOrTraversal(rawPath)) {
        diagnostics.push({ taskId: task.id, severity: "block", reason: `unsafe owned path: ${rawPath}` });
        continue;
      }
      const path = normalizePath(rawPath);
      if (isProtectedPath(path)) diagnostics.push({ taskId: task.id, severity: "block", reason: `protected owned path: ${rawPath}` });
      if (path === "" || path === "." || path.startsWith("../") || path === "..") {
        diagnostics.push({ taskId: task.id, severity: "block", reason: `unsafe owned path: ${rawPath}` });
      }
    }
    if (!allowWrites && task.outputs.length > 0 && task.parallelSafe === false) {
      // Outputs are declarations, not a permission; leave them schedulable as
      // read-only tasks. Actual modifications are rejected at report time.
    }
  }
  return diagnostics;
}

function effectiveWorkers(plan: Plan, options: OrchestratorOptions): number {
  const requested = options.maxWorkers ?? plan.budget.maxWorkers;
  return Math.min(4, plan.budget.maxWorkers, requested);
}

function effectiveBudget(plan: Plan, options: OrchestratorOptions): number {
  return options.maxTurns ?? plan.budget.maxTurns;
}

function hashPlan(plan: Plan): string {
  return sha256Text(stableStringify(plan));
}

function stableStringify(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map((item) => stableStringify(item)).join(",")}]`;
  const entries = Object.entries(value as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b));
  return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${stableStringify(item)}`).join(",")}}`;
}

function normalizePath(path: string): string {
  const parts = path.replaceAll("\\", "/").split("/");
  const normalized: string[] = [];
  for (const part of parts) {
    if (!part || part === ".") continue;
    if (part === "..") {
      if (normalized.length === 0) {
        normalized.push("..");
      } else if (normalized.at(-1) === "..") {
        normalized.push("..");
      } else {
        normalized.pop();
      }
      continue;
    }
    normalized.push(part);
  }
  return normalized.join("/");
}

function isAbsoluteOrTraversal(path: string): boolean {
  const raw = path.trim().replaceAll("\\", "/");
  return raw.startsWith("/") || raw.startsWith("//") || /^[a-z]:\//i.test(raw) ||
    raw.split("/").some((part) => part === "..");
}

function isProtectedPath(path: string): boolean {
  const normalized = normalizePath(path).toLowerCase();
  return normalized === ".git" || normalized.startsWith(".git/") ||
    normalized === "data/raw" || normalized.startsWith("data/raw/") ||
    normalized.split("/").some((part) => part === "credentials" || part === "credential" || part === "secrets" || part === "secret");
}

function isOwnedPath(ownedPaths: readonly string[], candidate: string): boolean {
  const normalized = normalizePath(candidate);
  return ownedPaths.some((owned) => {
    const path = normalizePath(owned);
    return normalized === path || normalized.startsWith(`${path}/`);
  });
}

function isOwnedOrOutput(task: TaskNode, candidate: string): boolean {
  return isOwnedPath(task.ownedPaths, candidate) || isOwnedPath(task.outputs, candidate);
}

function pathsOverlap(left: string, right: string): boolean {
  const a = normalizePath(left);
  const b = normalizePath(right);
  return a === b || a.startsWith(`${b}/`) || b.startsWith(`${a}/`);
}
