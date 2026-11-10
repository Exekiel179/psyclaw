/**
 * Render a prior script into analysis/plans/plan.md.
 * Decision points and verdict rules keep the columns decision-points.ts already checks.
 */
import { checkDecisionPoints } from "../decision-points.js";
import { isStage4, optionIds, parseConstants, settledBy, type PriorConstant, type PriorLabel } from "./constants.js";
import { dependencyOf, scriptFunctions, type ScriptFunction } from "./checks.js";

export const DEFAULT_CORE_N = 8;

export interface PriorCard {
  id: string;
  tier: "core" | "technical" | "later";
  value: string;
  options: string[];
  reason: string;
  requires?: { parent: string; value: string };
}

export interface RenderedPriorPlan {
  markdown: string;
  cards: PriorCard[];
  findings: string[];
}

function cell(value: string): string {
  return value.replace(/\|/g, "\\|").replace(/\r?\n/g, " ").trim();
}

function askNow(source: string, constant: PriorConstant, constants: readonly PriorConstant[]): boolean {
  const dependency = dependencyOf(source, constant, constants);
  if (!dependency) return true;
  const parent = constants.find((item) => item.name === dependency.parent);
  return parent?.value === dependency.value;
}

export function layerCards(source: string, coreN = DEFAULT_CORE_N): PriorCard[] {
  const constants = parseConstants(source).filter((constant) => constant.label === "intent" && !isStage4(constant.name));
  const limit = Number.isInteger(coreN) && coreN >= 1 && coreN <= 20 ? coreN : DEFAULT_CORE_N;
  const ready: PriorConstant[] = [];
  const later: PriorConstant[] = [];
  for (const constant of constants) {
    (askNow(source, constant, parseConstants(source)) ? ready : later).push(constant);
  }
  const cards: PriorCard[] = ready.map((constant, index) => ({
    id: constant.name,
    tier: index < limit ? "core" : "technical",
    value: constant.value,
    options: optionIds(constant),
    reason: constant.reason,
    ...dependencyField(source, constant),
  }));
  for (const constant of later) {
    cards.push({
      id: constant.name,
      tier: "later",
      value: constant.value,
      options: optionIds(constant),
      reason: constant.reason,
      ...dependencyField(source, constant),
    });
  }
  return cards;
}

function dependencyField(source: string, constant: PriorConstant): { requires?: { parent: string; value: string } } {
  const requires = dependencyOf(source, constant, parseConstants(source));
  return requires ? { requires } : {};
}

function hypothesisRows(constants: readonly PriorConstant[]): string[] {
  const groups = [...new Set(constants.map((constant) => constant.group).filter(Boolean))];
  const rows = (groups.length > 0 ? groups : ["unspecified"]).map((group) => {
    const tests = constants.filter((constant) => constant.label === "intent" && (constant.group === group || groups.length === 0)).map((constant) => constant.name);
    return `| ${cell(group)} | ${cell(group)} | — | — | ${cell(tests.join(", ") || "—")} | confirmatory |`;
  });
  return [
    "## Hypotheses to models",
    "",
    "| ID | Scope as worded | Outcome | Focal term | Implied tests | Status |",
    "| --- | --- | --- | --- | --- | --- |",
    ...rows,
  ];
}

function decisionRows(constants: readonly PriorConstant[]): string[] {
  const rows = constants.filter((constant) => constant.label === "intent" || constant.label === "declare").map((constant) => {
    const label = constant.label as PriorLabel;
    const options = optionIds(constant);
    const alternative = options.find((option) => option !== constant.value) ?? "";
    return `| ${constant.name} | ${cell(constant.reason || constant.name)} | ${cell(options.join(" / "))} | ${settledBy(label, constant.reason)} | ${cell(constant.value)} | ${cell(label === "intent" ? alternative : alternative)} |`;
  });
  return [
    "## Decision points",
    "",
    "| ID | Decision | Options | Settled by | Primary | Alternative (sensitivity) |",
    "| --- | --- | --- | --- | --- | --- |",
    ...rows,
  ];
}

function verdictRows(constants: readonly PriorConstant[]): string[] {
  const stage4 = constants.filter((constant) => constant.label === "declare" && isStage4(constant.name));
  const rows = stage4.map((constant) => `| ${cell(constant.group || "all")} | ${constant.name} | ${cell(constant.value)} | ${cell(constant.reason || constant.value)} |`);
  return [
    "## Verdict rules",
    "",
    "Locked from stage-4 declarations before any outcome model.",
    "",
    "| Hypothesis | Test | Alpha and multiplicity family | Counts as supported if |",
    "| --- | --- | --- | --- |",
    ...rows,
  ];
}

function cardSection(title: string, cards: readonly PriorCard[]): string[] {
  if (cards.length === 0) return [];
  return ["", `## ${title}`, "", ...cards.map((card, index) => {
    const others = card.options.filter((option) => option !== card.value);
    const depends = card.requires ? ` Depends on ${card.requires.parent} == ${card.requires.value}.` : "";
    return `${index + 1}. **${card.id}** = ${card.value}; other: ${others.join(", ") || "—"}. ${card.reason}${depends}`;
  })];
}

function stepLines(functions: readonly ScriptFunction[], constants: readonly PriorConstant[]): string[] {
  const labeled = new Set(constants.filter((constant) => constant.label && constant.label !== "pseudo").map((constant) => constant.name));
  if (functions.length === 0) return [];
  const lines = functions.map((fn, index) => {
    const used = [...labeled].filter((name) => new RegExp(`\\b${name}\\b`).test(fn.body));
    const tags = used.length > 0 ? ` (uses ${used.join(", ")})` : "";
    return `${index + 1}. ${fn.name}${tags}`;
  });
  return ["", "## Steps", "", ...lines];
}

export function renderPriorPlan(source: string, coreN = DEFAULT_CORE_N): RenderedPriorPlan {
  const constants = parseConstants(source);
  const cards = layerCards(source, coreN);
  const declared = constants.filter((constant) => constant.label === "declare");
  const pseudo = constants.filter((constant) => constant.label === "pseudo");
  const lines = [
    "# Analysis plan",
    "",
    "Rendered from labeled constants. Later analysis follows these rows.",
    "",
    ...hypothesisRows(constants),
    "",
    ...decisionRows(constants),
    "",
    ...verdictRows(constants),
    ...cardSection(`Core questions (${cards.filter((card) => card.tier === "core").length})`, cards.filter((card) => card.tier === "core")),
    ...cardSection(`Technical settings (${cards.filter((card) => card.tier === "technical").length}, confirm once at the current values)`, cards.filter((card) => card.tier === "technical")),
    ...cardSection(`After a parent choice (${cards.filter((card) => card.tier === "later").length})`, cards.filter((card) => card.tier === "later")),
    "",
    `## Declarations (${declared.length})`,
    "",
    ...declared.map((constant) => `- **${constant.name}** = ${constant.value}. ${constant.reason}`.trim()),
    "",
    `## Pseudo (${pseudo.length})`,
    "",
    ...(pseudo.length > 0 ? pseudo.map((constant) => `- **${constant.name}** = ${constant.value}. ${constant.reason}`.trim()) : ["- none"]),
    ...stepLines(scriptFunctions(source), constants),
    "",
  ];
  const markdown = `${lines.join("\n")}\n`;
  return { markdown, cards, findings: checkDecisionPoints(markdown) };
}

export function formatCardInstructions(cards: readonly PriorCard[]): string {
  const core = cards.filter((card) => card.tier === "core");
  const technical = cards.filter((card) => card.tier === "technical");
  const later = cards.filter((card) => card.tier === "later");
  const line = (card: PriorCard) => {
    const others = card.options.filter((option) => option !== card.value);
    return `- ${card.id} = ${card.value}; other: ${others.join(", ") || "—"}. ${card.reason}`;
  };
  return [
    core.length > 0 ? `Core, one card each, in this order:\n${core.map(line).join("\n")}` : "Core: none.",
    technical.length > 0 ? `Technical settings, one confirmation card:\n${technical.map(line).join("\n")}` : "Technical settings: none.",
    later.length > 0 ? `Ask only after the parent choice:\n${later.map(line).join("\n")}` : "Dependent questions: none.",
  ].join("\n\n");
}
