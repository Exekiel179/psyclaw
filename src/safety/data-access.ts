/**
 * Display levels for project files. script-only files stay on disk for
 * analysis scripts, but their contents are not returned to the model.
 * The researcher sets levels with /data-access. The model cannot.
 */
import { relative, resolve } from "node:path";
import { readFile } from "node:fs/promises";
import { atomicWriteFile } from "../project/jsonl.js";
import { extractToolCommandText } from "./irreversible-host-ops.js";

export const DATA_ACCESS_VERSION = "psyclaw/data-access/v1" as const;
export const DATA_ACCESS_CONFIG = ".psyclaw/data-access.json";
/** Full tool stdout saved for a later bounded recall. Not a researcher data directory. */
export const TOOL_OUTPUT_LOG_DIR = ".psyclaw/cache/tool-output";
export type DataAccessLevel = "full" | "script-only";

export interface DataAccessEntry {
  path: string;
  access: DataAccessLevel;
}

export interface DataAccessRules {
  entries: DataAccessEntry[];
  warning?: string;
}

const DEFAULT_ENTRIES: readonly DataAccessEntry[] = [
  { path: "data/secret", access: "script-only" },
];

const CONTENT_TOOLS = new Set(["read", "edit", "write", "grep", "psyclaw_read_results"]);
const DISPLAY_BIN = String.raw`(?:base64|xxd|cat|head|tail|less|more|bat|nl|od|hexdump|strings|sed|awk|grep|rg|egrep|fgrep|cp|mv|rsync|tee)`;
const DIRECT_DISPLAY = new RegExp(`(?:^|[;&|\n]|&&|\\|\\||\\$\\(|\`)\\s*(?:sudo\\s+)?${DISPLAY_BIN}\\b`);

function configPath(root: string): string {
  return resolve(root, DATA_ACCESS_CONFIG);
}

function normalizePath(input: string): string | undefined {
  const normalized = input.trim().replaceAll("\\", "/").replace(/^\.\//, "");
  if (!normalized || normalized.startsWith("/") || /^[A-Za-z]:/.test(input) || normalized.split("/").includes("..")) return undefined;
  return normalized;
}

/** Map a tool path onto a project-relative path. Absolute paths and `..` must stay inside root. */
export function toProjectRelative(input: string, cwd?: string): string | undefined {
  const raw = input.trim();
  if (!raw) return undefined;
  const slash = raw.replaceAll("\\", "/");
  const absolute = slash.startsWith("/") || /^[A-Za-z]:/.test(raw);
  if (!absolute && !slash.split("/").includes("..")) return normalizePath(slash);
  if (!cwd) return undefined;
  const root = resolve(cwd);
  const target = absolute ? resolve(slash) : resolve(root, slash);
  const rel = relative(root, target).replaceAll("\\", "/");
  if (!rel || rel === "." || rel.startsWith("../") || rel === "..") return undefined;
  return rel;
}

function isLevel(value: unknown): value is DataAccessLevel {
  return value === "full" || value === "script-only";
}

export function mergeDataAccess(extra: readonly DataAccessEntry[]): DataAccessEntry[] {
  const merged = new Map(DEFAULT_ENTRIES.map((entry) => [entry.path, { ...entry }]));
  for (const entry of extra) merged.set(entry.path, { ...entry });
  return [...merged.values()];
}

export function accessFor(relativePath: string, entries: readonly DataAccessEntry[]): DataAccessLevel {
  const normalized = normalizePath(relativePath);
  if (!normalized) return "full";
  let best: DataAccessEntry | undefined;
  for (const entry of entries) {
    if (normalized === entry.path || normalized.startsWith(`${entry.path}/`)) {
      if (!best || entry.path.length > best.path.length) best = entry;
    }
  }
  return best?.access ?? "full";
}

export async function loadDataAccess(root: string): Promise<DataAccessRules> {
  try {
    const parsed = JSON.parse(await readFile(configPath(root), "utf8")) as { schemaVersion?: string; entries?: unknown };
    if (parsed.schemaVersion !== DATA_ACCESS_VERSION || !Array.isArray(parsed.entries)) {
      return { entries: mergeDataAccess([]), warning: `${DATA_ACCESS_CONFIG} 无法识别，仍使用 data/secret 的默认 script-only。` };
    }
    const extra: DataAccessEntry[] = [];
    for (const entry of parsed.entries) {
      if (!entry || typeof entry !== "object") continue;
      const record = entry as { path?: unknown; access?: unknown };
      const path = typeof record.path === "string" ? normalizePath(record.path) : undefined;
      if (!path || !isLevel(record.access)) continue;
      extra.push({ path, access: record.access });
    }
    return { entries: mergeDataAccess(extra) };
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return { entries: mergeDataAccess([]) };
    return { entries: mergeDataAccess([]), warning: `${DATA_ACCESS_CONFIG} 无法读取，仍使用 data/secret 的默认 script-only。` };
  }
}

export async function setDataAccess(root: string, target: string, access: DataAccessLevel): Promise<DataAccessEntry[]> {
  const path = normalizePath(target);
  if (!path || path === DATA_ACCESS_CONFIG) throw new Error(`路径必须是项目内的数据文件：${target}`);
  const current = await loadDataAccess(root);
  if (current.warning) throw new Error(current.warning);
  const fileEntries = current.entries.filter((entry) => !DEFAULT_ENTRIES.some((item) => item.path === entry.path && item.access === entry.access));
  const next = new Map(fileEntries.map((entry) => [entry.path, entry]));
  const unchangedDefault = DEFAULT_ENTRIES.some((entry) => entry.path === path && entry.access === access);
  if (unchangedDefault) next.delete(path);
  else next.set(path, { path, access });
  const entries = [...next.values()];
  await atomicWriteFile(configPath(root), `${JSON.stringify({ schemaVersion: DATA_ACCESS_VERSION, entries }, null, 2)}\n`);
  return mergeDataAccess(entries);
}

export function formatDataAccess(entries: readonly DataAccessEntry[]): string {
  return [
    "文件展示级别（script-only 不能直接读入模型，分析脚本仍可在磁盘上打开）：",
    ...entries.map((entry) => `${entry.path}  ${entry.access}`),
    "设置：/data-access set <项目内相对路径> <full|script-only>",
  ].join("\n");
}

function inputPath(input: unknown): string | undefined {
  if (!input || typeof input !== "object" || Array.isArray(input)) return undefined;
  const record = input as Record<string, unknown>;
  for (const key of ["path", "file_path", "filePath"]) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return undefined;
}

function mentions(text: string, prefix: string): boolean {
  const escaped = prefix.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(?:^|[\\s'"\`=:/])\\.?\\/?${escaped}(?=$|[\\s'"\`/;|&<>:])`).test(text.replaceAll("\\", "/"));
}

function isDirectDisplay(command: string): boolean {
  return DIRECT_DISPLAY.test(command)
    || /\bpython3?\b[\s\S]*(\s-c\b|<<)/.test(command)
    || /\bRscript\b[\s\S]*\s-e\b/.test(command)
    || /\bperl\b[\s\S]*\s-e\b/.test(command);
}

export function scriptOnlyBlock(toolName: string, input: unknown, entries: readonly DataAccessEntry[], cwd?: string): string | undefined {
  const name = toolName.toLowerCase();
  const target = inputPath(input);
  const relativePath = target ? toProjectRelative(target, cwd) : undefined;
  if ((name === "write" || name === "edit") && relativePath === DATA_ACCESS_CONFIG) {
    return `展示级别只能由研究者用 /data-access 修改，模型不能改 ${DATA_ACCESS_CONFIG}。`;
  }
  const command = extractToolCommandText(name, input);
  if (command && mentions(command, DATA_ACCESS_CONFIG)) {
    return `展示级别只能由研究者用 /data-access 修改。模型的 shell 不处理 ${DATA_ACCESS_CONFIG}；需要查看时用 read。`;
  }
  if (relativePath && isToolOutputLog(relativePath) && name !== "psyclaw_recall_output" && (CONTENT_TOOLS.has(name) || name === "write" || name === "edit")) {
    return "工具输出缓存不能整段读入模型。需要中段时用 psyclaw_recall_output 按行取回。";
  }
  if (CONTENT_TOOLS.has(name) && relativePath && accessFor(relativePath, entries) === "script-only") {
    return blockReason(relativePath);
  }
  if (command && isDirectDisplay(command) && mentions(command, TOOL_OUTPUT_LOG_DIR)) {
    return "工具输出缓存不能整段读入模型。需要中段时用 psyclaw_recall_output 按行取回。";
  }
  if (!command || !isDirectDisplay(command)) return undefined;
  for (const entry of entries) {
    if (entry.access === "script-only" && mentions(command, entry.path)) return blockReason(entry.path);
  }
  return undefined;
}

function isToolOutputLog(path: string): boolean {
  return path === TOOL_OUTPUT_LOG_DIR || path.startsWith(`${TOOL_OUTPUT_LOG_DIR}/`);
}

function blockReason(path: string): string {
  return `${path} 的展示级别是 script-only，不能把文件内容直接读入模型。请用分析脚本处理；行数、列名和缺失可以用 psyclaw_data_profile。`;
}

export function redactScriptOnlyOutput(text: string, entries: readonly DataAccessEntry[]): string {
  const prefixes = [...entries.filter((entry) => entry.access === "script-only").map((entry) => entry.path), TOOL_OUTPUT_LOG_DIR];
  if (prefixes.length === 0 || !text) return text;
  let removed = 0;
  const kept = text.split("\n").filter((line) => {
    const trimmed = line.trimStart().replace(/^\.\//, "");
    const hit = prefixes.some((prefix) => trimmed.startsWith(`${prefix}:`) || trimmed.startsWith(`${prefix}/`));
    if (hit) removed += 1;
    return !hit;
  });
  if (removed === 0) return text;
  return `${kept.join("\n")}\n[psyclaw:data-access withheld ${removed} lines from script-only files]`;
}
