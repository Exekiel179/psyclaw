import type { Plan, TaskNode } from "./contracts.js";

export interface PlanDiagnostic {
  // Explicit `undefined` is used while validating malformed tasks. Keeping it
  // in the type avoids accidentally attaching an undefined field under
  // `exactOptionalPropertyTypes`.
  taskId?: string | undefined;
  severity: "block" | "warn";
  reason: string;
}

interface PathDeclaration {
  kind: "owned" | "output";
  raw: string;
  normalized: string;
}

interface TaskPaths {
  owned: PathDeclaration[];
  outputs: PathDeclaration[];
  all: PathDeclaration[];
}

const PROTECTED_NAME = /^(?:credential|credentials|secret|secrets)(?:$|[._-])/i;

/**
 * Scheduler paths are project-relative declarations, not arbitrary filesystem
 * paths. We intentionally reject a `..` segment even when it would collapse
 * back inside the project: accepting it makes the same plan mean different
 * things to different executors and leaves room for symlink/path confusion.
 */
function inspectPath(value: unknown, kind: PathDeclaration["kind"]): { declaration?: PathDeclaration; reasons: string[] } {
  const reasons: string[] = [];
  if (typeof value !== "string") {
    reasons.push(`${kind} path must be a string`);
    return { reasons };
  }

  const raw = value.trim();
  const slashPath = raw.replaceAll("\\", "/");
  if (raw.length === 0) {
    reasons.push(`${kind} path must not be empty`);
    return { reasons };
  }
  if (slashPath.includes("\0") || /[\r\n\t]/u.test(slashPath)) {
    reasons.push(`${kind} path contains a control character`);
  }

  // Reject POSIX-rooted, Windows-rooted, UNC, and drive-relative paths. A
  // drive-relative path such as `C:notes/x` is not safely project-relative.
  if (
    slashPath.startsWith("/") ||
    slashPath.startsWith("//") ||
    /^[a-z]:/i.test(slashPath)
  ) {
    reasons.push(`${kind} path must be project-relative (absolute path denied)`);
  }

  const rawSegments = slashPath.split("/").filter((segment) => segment.length > 0 && segment !== ".");
  if (rawSegments.some((segment) => segment === "..")) {
    reasons.push(`${kind} path traversal is denied`);
  }
  // A colon in a non-drive segment can address an NTFS alternate data stream
  // and has no portable project-relative meaning.
  if (rawSegments.some((segment) => segment.includes(":"))) {
    reasons.push(`${kind} path contains an invalid colon`);
  }

  const collapsedSegments: string[] = [];
  for (const segment of rawSegments) {
    if (segment === "..") {
      if (collapsedSegments.length > 0 && collapsedSegments.at(-1) !== "..") collapsedSegments.pop();
      else collapsedSegments.push("..");
    } else {
      collapsedSegments.push(segment);
    }
  }
  const normalized = collapsedSegments.join("/").toLowerCase();
  const rawLower = rawSegments.map((segment) => segment.toLowerCase());
  const hasRaw = containsDataRaw(rawLower) || containsDataRaw(collapsedSegments.map((segment) => segment.toLowerCase()));
  const hasGit = rawLower.includes(".git") || normalized === ".git" || normalized.startsWith(".git/");
  const hasCredentials = rawLower.some((segment) => PROTECTED_NAME.test(segment)) ||
    normalized.split("/").some((segment) => PROTECTED_NAME.test(segment));
  if (hasRaw) reasons.push("raw data is immutable");
  if (hasGit) reasons.push(".git is protected");
  if (hasCredentials) reasons.push("credentials and secrets are protected");
  if (normalized.length === 0 || normalized === "." || normalized === ".." || normalized.startsWith("../")) {
    reasons.push(`${kind} path must name a project-relative location`);
  }

  return reasons.length > 0
    ? { reasons }
    : { declaration: { kind, raw, normalized }, reasons };
}

function containsDataRaw(segments: readonly string[]): boolean {
  return segments.some((segment, index) => segment === "data" && segments[index + 1] === "raw");
}

function pathsOverlap(left: string, right: string): boolean {
  const a = canonicalForComparison(left);
  const b = canonicalForComparison(right);
  return a === b || a.startsWith(`${b}/`) || b.startsWith(`${a}/`);
}

function canonicalForComparison(path: string): string {
  const parts = path.replaceAll("\\", "/").split("/");
  const normalized: string[] = [];
  for (const part of parts) {
    if (!part || part === ".") continue;
    // Invalid traversal is rejected before this helper is used for a plan;
    // retaining the segment here keeps the function fail-closed for callers
    // passing an untrusted running task to nextReadyBatch.
    if (part === "..") normalized.push("..");
    else normalized.push(part.toLowerCase());
  }
  return normalized.join("/").replace(/\/+$/u, "");
}

function addDiagnostic(diagnostics: PlanDiagnostic[], diagnostic: PlanDiagnostic): void {
  const duplicate = diagnostics.some((item) =>
    item.taskId === diagnostic.taskId && item.severity === diagnostic.severity && item.reason === diagnostic.reason);
  if (!duplicate) diagnostics.push(diagnostic);
}

function taskPaths(task: TaskNode, diagnostics?: PlanDiagnostic[]): TaskPaths {
  const owned: PathDeclaration[] = [];
  const outputs: PathDeclaration[] = [];
  const taskId = typeof task?.id === "string" ? task.id : undefined;
  const add = (value: unknown, kind: PathDeclaration["kind"], target: PathDeclaration[]): void => {
    const inspected = inspectPath(value, kind);
    if (diagnostics) {
      for (const reason of inspected.reasons) addDiagnostic(diagnostics, { taskId, severity: "block", reason });
    }
    if (inspected.declaration) target.push(inspected.declaration);
  };
  const ownedValues: unknown[] = Array.isArray((task as Partial<TaskNode>).ownedPaths)
    ? (task as Partial<TaskNode>).ownedPaths as unknown[]
    : [];
  const outputValues: unknown[] = Array.isArray((task as Partial<TaskNode>).outputs)
    ? (task as Partial<TaskNode>).outputs as unknown[]
    : [];
  for (const path of ownedValues) add(path, "owned", owned);
  for (const path of outputValues) add(path, "output", outputs);
  return { owned, outputs, all: [...owned, ...outputs] };
}

function declarationCovers(owner: string, target: string): boolean {
  const left = canonicalForComparison(owner);
  const right = canonicalForComparison(target);
  return right === left || right.startsWith(`${left}/`);
}

function validateTaskDeclarations(task: TaskNode, diagnostics: PlanDiagnostic[]): TaskPaths {
  const paths = taskPaths(task, diagnostics);
  const taskId = typeof task?.id === "string" ? task.id : undefined;
  if (paths.owned.length !== new Set(paths.owned.map((item) => item.normalized)).size) {
    addDiagnostic(diagnostics, { taskId, severity: "block", reason: "owned paths overlap or are duplicated" });
  }
  for (let index = 0; index < paths.owned.length; index += 1) {
    for (const other of paths.owned.slice(index + 1)) {
      const current = paths.owned[index];
      if (current && pathsOverlap(current.normalized, other.normalized)) {
        addDiagnostic(diagnostics, { taskId, severity: "block", reason: `owned paths overlap: ${current.raw} and ${other.raw}` });
      }
    }
  }
  if (paths.outputs.length !== new Set(paths.outputs.map((item) => item.normalized)).size) {
    addDiagnostic(diagnostics, { taskId, severity: "block", reason: "outputs overlap or are duplicated" });
  }
  for (let index = 0; index < paths.outputs.length; index += 1) {
    for (const other of paths.outputs.slice(index + 1)) {
      const current = paths.outputs[index];
      if (current && pathsOverlap(current.normalized, other.normalized)) {
        addDiagnostic(diagnostics, { taskId, severity: "block", reason: `outputs overlap: ${current.raw} and ${other.raw}` });
      }
    }
  }
  for (const output of paths.outputs) {
    if (!paths.owned.some((owned) => declarationCovers(owned.normalized, output.normalized))) {
      addDiagnostic(diagnostics, { taskId, severity: "block", reason: `output is outside owned paths: ${output.raw}` });
    }
  }
  return paths;
}

function validateCrossTaskPaths(
  tasks: readonly TaskNode[],
  pathByTask: ReadonlyMap<string, TaskPaths>,
  diagnostics: PlanDiagnostic[],
): void {
  for (let leftIndex = 0; leftIndex < tasks.length; leftIndex += 1) {
    const leftTask = tasks[leftIndex];
    if (!leftTask) continue;
    const leftPaths = pathByTask.get(leftTask.id);
    if (!leftPaths) continue;
    for (const rightTask of tasks.slice(leftIndex + 1)) {
      const rightPaths = pathByTask.get(rightTask.id);
      if (!rightPaths) continue;
      let reported = false;
      for (const left of leftPaths.all) {
        for (const right of rightPaths.all) {
          if (!pathsOverlap(left.normalized, right.normalized)) continue;
          addDiagnostic(diagnostics, {
            taskId: leftTask.id,
            severity: "block",
            reason: `task path conflict with ${rightTask.id}: ${left.kind} ${left.raw} overlaps ${right.kind} ${right.raw}`,
          });
          reported = true;
          break;
        }
        if (reported) break;
      }
    }
  }
}

export function validatePlan(plan: Plan): PlanDiagnostic[] {
  const diagnostics: PlanDiagnostic[] = [];
  if (typeof plan !== "object" || plan === null) {
    return [{ severity: "block", reason: "plan must be an object" }];
  }
  const candidate = plan as Partial<Plan>;
  if (!candidate.budget || typeof candidate.budget !== "object") {
    addDiagnostic(diagnostics, { severity: "block", reason: "plan budget is required" });
  } else {
    if (!Number.isInteger(candidate.budget.maxWorkers) || candidate.budget.maxWorkers < 1 || candidate.budget.maxWorkers > 4) {
      addDiagnostic(diagnostics, { severity: "block", reason: "maxWorkers must be between 1 and 4" });
    }
    if (!Number.isInteger(candidate.budget.maxTurns) || candidate.budget.maxTurns < 1) {
      addDiagnostic(diagnostics, { severity: "block", reason: "maxTurns must be a positive integer" });
    }
  }
  if (!Array.isArray(candidate.tasks) || candidate.tasks.length === 0) {
    addDiagnostic(diagnostics, { severity: "block", reason: "plan must contain at least one task" });
    return diagnostics;
  }

  const tasks = candidate.tasks as TaskNode[];
  const ids = new Set<string>();
  const pathByTask = new Map<string, TaskPaths>();
  for (const task of tasks) {
    const taskId = typeof task?.id === "string" ? task.id : undefined;
    if (!taskId || taskId.trim().length === 0) {
      addDiagnostic(diagnostics, { severity: "block", reason: "task id must not be empty" });
    } else if (ids.has(taskId)) {
      addDiagnostic(diagnostics, { taskId, severity: "block", reason: "duplicate task id" });
    }
    if (taskId) ids.add(taskId);
    const paths = validateTaskDeclarations(task, diagnostics);
    if (taskId) pathByTask.set(taskId, paths);
    const deps = Array.isArray((task as Partial<TaskNode>).deps) ? task.deps : [];
    if (deps.some((dep) => dep === taskId)) {
      addDiagnostic(diagnostics, { taskId, severity: "block", reason: "task cannot depend on itself" });
    }
    if (new Set(deps).size !== deps.length) {
      addDiagnostic(diagnostics, { taskId, severity: "block", reason: "duplicate task dependency" });
    }
  }
  // Cross-task overlap is a scheduling concern, not a plan-invalidating
  // error. `nextReadyBatch` includes both owned paths and outputs in its
  // conflict check, so overlapping tasks are serialized while independent
  // tasks can still fan out.

  for (const task of tasks) {
    const taskId = typeof task?.id === "string" ? task.id : undefined;
    const deps = Array.isArray((task as Partial<TaskNode>).deps) ? task.deps : [];
    for (const dep of deps) {
      if (!ids.has(dep)) addDiagnostic(diagnostics, { taskId, severity: "block", reason: `unknown dependency: ${dep}` });
    }
  }
  // Kahn-style cycle check keeps planner output fail-closed.
  const remaining = new Map<string, Set<string>>();
  for (const task of tasks) {
    if (typeof task?.id === "string") remaining.set(task.id, new Set(Array.isArray(task.deps) ? task.deps.filter((dep) => ids.has(dep)) : []));
  }
  let removed = 0;
  while (true) {
    const ready = [...remaining.entries()].filter(([, deps]) => deps.size === 0).map(([id]) => id);
    if (ready.length === 0) break;
    for (const id of ready) {
      remaining.delete(id);
      removed++;
      for (const deps of remaining.values()) deps.delete(id);
    }
  }
  if (remaining.size > 0 || removed !== ids.size) addDiagnostic(diagnostics, { severity: "block", reason: "task dependency cycle" });
  return diagnostics;
}

function pathsForScheduling(task: TaskNode): string[] {
  return [
    ...(Array.isArray(task.ownedPaths) ? task.ownedPaths : []),
    ...(Array.isArray(task.outputs) ? task.outputs : []),
  ];
}

function sameTaskDeclaration(left: TaskNode, right: TaskNode): boolean {
  try {
    return JSON.stringify(left) === JSON.stringify(right);
  } catch {
    return false;
  }
}

export function nextReadyBatch(
  plan: Plan,
  completed: ReadonlySet<string>,
  running: readonly TaskNode[] = [],
): TaskNode[] {
  const diagnostics = validatePlan(plan);
  if (diagnostics.some((diagnostic) => diagnostic.severity === "block")) return [];
  const planIds = new Set(plan.tasks.map((task) => task.id));
  if ([...completed].some((id) => typeof id !== "string" || !planIds.has(id))) return [];
  if (running.some((task) => !planIds.has(task.id) || completed.has(task.id))) return [];
  if (new Set(running.map((task) => task.id)).size !== running.length) return [];
  const runningDiagnostics: PlanDiagnostic[] = [];
  for (const task of running) validateTaskDeclarations(task, runningDiagnostics);
  if (runningDiagnostics.some((diagnostic) => diagnostic.severity === "block")) return [];
  const planById = new Map(plan.tasks.map((task) => [task.id, task]));
  for (const task of running) {
    const planned = planById.get(task.id);
    if (!planned || !sameTaskDeclaration(planned, task)) return [];
    if (!Array.isArray(task.deps) || !task.deps.every((dep) => typeof dep === "string") || typeof task.parallelSafe !== "boolean") return [];
  }
  if (running.some((task) => !task.parallelSafe)) return [];

  const runningPaths = running.flatMap(pathsForScheduling);
  const available = plan.tasks
    .filter((task) => !completed.has(task.id) && !running.some((item) => item.id === task.id))
    .filter((task) => Array.isArray(task.deps) && task.deps.every((dep) => typeof dep === "string" && completed.has(dep)))
    .filter((task) => typeof task.parallelSafe === "boolean")
    .sort((a, b) => a.id.localeCompare(b.id));
  const batch: TaskNode[] = [];
  for (const task of available) {
    if (!task.parallelSafe && (batch.length > 0 || running.length > 0)) continue;
    const taskPaths = pathsForScheduling(task);
    if (taskPaths.some((path) => runningPaths.some((other) => pathsOverlap(path, other)))) continue;
    const batchPaths = batch.flatMap(pathsForScheduling);
    if (taskPaths.some((path) => batchPaths.some((other) => pathsOverlap(path, other)))) continue;
    if (batch.some((item) => !item.parallelSafe) || (batch.length > 0 && !task.parallelSafe)) continue;
    batch.push(task);
    if (batch.length >= plan.budget.maxWorkers) break;
  }
  return batch;
}
