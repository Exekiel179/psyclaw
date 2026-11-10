/**
 * Checks for a prior-mode script. An empty list means the script can be rendered.
 * Statistical procedures stay in the script; this module only reads labels.
 */
import { isStage4, optionIds, parseConstants, type PriorConstant } from "./constants.js";

export interface ScriptFunction {
  name: string;
  body: string;
  descriptive: boolean;
}

const PY_DEF = /^def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(/;
const R_DEF = /^([A-Za-z.][A-Za-z0-9._]*)\s*<-\s*function\b/;
const DESCRIPTIVE_NAME = /describ|explor|eda|profile|missing|codebook|covariate/i;
const HYPOTHESIS_MARK = /\bH\d+\b|hypoth|confirmatory|假设/;
const CONDITION = /\b(?:if|when|若)\s+([A-Z][A-Z0-9_]*)\s*(?:==|=|is|为)\s*["']?([\w.-]+)/i;
const IF_LINE = /^(\s*)if\b\s*\(?\s*([A-Z][A-Z0-9_]*)\s*==\s*["']?([\w.-]+)/;
const ITEM = /^\s*[-*]\s*`?([A-Za-z0-9_][A-Za-z0-9_.-]*)`?\s*:/gm;
const SLOT_IDS = new Set([
  "construct",
  "internal_validity",
  "internal",
  "validity",
  "statistical_conclusion",
  "conclusion",
  "dependence",
  "构念",
  "内部效度",
  "统计结论",
  "依赖",
]);
const STOP = new Set([
  "the", "and", "for", "with", "use", "used", "using", "usually", "score", "scores", "scored", "scoring",
  "analysis", "analyse", "analysed", "test", "tests", "model", "design", "problem", "problems", "data",
  "item", "items", "study", "studies",
]);

const RECALL_SLOTS: { label: string; re: RegExp }[] = [
  { label: "construct", re: /construct|构念/i },
  { label: "internal validity", re: /internal[_\s-]*validity|内部效度/i },
  { label: "statistical conclusion", re: /statistical[_\s-]*conclusion|统计结论/i },
  { label: "dependence", re: /dependence|依赖/i },
];

function functionEnd(lines: readonly string[], start: number): number {
  for (let index = start + 1; index < lines.length; index += 1) {
    const line = lines[index] ?? "";
    if (line.trim() === "") continue;
    if (line.startsWith(" ") || line.startsWith("\t")) continue;
    return index;
  }
  return lines.length;
}

export function scriptFunctions(source: string): ScriptFunction[] {
  const lines = source.split(/\r?\n/);
  const starts: { name: string; index: number }[] = [];
  lines.forEach((line, index) => {
    if (line.startsWith(" ") || line.startsWith("\t")) return;
    const name = PY_DEF.exec(line)?.[1] ?? R_DEF.exec(line)?.[1];
    if (name) starts.push({ name, index });
  });
  return starts.map((start) => {
    const body = lines.slice(start.index, functionEnd(lines, start.index)).join("\n");
    const descriptive = DESCRIPTIVE_NAME.test(start.name) && !HYPOTHESIS_MARK.test(body);
    return { name: start.name, body, descriptive };
  });
}

export function checkRecall(text: string): string[] {
  const body = text.trim();
  if (!body) return ["Recall is empty. For each hypothesis, write construct, internal validity, statistical conclusion, and dependence."];
  const problems: string[] = [];
  for (const block of hypothesisBlocks(body)) {
    const title = block.split(/\r?\n/).find((line) => line.trim())?.trim() ?? "recall";
    for (const slot of RECALL_SLOTS) {
      if (!slot.re.test(block)) problems.push(`${title}: missing ${slot.label}.`);
    }
  }
  return problems;
}

function hypothesisBlocks(text: string): string[] {
  const lines = text.split(/\r?\n/);
  const indexes = lines.flatMap((line, index) => (/^#{1,3}\s+\S/.test(line) || /^H\d+\b/.test(line) ? [index] : []));
  if (indexes.length === 0) return [text];
  return indexes.map((start, index) => lines.slice(start, indexes[index + 1] ?? lines.length).join("\n"));
}

/** Approach ids from `- id: ...` lines, excluding the four recall slots. */
export function recalledApproachIds(text: string): string[] {
  return [...text.matchAll(ITEM)]
    .map((match) => match[1] ?? "")
    .filter((id) => id && !SLOT_IDS.has(id.toLowerCase()));
}

function words(text: string): Set<string> {
  const out = new Set<string>();
  for (const raw of text.toLowerCase().split(/[^a-z0-9]+/)) {
    if (raw.length < 3 || STOP.has(raw)) continue;
    out.add(raw.length > 4 && raw.endsWith("s") && !raw.endsWith("ss") ? raw.slice(0, -1) : raw);
  }
  return out;
}

function overlap(left: Set<string>, right: Set<string>): number {
  if (left.size === 0 || right.size === 0) return 0;
  let shared = 0;
  for (const word of left) if (right.has(word)) shared += 1;
  const union = left.size + right.size - shared;
  return union === 0 ? 0 : shared / union;
}

function covered(recallId: string, constants: readonly PriorConstant[]): boolean {
  const rid = words(recallId);
  for (const constant of constants) {
    const options = optionIds(constant);
    if (options.some((option) => option.toLowerCase().includes(recallId.toLowerCase()))) return true;
    if (options.some((option) => overlap(rid, words(option)) >= 0.5)) return true;
    const bag = words([constant.name, ...options].join(" "));
    if (rid.size > 0) {
      let shared = 0;
      for (const word of rid) if (bag.has(word)) shared += 1;
      if (shared >= rid.size / 2) return true;
    }
  }
  return false;
}

interface Dependency {
  parent: string;
  value: string;
}

function dependenciesFromCode(source: string, names: ReadonlySet<string>): Map<string, Dependency> {
  const loads = new Map<string, (Dependency | null)[]>();
  const stack: { indent: number; parent: string; value: string }[] = [];
  for (const line of source.split(/\r?\n/)) {
    const indent = line.match(/^\s*/)?.[0].length ?? 0;
    while (stack.length > 0 && indent <= (stack.at(-1)?.indent ?? 0)) stack.pop();
    const frame = stack.at(-1);
    const assignment = /^(\s*)([A-Z][A-Z0-9_]*)\s*(?:=|<-)/.exec(line);
    if (!(assignment && names.has(assignment[2] ?? ""))) {
      for (const name of names) {
        if (new RegExp(`\\b${name}\\b`).test(line)) {
          const list = loads.get(name) ?? [];
          list.push(frame ? { parent: frame.parent, value: frame.value } : null);
          loads.set(name, list);
        }
      }
    }
    const conditional = IF_LINE.exec(line);
    if (conditional && names.has(conditional[2] ?? "")) {
      stack.push({ indent, parent: conditional[2] ?? "", value: conditional[3] ?? "" });
    }
  }
  const requires = new Map<string, Dependency>();
  for (const [name, sites] of loads) {
    if (sites.length === 0 || sites.some((site) => site === null)) continue;
    const first = sites[0];
    if (!first) continue;
    if (sites.every((site) => site?.parent === first.parent && site?.value === first.value)) {
      requires.set(name, first);
    }
  }
  return requires;
}

export function dependencyOf(source: string, constant: PriorConstant, constants: readonly PriorConstant[]): Dependency | undefined {
  const fromCode = dependenciesFromCode(source, new Set(constants.map((item) => item.name))).get(constant.name);
  if (fromCode) return fromCode;
  const match = CONDITION.exec(constant.reason);
  if (!match) return undefined;
  const parent = constants.find((item) => item.name === match[1]);
  const value = match[2] ?? "";
  if (!parent || !optionIds(parent).includes(value)) return { parent: match[1] ?? "", value };
  return { parent: parent.name, value };
}

export function checkPlanScript(source: string, recallText: string): string[] {
  const constants = parseConstants(source);
  const problems: string[] = [];
  if (!constants.some((constant) => constant.label)) {
    problems.push("No labeled constant. Each analysis choice needs @intent, @declare, or @pseudo on a top-level constant.");
  }
  for (const constant of constants) {
    if (!constant.label) {
      problems.push(`${constant.name} (line ${constant.line}) has no label. Use @declare or @pseudo if it is not a choice.`);
      continue;
    }
    if (constant.label === "intent" && isStage4(constant.name)) {
      problems.push(`${constant.name} is inference or a support rule (stage 4: alpha, tails, multiplicity, equivalence, what counts as support). Label it @declare and do not ask.`);
    }
    if (constant.label === "intent") {
      const others = constant.alternatives.filter((item) => item !== constant.value);
      if (others.length < 1) problems.push(`${constant.name} is @intent but lists no other value after |.`);
      if (!constant.reason) problems.push(`${constant.name} is @intent but has no reason after the dash.`);
    }
  }
  const functions = scriptFunctions(source);
  for (const constant of constants) {
    if (constant.label !== "intent" || isStage4(constant.name)) continue;
    const users = functions.filter((fn) => new RegExp(`\\b${constant.name}\\b`).test(fn.body));
    const hypothesisUse = users.some((fn) => !fn.descriptive);
    if (!hypothesisUse) {
      problems.push(`${constant.name} is @intent but is not used by a hypothesis test. If it only feeds a description, an exploration, or a covariate screen, label it @declare.`);
    }
  }
  for (const constant of constants) {
    if (!constant.label) continue;
    const match = CONDITION.exec(constant.reason);
    if (!match) continue;
    const parent = constants.find((item) => item.name === match[1]);
    const value = match[2] ?? "";
    if (!parent) problems.push(`${constant.name} depends on ${match[1]}, which is not a labeled constant.`);
    else if (!optionIds(parent).includes(value)) problems.push(`${constant.name} depends on ${parent.name} == ${value}, which is not one of that constant's values.`);
  }
  const missing = recalledApproachIds(recallText).filter((id) => !covered(id, constants));
  if (missing.length > 0) {
    problems.push(`These recalled approaches are not options of any constant: ${missing.join(", ")}. Add them (they may be @declare or @pseudo). Do not drop them.`);
  }
  if (!constants.some((constant) => constant.label === "declare" && isStage4(constant.name))) {
    problems.push("Stage 4 is missing. Declare alpha, tails, multiplicity, or the support rule as an @declare constant.");
  }
  return problems;
}
