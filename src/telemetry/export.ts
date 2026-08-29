import { createHash, randomBytes } from "node:crypto";
import { lstat, mkdir, readFile, readdir } from "node:fs/promises";
import { dirname, relative, resolve } from "node:path";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import { PSYCLAW_VERSION } from "../branding.js";
import { atomicWriteFile } from "../project/jsonl.js";
import { projectPaths } from "../project/paths.js";
import { resolvePsyClawManifest } from "../updates/manifest.js";

type JsonRecord = Record<string, unknown>;

interface OtlpAttribute {
  key: string;
  value: { stringValue?: string; intValue?: string; boolValue?: boolean };
}

interface OtlpSpan {
  traceId: string;
  spanId: string;
  parentSpanId?: string;
  name: string;
  kind: number;
  startTimeUnixNano: string;
  endTimeUnixNano: string;
  attributes: OtlpAttribute[];
  status: { code: number };
}

export interface TraceExportOptions {
  root?: string;
  agentDir?: string;
  output?: string;
  now?: () => Date;
}

export interface TraceExportResult {
  schemaVersion: "psyclaw/trace-export-receipt/v1";
  format: "otlp-json";
  output: string;
  traces: number;
  spans: number;
  sources: { sessions: number; workflowRuns: number };
  privacy: {
    contentIncluded: false;
    originalIdsIncluded: false;
    absolutePathsIncluded: false;
  };
}

export interface PanelTraceEvent {
  id: string;
  name: string;
  at: string;
  status: "ok" | "error";
  category?: string;
}

export interface PanelTrace {
  id: string;
  source: "session" | "workflow";
  label: string;
  startedAt: string;
  endedAt: string;
  status: "ok" | "error";
  events: PanelTraceEvent[];
}

export interface PanelTraceSnapshot {
  schemaVersion: "psyclaw/panel-traces/v1";
  generatedAt: string;
  traces: PanelTrace[];
  sources: { sessions: number; workflowRuns: number };
  privacy: {
    contentIncluded: false;
    originalIdsIncluded: false;
    absolutePathsIncluded: false;
  };
}

const attr = (key: string, value: string | number | boolean): OtlpAttribute => ({
  key,
  value: typeof value === "boolean"
    ? { boolValue: value }
    : typeof value === "number"
      ? { intValue: String(Math.trunc(value)) }
      : { stringValue: value },
});

function id(bytes: number): string {
  return randomBytes(bytes).toString("hex");
}

function stableId(value: string): string {
  return createHash("sha256").update(value).digest("hex").slice(0, 16);
}

function timestamp(value: unknown, fallback: Date): Date {
  if (typeof value !== "string") return fallback;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? fallback : parsed;
}

function nanos(value: Date): string {
  return (BigInt(value.getTime()) * 1_000_000n).toString();
}

function endAfter(start: Date, candidate?: Date): Date {
  if (candidate && candidate.getTime() > start.getTime()) return candidate;
  return new Date(start.getTime() + 1);
}

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

async function readJsonl(path: string): Promise<JsonRecord[]> {
  const text = await readFile(path, "utf8");
  const rows: JsonRecord[] = [];
  for (const line of text.split(/\r?\n/)) {
    if (!line.trim()) continue;
    try {
      const parsed = JSON.parse(line) as unknown;
      if (isRecord(parsed)) rows.push(parsed);
    } catch {
      // A malformed historical line is omitted instead of leaking its text in
      // an error message or preventing export of the remaining safe metadata.
    }
  }
  return rows;
}

async function regularJsonlFiles(root: string): Promise<string[]> {
  const files: string[] = [];
  async function walk(directory: string): Promise<void> {
    let entries;
    try {
      entries = await readdir(directory, { withFileTypes: true });
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return;
      throw error;
    }
    for (const entry of entries) {
      const path = resolve(directory, entry.name);
      if (entry.isSymbolicLink()) continue;
      if (entry.isDirectory()) await walk(path);
      else if (entry.isFile() && entry.name.endsWith(".jsonl")) files.push(path);
    }
  }
  await walk(root);
  return files.sort();
}

function safeToolCategory(name: unknown): string {
  if (typeof name !== "string") return "other";
  if (name === "psyclaw_workbench") return "research_workbench";
  if (name === "psyclaw_skill") return "research_skill";
  if (["read", "grep", "find", "ls"].includes(name)) return "file_read";
  if (["edit", "write"].includes(name)) return "file_write";
  if (["bash", "powershell"].includes(name)) return "shell";
  return "other";
}

function toolCategories(message: JsonRecord): string[] {
  const content = message.content;
  if (!Array.isArray(content)) return [];
  const categories: string[] = [];
  for (const part of content) {
    if (!isRecord(part)) continue;
    const type = part.type;
    if (type !== "toolCall" && type !== "tool_call" && type !== "tool_use") continue;
    categories.push(safeToolCategory(part.name ?? part.toolName));
  }
  return categories;
}

function makeSpan(options: {
  traceId: string;
  parentSpanId?: string;
  name: string;
  start: Date;
  end?: Date;
  attributes?: OtlpAttribute[];
  status?: "ok" | "error";
}): OtlpSpan {
  return {
    traceId: options.traceId,
    spanId: id(8),
    ...(options.parentSpanId === undefined ? {} : { parentSpanId: options.parentSpanId }),
    name: options.name,
    kind: 1,
    startTimeUnixNano: nanos(options.start),
    endTimeUnixNano: nanos(endAfter(options.start, options.end)),
    attributes: options.attributes ?? [],
    status: { code: options.status === "error" ? 2 : 1 },
  };
}

function sessionSpans(rows: JsonRecord[], root: string, fallback: Date): OtlpSpan[] {
  const header = rows.find((row) => row.type === "session");
  if (!header || typeof header.cwd !== "string" || resolve(header.cwd) !== root) return [];
  const dated = rows.map((row) => ({ row, at: timestamp(row.timestamp, fallback) }));
  const start = dated[0]?.at ?? fallback;
  const end = dated.at(-1)?.at ?? start;
  const traceId = id(16);
  const rootSpan = makeSpan({
    traceId,
    name: "psyclaw.session",
    start,
    end,
    attributes: [attr("psyclaw.source", "pi-session"), attr("psyclaw.version", PSYCLAW_VERSION)],
  });
  const spans = [rootSpan];
  for (const { row, at } of dated) {
    if (row.type !== "message" || !isRecord(row.message)) continue;
    const role = row.message.role;
    if (role === "user" || role === "assistant") {
      spans.push(makeSpan({
        traceId,
        parentSpanId: rootSpan.spanId,
        name: role === "user" ? "conversation.user_turn" : "conversation.assistant_turn",
        start: at,
        attributes: [attr("psyclaw.content_included", false)],
        status: role === "assistant" && typeof row.message.errorMessage === "string" ? "error" : "ok",
      }));
    }
    if (role === "assistant") {
      for (const category of toolCategories(row.message)) {
        spans.push(makeSpan({
          traceId,
          parentSpanId: rootSpan.spanId,
          name: `tool.${category}`,
          start: at,
          attributes: [attr("langsmith.span.kind", "tool"), attr("psyclaw.tool.category", category)],
        }));
      }
    }
  }
  return spans;
}

function workflowSpans(rows: JsonRecord[], fallback: Date): OtlpSpan[] {
  const events = rows.filter((row) => row.schemaVersion === "psyclaw/run-event/v1" && typeof row.type === "string");
  if (events.length === 0) return [];
  const dated = events.map((row) => ({ row, at: timestamp(row.at, fallback) }));
  const start = dated[0]?.at ?? fallback;
  const end = dated.at(-1)?.at ?? start;
  const traceId = id(16);
  const blocked = events.some((row) => row.type === "blocked");
  const rootSpan = makeSpan({
    traceId,
    name: "psyclaw.workflow",
    start,
    end,
    status: blocked ? "error" : "ok",
    attributes: [attr("psyclaw.source", "workflow-run"), attr("psyclaw.version", PSYCLAW_VERSION)],
  });
  const spans = [rootSpan];
  for (const { row, at } of dated) {
    const eventType = String(row.type);
    spans.push(makeSpan({
      traceId,
      parentSpanId: rootSpan.spanId,
      name: `workflow.${eventType}`,
      start: at,
      status: eventType === "blocked" ? "error" : "ok",
      attributes: [attr("psyclaw.event.type", eventType)],
    }));
  }
  return spans;
}

function sessionTrace(rows: JsonRecord[], root: string, sourceKey: string): PanelTrace | undefined {
  const header = rows.find((row) => row.type === "session");
  if (!header || typeof header.cwd !== "string" || resolve(header.cwd) !== root) return undefined;
  const events: PanelTraceEvent[] = [];
  for (const [index, row] of rows.entries()) {
    if (row.type !== "message" || !isRecord(row.message)) continue;
    const role = row.message.role;
    const at = timestamp(row.timestamp ?? row.message.timestamp, new Date(0)).toISOString();
    if (role === "user" || role === "assistant") {
      events.push({
        id: stableId(`${sourceKey}:${index}:turn`),
        name: role === "user" ? "用户回合" : "助手回合",
        at,
        status: role === "assistant" && typeof row.message.errorMessage === "string" ? "error" : "ok",
      });
    }
    if (role === "assistant") {
      for (const [toolIndex, category] of toolCategories(row.message).entries()) {
        events.push({
          id: stableId(`${sourceKey}:${index}:tool:${toolIndex}`),
          name: "工具调用",
          at,
          status: "ok",
          category,
        });
      }
    }
  }
  if (events.length === 0) return undefined;
  const traceId = stableId(`session:${sourceKey}`);
  return {
    id: traceId,
    source: "session",
    label: `会话 ${traceId.slice(0, 6)}`,
    startedAt: events[0]!.at,
    endedAt: events.at(-1)!.at,
    status: events.some((event) => event.status === "error") ? "error" : "ok",
    events,
  };
}

function workflowTrace(rows: JsonRecord[], sourceKey: string): PanelTrace | undefined {
  const sourceEvents = rows.filter((row) => row.schemaVersion === "psyclaw/run-event/v1" && typeof row.type === "string");
  if (sourceEvents.length === 0) return undefined;
  const events = sourceEvents.map((row, index): PanelTraceEvent => {
    const eventType = String(row.type);
    return {
      id: stableId(`${sourceKey}:${index}:${eventType}`),
      name: `工作流 ${eventType}`,
      at: timestamp(row.at, new Date(0)).toISOString(),
      status: eventType === "blocked" ? "error" : "ok",
    };
  });
  const traceId = stableId(`workflow:${sourceKey}`);
  return {
    id: traceId,
    source: "workflow",
    label: `工作流 ${traceId.slice(0, 6)}`,
    startedAt: events[0]!.at,
    endedAt: events.at(-1)!.at,
    status: events.some((event) => event.status === "error") ? "error" : "ok",
    events,
  };
}

/** Build a stable, metadata-only trace view for the local Panel without writing an export file. */
export async function projectTraceSnapshot(options: Pick<TraceExportOptions, "root" | "agentDir"> = {}): Promise<PanelTraceSnapshot> {
  const root = resolve(options.root ?? process.cwd());
  const sessionsRoot = resolve(options.agentDir ?? getAgentDir(), "sessions");
  const runRoot = projectPaths(root).runs;
  const [sessionFiles, runFiles] = await Promise.all([regularJsonlFiles(sessionsRoot), regularJsonlFiles(runRoot)]);
  const traces: PanelTrace[] = [];
  for (const file of sessionFiles) {
    const sourceKey = stableId(relative(sessionsRoot, file).replaceAll("\\", "/"));
    const trace = sessionTrace(await readJsonl(file), root, sourceKey);
    if (trace) traces.push(trace);
  }
  for (const file of runFiles) {
    const sourceKey = stableId(relative(runRoot, file).replaceAll("\\", "/"));
    const trace = workflowTrace(await readJsonl(file), sourceKey);
    if (trace) traces.push(trace);
  }
  traces.sort((left, right) => right.startedAt.localeCompare(left.startedAt));
  return {
    schemaVersion: "psyclaw/panel-traces/v1",
    generatedAt: new Date().toISOString(),
    traces,
    sources: {
      sessions: traces.filter((trace) => trace.source === "session").length,
      workflowRuns: traces.filter((trace) => trace.source === "workflow").length,
    },
    privacy: { contentIncluded: false, originalIdsIncluded: false, absolutePathsIncluded: false },
  };
}

function safeOutput(root: string, requested: string): string {
  const output = resolve(root, requested);
  const rel = relative(root, output).replaceAll("\\", "/");
  if (rel === "" || rel === ".." || rel.startsWith("../")) {
    throw new Error("Trace export output must stay inside the current project");
  }
  return output;
}

/** Export metadata-only interaction paths as an OTLP/HTTP JSON payload. */
export async function exportTraces(options: TraceExportOptions = {}): Promise<TraceExportResult> {
  const root = resolve(options.root ?? process.cwd());
  const output = safeOutput(root, options.output ?? "psyclaw-traces.otlp.json");
  const fallback = options.now?.() ?? new Date();
  const sessionsRoot = resolve(options.agentDir ?? getAgentDir(), "sessions");
  const runRoot = projectPaths(root).runs;
  const [sessionFiles, runFiles] = await Promise.all([
    regularJsonlFiles(sessionsRoot),
    regularJsonlFiles(runRoot),
  ]);

  const traces: OtlpSpan[][] = [];
  let includedSessions = 0;
  for (const file of sessionFiles) {
    const spans = sessionSpans(await readJsonl(file), root, fallback);
    if (spans.length > 0) {
      traces.push(spans);
      includedSessions += 1;
    }
  }
  let includedRuns = 0;
  for (const file of runFiles) {
    const spans = workflowSpans(await readJsonl(file), fallback);
    if (spans.length > 0) {
      traces.push(spans);
      includedRuns += 1;
    }
  }

  const manifest = await resolvePsyClawManifest();
  const allSpans = traces.flat();
  const payload = {
    resourceSpans: [{
      resource: {
        attributes: [
          attr("service.name", "psyclaw"),
          attr("service.version", PSYCLAW_VERSION),
          ...(manifest?.piVersion ? [attr("psyclaw.pi.version", manifest.piVersion)] : []),
          attr("psyclaw.export.content_included", false),
        ],
      },
      scopeSpans: [{
        scope: { name: "psyclaw.trace-export", version: PSYCLAW_VERSION },
        spans: allSpans,
      }],
    }],
  };
  await mkdir(dirname(output), { recursive: true });
  await atomicWriteFile(output, `${JSON.stringify(payload, null, 2)}\n`);
  return {
    schemaVersion: "psyclaw/trace-export-receipt/v1",
    format: "otlp-json",
    output,
    traces: traces.length,
    spans: allSpans.length,
    sources: { sessions: includedSessions, workflowRuns: includedRuns },
    privacy: { contentIncluded: false, originalIdsIncluded: false, absolutePathsIncluded: false },
  };
}
