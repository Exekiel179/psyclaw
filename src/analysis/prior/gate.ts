/**
 * Prior mode never calls skills. Approval rewrites the script, runs it, and
 * leaves the session in plain chat, where skills are available.
 */

const DATA_EXT = /\.(csv|tsv|xlsx|xls|sav|dta|rds|rdata|parquet|feather|jsonl)$/i;
const RUN_SCRIPT = /analysis\/scripts\/(analysis|run_all)\.(py|r)\b|python3?\s+\S*analysis\.py|Rscript\s+\S*analysis\.R/i;
const RECALL_BLOCK = "Submit the recall with psyclaw_submit_recall first. Until then only the brief (BRIEF.md or psyclaw.md) can be read.";
const SKILL_BLOCK = "Prior mode does not call skills. After the approved script has run, the session is plain chat and skills are available.";
const RUN_BLOCK = "Do not run the outcome script yourself. After 「我已审阅并批准本方案」 the confirmed script is run automatically, then the session becomes plain chat.";

export interface PriorGateState {
  recallReady: boolean;
  planReady: boolean;
  approved: boolean;
}

function asRecord(input: unknown): Record<string, unknown> {
  return input && typeof input === "object" ? input as Record<string, unknown> : {};
}

function inputPath(input: unknown): string {
  const record = asRecord(input);
  for (const key of ["path", "filePath", "file", "entrypoint"]) {
    if (typeof record[key] === "string") return record[key] as string;
  }
  return "";
}

function inputCommand(input: unknown): string {
  const command = asRecord(input).command;
  return typeof command === "string" ? command : "";
}

function normalize(path: string): string {
  return path.replace(/\\/g, "/").replace(/^\.\//, "");
}

export function isBriefPath(path: string): boolean {
  const norm = normalize(path);
  const base = norm.split("/").at(-1)?.toLowerCase() ?? "";
  if (base === "brief.md") return true;
  if (base === "psyclaw.md" && !norm.toLowerCase().includes("data/")) return true;
  return false;
}

export function isDataPath(path: string): boolean {
  if (!path || isBriefPath(path)) return false;
  const norm = normalize(path).toLowerCase();
  if (/(^|\/)data\//.test(norm) || norm === "data") return true;
  if (DATA_EXT.test(norm)) return true;
  if (norm.includes("data_facts")) return true;
  return false;
}

export function isOutcomePath(path: string): boolean {
  const norm = normalize(path).toLowerCase();
  return /(^|\/)analysis\/results(\/|$)/.test(norm) || /(^|\/)results(\/|$)/.test(norm);
}

export function isSkillCall(toolName: string, path: string, command: string): boolean {
  const name = toolName.toLowerCase();
  if (name === "skill" || name.endsWith("_skill") || name.includes("skill")) return true;
  return isSkillPath(path) || isSkillPath(command);
}

function isSkillPath(path: string): boolean {
  const norm = normalize(path).toLowerCase();
  return /skill\.md\b/.test(norm) || /(^|[^a-z0-9_-])skills\//.test(norm);
}

export function priorToolBlock(mode: string, toolName: string, input: unknown, state: PriorGateState): string | undefined {
  if (mode !== "prior") return undefined;
  const name = toolName.toLowerCase();
  if (name === "psyclaw_submit_recall") return undefined;
  const path = inputPath(input);
  const command = inputCommand(input);
  if (isSkillCall(name, path, command)) return SKILL_BLOCK;
  if (name === "psyclaw_submit_plan_script" && !state.recallReady) return RECALL_BLOCK;
  if (!state.recallReady) {
    if (name === "psyclaw_data_profile" || name === "psyclaw_run_analysis" || name === "psyclaw_read_results") return RECALL_BLOCK;
    if (name === "bash") return RECALL_BLOCK;
    if (name === "write" || name === "edit") return RECALL_BLOCK;
    if (["read", "grep", "find", "ls", "glob"].includes(name) && (isDataPath(path) || isOutcomePath(path))) return RECALL_BLOCK;
    if (command && (isDataPath(command) || /\b(python3?|rscript|r)\b/i.test(command))) return RECALL_BLOCK;
    return undefined;
  }
  if (!state.approved && (name === "psyclaw_run_analysis" || name === "psyclaw_read_results" || isOutcomePath(path) || (command && isOutcomePath(command)) || RUN_SCRIPT.test(command))) {
    return RUN_BLOCK;
  }
  return undefined;
}
