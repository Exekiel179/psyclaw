import { lstat, readFile, readdir } from "node:fs/promises";
import { join } from "node:path";
import { Type, type Static } from "typebox";
import { Compile } from "typebox/compile";
import { checkEvidenceSufficiency } from "../core/evidence-policy.js";
import { redactSecrets } from "../core/redact.js";
import { readJsonl } from "../project/jsonl.js";
import { projectPaths } from "../project/paths.js";
import { assertSafeRunEventPath } from "./events.js";
import { loadLedger, readProject } from "../research/ledger.js";
import type { RunEvent } from "../orchestration/contracts.js";

export const RunSnapshotSchema = Type.Object({
  schemaVersion: Type.Literal("psyclaw/run-snapshot/v1"),
  runId: Type.String(),
  projectId: Type.String(),
  goal: Type.String(),
  paradigm: Type.String(),
  phase: Type.Union([
    Type.Literal("planned"),
    Type.Literal("executing"),
    Type.Literal("verifying"),
    Type.Literal("completed"),
    Type.Literal("paused"),
    Type.Literal("blocked"),
    Type.Literal("unknown"),
  ]),
  blocked: Type.Boolean(),
  waitingOnHuman: Type.Array(Type.String()),
  gates: Type.Array(Type.Object({
    gateId: Type.String(),
    ok: Type.Boolean(),
    severity: Type.String(),
    reason: Type.String(),
  })),
  artifacts: Type.Array(Type.String()),
  tasks: Type.Array(Type.Object({
    id: Type.String(),
    status: Type.Union([
      Type.Literal("pending"),
      Type.Literal("running"),
      Type.Literal("succeeded"),
      Type.Literal("failed"),
      Type.Literal("blocked"),
    ]),
    attempt: Type.Integer({ minimum: 0 }),
    summary: Type.String(),
    blockers: Type.Array(Type.String()),
    artifacts: Type.Array(Type.String()),
    receiptCount: Type.Integer({ minimum: 0 }),
    passedGates: Type.Array(Type.String()),
  }, { additionalProperties: false })),
  evidenceCoverage: Type.Object({
    totalClaims: Type.Integer(),
    supportedClaims: Type.Integer(),
    totalEvidence: Type.Integer(),
  }),
  eventCount: Type.Integer(),
  updatedAt: Type.String(),
  nextStep: Type.String(),
}, { additionalProperties: false });

export type RunSnapshot = Static<typeof RunSnapshotSchema>;

const compiled = Compile(RunSnapshotSchema);

export function asRunSnapshot(value: unknown): RunSnapshot {
  if (!compiled.Check(value)) {
    const errors = [...compiled.Errors(value)].map((error) => {
      const path = "path" in error && typeof error.path === "string" ? error.path : "/";
      return `${path}: ${error.message}`;
    });
    throw new Error(`run snapshot schema invalid: ${errors.join("; ")}`);
  }
  return value as RunSnapshot;
}

function isRunEvent(value: unknown): value is RunEvent {
  if (typeof value !== "object" || value === null) return false;
  const event = value as Partial<RunEvent>;
  return event.schemaVersion === "psyclaw/run-event/v1" &&
    typeof event.runId === "string" &&
    typeof event.at === "string" &&
    typeof event.type === "string";
}

function phaseFromEvents(events: readonly RunEvent[]): RunSnapshot["phase"] {
  const first = events[0];
  const last = events.at(-1);
  if (!last) return "planned";
  // A run must open with a `planned` event; a terminal or progress event
  // without that opener is a forged or corrupt log, reported as unknown rather
  // than trusted as a completed/blocked state.
  if (first?.type !== "planned") return "unknown";
  switch (last.type) {
    case "completed":
      return "completed";
    case "blocked":
      return "blocked";
    case "checkpoint":
      return "paused";
    case "gate":
      return "verifying";
    case "started":
    case "receipt":
      return "executing";
    default:
      return "planned";
  }
}

/** One concrete next action for the researcher, derived from the run state. */
function nextStepFor(phase: RunSnapshot["phase"], blocked: boolean, waitingReasons: readonly string[], corrupt: boolean): string {
  if (corrupt) return "运行事件或检查点不可用，先修复再继续";
  const waiting = waitingReasons.filter((item) => !item.includes("corrupt"));
  if (blocked || phase === "blocked") {
    return waiting.length > 0 ? `有 ${waiting.length} 项门禁需要你确认后再继续` : "门禁未通过，检查证据与 Claim";
  }
  if (waiting.length > 0) return `有 ${waiting.length} 项待你确认`;
  switch (phase) {
    case "paused": return "批准从 checkpoint 恢复运行";
    case "completed": return "检查产物，按 APA7 导出 DOCX（图片已内嵌）";
    case "executing": return "模型正在后台执行，无需操作";
    case "verifying": return "模型正在核验门禁";
    case "planned": return "导入证据并登记 Claim 后开始分析";
    default: return "等待运行状态";
  }
}

async function readEvents(root: string, runId: string): Promise<RunEvent[]> {
  const path = await assertSafeRunEventPath(root, runId);
  const stat = await lstat(path).catch((error: unknown) => {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return undefined;
    throw error;
  });
  if (stat !== undefined && (stat.isSymbolicLink() || !stat.isFile())) {
    throw new Error("Run event path must be a regular file");
  }
  const rows = await readJsonl<unknown>(path);
  return rows.map((row, index) => {
    if (!isRunEvent(row) || row.runId !== runId) {
      throw new Error(`Invalid run event at ${path}:${index + 1}`);
    }
    return row;
  });
}

interface TaskProjection {
  id: string;
  status: "pending" | "running" | "succeeded" | "failed" | "blocked";
  attempt: number;
  summary: string;
  blockers: string[];
  artifacts: string[];
  receiptCount: number;
  passedGates: string[];
}

type CheckpointProjection =
  | { kind: "missing"; artifacts: []; tasks: [] }
  | { kind: "corrupt"; artifacts: []; tasks: [] }
  | { kind: "valid"; status?: string; artifacts: string[]; tasks: TaskProjection[] };

async function readCheckpoint(root: string, runId: string): Promise<CheckpointProjection> {
  const path = join(projectPaths(root).runs, `${runId}.checkpoint.json`);
  try {
    const stat = await lstat(path);
    if (!stat.isFile() || stat.isSymbolicLink()) return { kind: "corrupt", artifacts: [], tasks: [] };
    const text = await readFile(path, "utf8");
    const value = JSON.parse(text) as {
      schemaVersion?: unknown;
      runId?: unknown;
      status?: unknown;
      tasks?: unknown;
    };
    if (value.schemaVersion !== "psyclaw/orchestrator-checkpoint/v1" || value.runId !== runId ||
        value.tasks === null || typeof value.tasks !== "object" || Array.isArray(value.tasks)) {
      return { kind: "corrupt", artifacts: [], tasks: [] };
    }
    const tasks = value.tasks as Record<string, unknown>;
    const artifacts: string[] = [];
    const taskProjections: TaskProjection[] = [];
    for (const [id, task] of Object.entries(tasks)) {
      if (task === null || typeof task !== "object" || Array.isArray(task)) return { kind: "corrupt", artifacts: [], tasks: [] };
      const item = task as { status?: unknown; attempt?: unknown; artifacts?: unknown; receipts?: unknown; passedGates?: unknown; report?: unknown };
      const taskArtifacts = item.artifacts;
      const validStatus = item.status === "pending" || item.status === "running" || item.status === "succeeded" || item.status === "failed" || item.status === "blocked";
      if (!validStatus || !Number.isInteger(item.attempt) || (item.attempt as number) < 0 ||
          !Array.isArray(taskArtifacts) || !taskArtifacts.every((entry) => typeof entry === "string") ||
          !Array.isArray(item.receipts) || !Array.isArray(item.passedGates) || !item.passedGates.every((entry) => typeof entry === "string")) {
        return { kind: "corrupt", artifacts: [], tasks: [] };
      }
      artifacts.push(...taskArtifacts);
      const report = item.report && typeof item.report === "object" && !Array.isArray(item.report)
        ? item.report as { summary?: unknown; blockers?: unknown }
        : undefined;
      if (report !== undefined && (typeof report.summary !== "string" || !Array.isArray(report.blockers) || !report.blockers.every((entry) => typeof entry === "string"))) {
        return { kind: "corrupt", artifacts: [], tasks: [] };
      }
      const taskArtifactPaths = taskArtifacts as string[];
      const taskPassedGates = item.passedGates as string[];
      taskProjections.push({
        id,
        status: item.status as TaskProjection["status"],
        attempt: item.attempt as number,
        summary: redactSecrets(typeof report?.summary === "string" ? report.summary : ""),
        blockers: (Array.isArray(report?.blockers) ? report.blockers as string[] : []).map((entry) => redactSecrets(entry)),
        artifacts: taskArtifactPaths,
        receiptCount: (item.receipts as unknown[]).length,
        passedGates: taskPassedGates,
      });
    }
    return {
      kind: "valid",
      ...(typeof value.status === "string" ? { status: value.status } : {}),
      artifacts,
      tasks: taskProjections.sort((left, right) => left.id.localeCompare(right.id)),
    };
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === "ENOENT"
      ? { kind: "missing", artifacts: [], tasks: [] }
      : { kind: "corrupt", artifacts: [], tasks: [] };
  }
}

export interface RunListing {
  runId: string;
  phase: RunSnapshot["phase"];
  eventCount: number;
}

/** List run ids discovered from the append-only run event log. */
export async function listRuns(root: string): Promise<RunListing[]> {
  const runsDir = projectPaths(root).runs;
  let entries: string[];
  try {
    entries = await readdir(runsDir);
  } catch {
    return [];
  }
  const listings: RunListing[] = [];
  for (const entry of entries) {
    if (!entry.endsWith(".jsonl") || entry.endsWith(".checkpoint.json")) continue;
    const runId = entry.slice(0, -".jsonl".length);
    try {
      const events = await readEvents(root, runId);
      listings.push({ runId, phase: phaseFromEvents(events), eventCount: events.length });
    } catch {
      continue;
    }
  }
  return listings.sort((left, right) => left.runId.localeCompare(right.runId));
}

/**
 * Read-only projection of a run's facts. It derives a redacted snapshot from
 * the JSONL event log, checkpoint, project, and evidence ledger. The panel
 * consumes this and never mutates state or reaches the filesystem/MCP itself.
 */
export async function projectRunSnapshot(root: string, runId: string): Promise<RunSnapshot> {
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(runId)) {
    throw new Error("Run id contains unsupported path characters");
  }
  const project = await readProject(root);
  const ledger = await loadLedger(root);
  const gates = checkEvidenceSufficiency({ ...ledger, paradigm: project.paradigm });
  const checkpoint = await readCheckpoint(root, runId);

  let events: RunEvent[] = [];
  let eventCorrupt = false;
  try {
    events = await readEvents(root, runId);
  } catch {
    eventCorrupt = true;
  }

  const gateBlocked = gates.filter((gate) => !gate.ok);
  const checkpointCorrupt = checkpoint.kind === "corrupt";
  const phase: RunSnapshot["phase"] = eventCorrupt || checkpointCorrupt
    ? "unknown"
    : checkpoint.kind === "valid" && checkpoint.status === "paused"
      ? "paused"
      : phaseFromEvents(events);

  const snapshot: RunSnapshot = {
    schemaVersion: "psyclaw/run-snapshot/v1",
    runId,
    projectId: project.id,
    goal: redactSecrets(project.goal),
    paradigm: project.paradigm,
    phase,
    blocked: gateBlocked.length > 0 || phase === "blocked",
    waitingOnHuman: [
      ...(eventCorrupt ? ["run event log is corrupt or unavailable"] : []),
      ...(checkpointCorrupt ? ["run checkpoint is corrupt or unavailable"] : []),
      ...gateBlocked.map((gate) => redactSecrets(gate.reason)),
    ],
    gates: gates.map((gate) => ({
      gateId: gate.gateId,
      ok: gate.ok,
      severity: gate.severity,
      reason: redactSecrets(gate.reason),
    })),
    artifacts: checkpoint.kind === "valid" ? checkpoint.artifacts : [],
    tasks: checkpoint.kind === "valid" ? checkpoint.tasks : [],
    evidenceCoverage: {
      totalClaims: ledger.claims.length,
      supportedClaims: ledger.claims.filter((claim) => claim.status === "supported").length,
      totalEvidence: ledger.evidence.length,
    },
    eventCount: events.length,
    updatedAt: new Date().toISOString(),
    nextStep: nextStepFor(phase, gateBlocked.length > 0, gateBlocked.map((gate) => redactSecrets(gate.reason)), checkpointCorrupt || eventCorrupt),
  };
  asRunSnapshot(snapshot);
  return snapshot;
}
