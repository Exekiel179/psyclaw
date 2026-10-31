/**
 * Decision points: the analytic forks of a plan, each marked with what settles it.
 *
 * Some forks follow from the brief, the data, or settled convention. Others depend
 * on what the researcher intended (an exclusion rule, a scoring key, analysing
 * groups separately or pooled, alpha, the multiplicity family, what counts as
 * support). A framework default must not silently settle the second kind. The plan
 * records every fork and locks the verdict rules before outcome models are run.
 * This module only reads `analysis/plans/plan.md`; it never blocks a run.
 */
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

export const DECISION_SOURCES = ["brief", "data", "convention", "intent"] as const;
export type DecisionSource = (typeof DECISION_SOURCES)[number];

export const DECISION_POINTS_HEADING = "## Decision points";
export const VERDICT_RULES_HEADING = "## Verdict rules";
const PLAN_PATH = "analysis/plans/plan.md";

/** Rows of the first markdown table under `heading`, keyed by lower-cased header cell. */
export function tableRowsUnder(markdown: string, heading: string): Record<string, string>[] {
  const lines = markdown.split(/\r?\n/);
  const start = lines.findIndex((line) => line.trim().toLowerCase().startsWith(heading.toLowerCase()));
  if (start < 0) return [];
  const table: string[] = [];
  for (const line of lines.slice(start + 1)) {
    if (/^#{1,6}\s/.test(line.trim())) break;
    if (line.trim().startsWith("|")) table.push(line.trim());
    else if (table.length > 0 && line.trim() !== "") break;
  }
  if (table.length < 2) return [];
  const cells = (line: string) => line.replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
  const header = cells(table[0] ?? "").map((cell) => cell.toLowerCase());
  return table.slice(2)
    .map(cells)
    .filter((row) => row.some((cell) => cell !== ""))
    .map((row) => Object.fromEntries(header.map((name, i) => [name, row[i] ?? ""])));
}

function sourceOf(value: string): DecisionSource | undefined {
  const lowered = value.toLowerCase();
  return DECISION_SOURCES.find((source) => lowered.startsWith(source));
}

/** Findings for the decision-points and verdict-rules tables; empty when both are complete. */
export function checkDecisionPoints(planMarkdown: string): string[] {
  const findings: string[] = [];
  const decisions = tableRowsUnder(planMarkdown, DECISION_POINTS_HEADING);
  if (decisions.length === 0) {
    findings.push("No decision points recorded: list each analytic fork and what settles it (brief, data, convention, intent).");
  }
  for (const row of decisions) {
    const id = row["id"] || row["decision"] || "?";
    const source = sourceOf(row["settled by"] ?? "");
    if (!source) {
      findings.push(`Decision ${id}: "Settled by" must be one of ${DECISION_SOURCES.join(", ")}.`);
      continue;
    }
    if (source === "intent" && !(row["primary"] ?? "").trim()) {
      findings.push(`Decision ${id} depends on researcher intent but has no primary choice.`);
    }
    if (source === "intent" && !(row["alternative (sensitivity)"] ?? row["alternative"] ?? "").trim()) {
      findings.push(`Decision ${id} depends on researcher intent: run the main alternative as a labelled sensitivity analysis, or note who settled it.`);
    }
  }
  const verdicts = tableRowsUnder(planMarkdown, VERDICT_RULES_HEADING);
  if (verdicts.length === 0) {
    findings.push("No verdict rules locked: state alpha, the multiplicity family and what counts as support for each hypothesis before running outcome models.");
  }
  return findings;
}

/** A short reminder for a tool result when the plan's decision tables are missing or incomplete. */
export async function decisionPointsNotice(root: string): Promise<string | undefined> {
  let markdown: string;
  try {
    markdown = await readFile(resolve(root, PLAN_PATH), "utf8");
  } catch {
    return undefined;
  }
  const findings = checkDecisionPoints(markdown);
  if (findings.length === 0) return undefined;
  const shown = findings.slice(0, 3);
  const more = findings.length > shown.length ? ` (+${findings.length - shown.length} more)` : "";
  return [`Plan check (${PLAN_PATH}), not a blocker${more}:`, ...shown.map((finding) => `- ${finding}`)].join("\n");
}
