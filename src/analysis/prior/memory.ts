/**
 * Compact memory of a settled prior plan. Later chat turns follow this text,
 * not the recall dialogue or the choice cards that produced it.
 */
import { readFile } from "node:fs/promises";
import { join } from "node:path";

export const PRIOR_MEMORY_REL = ".psyclaw/prior/memory.md";

const KEPT_SECTIONS = ["Hypotheses to models", "Decision points", "Verdict rules", "Declarations", "Pseudo", "Steps"];

export function settledPlanBody(markdown: string): string {
  const chunks = markdown.split(/\n(?=## )/);
  return chunks.filter((chunk) => {
    const title = chunk.match(/^## ([^\n]+)/)?.[1] ?? "";
    return KEPT_SECTIONS.some((name) => title.startsWith(name));
  }).join("\n").trim();
}

export function runFact(output: string): string {
  const lines = output.split("\n");
  const header = lines[0] ?? "";
  const log = lines.find((line) => line.startsWith("Log: "));
  if (header.startsWith("Ran ")) return [header, log].filter((line): line is string => Boolean(line)).join("\n");
  const short = header.replace(/\s+/g, " ").slice(0, 180);
  return short ? `Run did not start: ${short}` : "Run did not start.";
}

export function buildPriorMemory(planMarkdown: string, facts: { script: string; run: string }): string {
  const body = settledPlanBody(planMarkdown);
  return [
    "## Prior plan memory",
    "This settled plan is the only analysis contract. Later work follows these rows. Do not reopen recall or choice cards, and do not send the researcher to another mode for this work. Do not change a confirmed value unless they ask. A skill may fix the script so it matches these rows.",
    facts.script ? `Script: ${facts.script}` : "",
    facts.run,
    "",
    body,
    "",
  ].filter((line) => line !== undefined).join("\n").replace(/\n{3,}/g, "\n\n");
}

export async function readPriorMemory(root: string): Promise<string> {
  try {
    const text = (await readFile(join(root, PRIOR_MEMORY_REL), "utf8")).trim();
    return text;
  } catch {
    return "";
  }
}
