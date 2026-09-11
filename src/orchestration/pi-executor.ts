import type { Effect } from "../core/contracts.js";
import type { WorkerReport, TaskNode } from "./contracts.js";
import {
  BoundedOrchestrator,
  type OrchestrationResult,
  type WorkerExecutionResult,
  type WorkerExecutor,
  type WorkerContext,
  type RunnerEvent,
} from "./runner.js";
import { PiRpcClient, type PiRpcMessage } from "../adapters/pi/rpc.js";
import { formatEffects, hasElevatedEffects, normalizeEffects, toolsForEffects } from "./effects.js";
import { lastPiGeneration, trackLlmGeneration, withAgentSpan } from "../observability/index.js";

export interface PiExecutorOptions {
  cwd: string;
  cliPath?: string;
  command?: string;
  provider?: string;
  model?: string;
  agentDir?: string;
  env?: Record<string, string>;
  timeoutMs?: number;
  tools?: readonly string[];
  /** Host ceilings after interactive approval. */
  allowWrites?: boolean;
  allowNetwork?: boolean;
  allowDestructive?: boolean;
  onEvent?: (event: RunnerEvent) => void | Promise<void>;
  pauseRequested?: () => boolean | Promise<boolean>;
}

function blockedReport(task: TaskNode, context: WorkerContext, summary: string): WorkerReport {
  return {
    schemaVersion: "psyclaw/worker-report/v1",
    taskId: task.id,
    dispatchId: context.dispatchId,
    outcome: "blocked",
    summary,
    filesModified: [],
    verification: [],
    blockers: [summary],
  };
}

function textFromMessage(message: unknown): string | undefined {
  if (!message || typeof message !== "object") return undefined;
  const content = (message as { content?: unknown }).content;
  if (!Array.isArray(content)) return undefined;
  const text = content
    .filter((part): part is { type: "text"; text: string } =>
      Boolean(part && typeof part === "object" && (part as { type?: unknown }).type === "text" && typeof (part as { text?: unknown }).text === "string"),
    )
    .map((part) => part.text)
    .join("");
  return text || undefined;
}

function extractJson(text: string): unknown {
  const trimmed = text.trim();
  const fenced = trimmed.match(/```(?:json)?\s*([\s\S]*?)\s*```/i)?.[1];
  const candidate = (fenced ?? trimmed).trim();
  try {
    return JSON.parse(candidate);
  } catch {
    const start = candidate.indexOf("{");
    const end = candidate.lastIndexOf("}");
    if (start < 0 || end <= start) return undefined;
    try {
      return JSON.parse(candidate.slice(start, end + 1));
    } catch {
      return undefined;
    }
  }
}

function parseWorkerReport(value: unknown, task: TaskNode, context: WorkerContext, allowFilesModified: boolean): WorkerReport | undefined {
  if (!value || typeof value !== "object") return undefined;
  const record = value as Record<string, unknown>;
  if (record.schemaVersion !== "psyclaw/worker-report/v1") return undefined;
  if (record.taskId !== task.id || record.dispatchId !== context.dispatchId) return undefined;
  if (record.outcome !== "succeeded" && record.outcome !== "blocked" && record.outcome !== "failed") return undefined;
  if (typeof record.summary !== "string" || record.summary.trim() === "") return undefined;
  if (!Array.isArray(record.filesModified) || !record.filesModified.every((item) => typeof item === "string")) return undefined;
  if (!Array.isArray(record.blockers) || !record.blockers.every((item) => typeof item === "string")) return undefined;
  if (!Array.isArray(record.verification)) return undefined;
  if (!allowFilesModified && record.filesModified.length > 0) return undefined;
  return {
    schemaVersion: "psyclaw/worker-report/v1",
    taskId: task.id,
    dispatchId: context.dispatchId,
    outcome: record.outcome,
    summary: record.summary,
    filesModified: record.filesModified as string[],
    verification: record.verification.filter((item): item is { command: string; exitCode: number; outputDigest?: string } => {
      if (!item || typeof item !== "object") return false;
      const candidate = item as Record<string, unknown>;
      return typeof candidate.command === "string" && candidate.command.trim() !== ""
        && Number.isInteger(candidate.exitCode) && (candidate.outputDigest === undefined || typeof candidate.outputDigest === "string");
    }),
    blockers: record.blockers as string[],
  };
}

function lastAssistantText(events: readonly PiRpcMessage[]): string | undefined {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (event?.type !== "message_end") continue;
    const text = textFromMessage(event.message);
    if (text) return text;
  }
  return undefined;
}

function taskPrompt(task: TaskNode, context: WorkerContext, effects: readonly Effect[]): string {
  const elevated = hasElevatedEffects(effects);
  return [
    elevated
      ? `You are a psyclaw research worker with explicitly approved effects: ${formatEffects(effects)}.`
      : "You are a read-only psyclaw research worker.",
    elevated
      ? "Stay within the approved effects. Do not read credentials or bypass project gates."
      : "Do not write, edit, delete, execute shell commands, access network services, or modify credentials.",
    elevated
      ? "Use only the tools enabled for this run."
      : "Inspect only the supplied task inputs and project files with read/grep/find/ls.",
    "At the end return ONLY one JSON object matching this schema:",
    '{"schemaVersion":"psyclaw/worker-report/v1","taskId":"...","dispatchId":"...","outcome":"succeeded|blocked|failed","summary":"...","filesModified":[],"verification":[{"command":"...","exitCode":0}],"blockers":[]}',
    `taskId=${task.id}`,
    `dispatchId=${context.dispatchId}`,
    `objective=${task.objective}`,
    `inputs=${JSON.stringify(task.inputs)}`,
    `allowedEffects=${JSON.stringify(effects)}`,
  ].join("\n");
}

function hostAllowsTaskEffects(
  effects: readonly Effect[],
  options: Pick<PiExecutorOptions, "allowWrites" | "allowNetwork" | "allowDestructive">,
): boolean {
  for (const effect of effects) {
    if (effect === "read") continue;
    if (effect === "write" && options.allowWrites !== true) return false;
    if (effect === "network" && options.allowNetwork !== true) return false;
    if (effect === "destructive" && options.allowDestructive !== true) return false;
  }
  return true;
}

/**
 * Execute one task in a separate Pi process. Mutating tools are available only
 * when the host options explicitly approve matching effects after user confirm.
 */
export function createPiWorkerExecutor(options: PiExecutorOptions): WorkerExecutor {
  return async (task: TaskNode, context: WorkerContext): Promise<WorkerExecutionResult> => {
    const effects = normalizeEffects(task.allowedEffects);
    if (!hostAllowsTaskEffects(effects, options)) {
      return {
        report: blockedReport(
          task,
          context,
          `Task effects [${formatEffects(effects)}] exceed approved host ceilings`,
        ),
      };
    }
    const elevated = hasElevatedEffects(effects);
    const tools = options.tools ?? toolsForEffects(effects);
    const client = new PiRpcClient({
      cwd: options.cwd,
      ...(options.cliPath === undefined ? {} : { cliPath: options.cliPath }),
      ...(options.command === undefined ? {} : { command: options.command }),
      ...(options.provider === undefined ? {} : { provider: options.provider }),
      ...(options.model === undefined ? {} : { model: options.model }),
      ...(options.agentDir === undefined ? {} : { agentDir: options.agentDir }),
      ...(options.env === undefined ? {} : { env: options.env }),
      ...(options.timeoutMs === undefined ? {} : { timeoutMs: options.timeoutMs }),
      tools,
      ...(elevated ? { allowElevatedTools: true } : {}),
    });
    try {
      await client.start();
      const events = await withAgentSpan(
        "cli.llm_call",
        { phase: "pi_rpc", provider: options.provider ?? "unknown" },
        () => client.promptAndWait(taskPrompt(task, context, effects), options.timeoutMs),
      );
      const generation = lastPiGeneration(events);
      if (generation) {
        void trackLlmGeneration({
          ...generation,
          surface: "cli",
          spanName: generation.spanName ?? "pi-rpc",
        });
      }
      const report = parseWorkerReport(extractJson(lastAssistantText(events) ?? ""), task, context, effects.includes("write"));
      if (!report) return { report: blockedReport(task, context, "Worker did not return a valid structured report") };
      return { report };
    } catch {
      return { report: blockedReport(task, context, "Pi worker process failed or timed out") };
    } finally {
      await client.stop();
    }
  };
}

/** @deprecated Prefer createPiWorkerExecutor; kept as the read-only default alias. */
export function createPiReadOnlyExecutor(options: PiExecutorOptions): WorkerExecutor {
  return createPiWorkerExecutor({ ...options, allowWrites: false, allowNetwork: false, allowDestructive: false });
}

export async function runPlanWithPi(
  plan: Parameters<BoundedOrchestrator["run"]>[0],
  options: PiExecutorOptions & { root?: string; maxWorkers?: number } = { cwd: process.cwd() },
): Promise<OrchestrationResult> {
  const executor = createPiWorkerExecutor(options);
  return new BoundedOrchestrator({
    executor,
    root: options.root ?? options.cwd,
    ...(options.maxWorkers === undefined ? {} : { maxWorkers: options.maxWorkers }),
    allowWrites: options.allowWrites === true,
    allowNetwork: options.allowNetwork === true,
    allowDestructive: options.allowDestructive === true,
    ...(options.pauseRequested === undefined ? {} : { pauseRequested: options.pauseRequested }),
    ...(options.onEvent === undefined ? {} : { onEvent: options.onEvent }),
  }).run(plan);
}

export async function resumePlanWithPi(
  plan: Parameters<BoundedOrchestrator["resume"]>[0],
  options: PiExecutorOptions & { root?: string; maxWorkers?: number } = { cwd: process.cwd() },
): Promise<OrchestrationResult> {
  const executor = createPiWorkerExecutor(options);
  return new BoundedOrchestrator({
    executor,
    root: options.root ?? options.cwd,
    ...(options.maxWorkers === undefined ? {} : { maxWorkers: options.maxWorkers }),
    allowWrites: options.allowWrites === true,
    allowNetwork: options.allowNetwork === true,
    allowDestructive: options.allowDestructive === true,
    ...(options.pauseRequested === undefined ? {} : { pauseRequested: options.pauseRequested }),
    ...(options.onEvent === undefined ? {} : { onEvent: options.onEvent }),
  }).resume(plan);
}
