/**
 * Write the researcher's confirmed option into each @intent constant, then
 * re-render the plan so the script that runs is the one they approved.
 */
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { atomicWriteFile } from "../../project/jsonl.js";
import { assertSafeProjectPath } from "../../project/paths.js";
import { optionIds, parseConstants, type PriorConstant } from "./constants.js";
import { renderPriorPlan } from "./render.js";

const PRIOR_PLAN_REL = "analysis/plans/plan.md";

export interface ChoiceLike {
  prompt: string;
  originalResponse: string;
  selectedIds: string[];
  selectedLabels: string[];
  context?: string;
}

const ASSIGN = /^([A-Z][A-Z0-9_]*)(\s*(?:=|<-)\s*)(.*)$/;

function literal(value: string): string {
  return /^-?\d+(?:\.\d+)?$/.test(value) ? value : JSON.stringify(value);
}

/** Later records win. A token is applied only when exactly one candidate constant lists it. */
export function updatesFromChoices(source: string, records: readonly ChoiceLike[]): Map<string, string> {
  const constants = parseConstants(source).filter((constant) => constant.label === "intent");
  const updates = new Map<string, string>();
  for (const record of records) {
    const named = constants.filter((constant) => new RegExp(`\\b${constant.name}\\b`).test(`${record.prompt}\n${record.context ?? ""}`));
    const pool = named.length > 0 ? named : constants;
    const tokens = [...record.selectedIds, ...record.selectedLabels, record.originalResponse.trim()];
    for (const token of tokens) {
      const value = token.trim();
      if (!value) continue;
      const hits = pool.filter((constant) => optionIds(constant).includes(value));
      if (hits.length === 1 && hits[0]) updates.set(hits[0].name, value);
    }
  }
  return updates;
}

export function applyConstantValues(source: string, updates: ReadonlyMap<string, string>): string {
  const newline = source.endsWith("\n") ? "\n" : "";
  const lines = source.replace(/\n$/, "").split(/\r?\n/).map((line) => {
    if (line.startsWith(" ") || line.startsWith("\t")) return line;
    const match = ASSIGN.exec(line);
    if (!match) return line;
    const name = match[1] ?? "";
    const next = updates.get(name);
    if (next === undefined) return line;
    const rhs = match[3] ?? "";
    const hash = rhs.indexOf("#");
    const comment = hash < 0 ? "" : rhs.slice(hash).trim();
    return `${name}${match[2] ?? " = "}${literal(next)}${comment ? `  ${comment}` : ""}`;
  });
  return `${lines.join("\n")}${newline || "\n"}`;
}

export async function readChoiceRecords(root: string): Promise<ChoiceLike[]> {
  let text = "";
  try {
    text = await readFile(join(root, ".psyclaw/choices.jsonl"), "utf8");
  } catch {
    return [];
  }
  const records: ChoiceLike[] = [];
  for (const line of text.split(/\r?\n/)) {
    if (!line.trim()) continue;
    try {
      const parsed = JSON.parse(line) as Partial<ChoiceLike>;
      if (typeof parsed.prompt !== "string" || typeof parsed.originalResponse !== "string") continue;
      records.push({
        prompt: parsed.prompt,
        originalResponse: parsed.originalResponse,
        selectedIds: Array.isArray(parsed.selectedIds) ? parsed.selectedIds.filter((item) => typeof item === "string") : [],
        selectedLabels: Array.isArray(parsed.selectedLabels) ? parsed.selectedLabels.filter((item) => typeof item === "string") : [],
        ...(typeof parsed.context === "string" ? { context: parsed.context } : {}),
      });
    } catch { /* skip a broken line */ }
  }
  return records;
}

export async function rewriteScriptFromChoices(root: string, scriptRelative: string, source: string): Promise<{ source: string; changes: string[] }> {
  const updates = updatesFromChoices(source, await readChoiceRecords(root));
  const constants = new Map<string, PriorConstant>(parseConstants(source).map((constant) => [constant.name, constant]));
  const changes: string[] = [];
  for (const [name, value] of updates) {
    if (constants.get(name)?.value === value) continue;
    changes.push(`${name} = ${value}`);
  }
  if (changes.length === 0) return { source, changes };
  const next = applyConstantValues(source, updates);
  await atomicWriteFile(await assertSafeProjectPath(root, scriptRelative), next);
  await atomicWriteFile(await assertSafeProjectPath(root, PRIOR_PLAN_REL), renderPriorPlan(next).markdown);
  return { source: next, changes };
}
