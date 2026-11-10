/**
 * Prior mode reads the plan from labeled constants at the top of an analysis script.
 *
 *   NAME = value  # @intent value | other — why the researcher must choose
 *   NAME = value  # @declare — why this needs no question
 *   NAME = value  # @pseudo — why the options cannot differ for any data
 *
 * One assignment per line, at column 0. Python `=` and R `<-` both count.
 * A comment directly above the constant, short and not itself a label, is the
 * hypothesis group it affects.
 */

export type PriorLabel = "intent" | "declare" | "pseudo";

export interface PriorConstant {
  name: string;
  value: string;
  line: number;
  group: string;
  label: PriorLabel | null;
  alternatives: string[];
  reason: string;
}

export const STAGE4_NAME = /^(ALPHA|ALPHA_LEVEL|SIGNIFICANCE_LEVEL|TAILS|TAILEDNESS|TAIL|MULTIPLICITY|MULTIPLE_COMPARISON|MULTIPLE_COMPARISONS|EQUIVALENCE|EQUIVALENCE_BOUND|SUPPORT|SUPPORT_RULE|DECISION_RULE|BOOTSTRAP|BOOTSTRAP_B|N_BOOT|N_RESAMPLES|RESAMPLES|CI_LEVEL|CONFIDENCE_LEVEL)$/;

/** Options that coincide only in this data set are a declaration, not a pseudo-choice. */
export const EQUIVALENT_REASON = /本数据等价|equivalent in this data|in (these|this) data|in this sample|removes no one|removes nobody|nobody is removed|same result in this/i;

export function isStage4(name: string): boolean {
  return STAGE4_NAME.test(name);
}

export function settledBy(label: PriorLabel, reason: string): "intent" | "convention" | "equivalent" {
  if (label === "intent") return "intent";
  if (EQUIVALENT_REASON.test(reason)) return "equivalent";
  return "convention";
}

const LABEL = /@(intent|declare|pseudo)\b\s*([\s\S]*)$/;
const ASSIGN = /^([A-Z][A-Z0-9_]*)\s*(?:=|<-)\s*(.*)$/;

function unquote(text: string): string {
  const trimmed = text.trim().replace(/,+$/, "");
  if (trimmed.length >= 2 && (trimmed[0] === "\"" || trimmed[0] === "'") && trimmed[0] === trimmed.at(-1)) {
    return trimmed.slice(1, -1);
  }
  return trimmed;
}

/** "value | other — why" → alternatives and reason. Mirrors the labels splitter. */
export function splitLabel(text: string): { alternatives: string[]; reason: string } {
  const rest = text.trim();
  let choices = "";
  let reason = "";
  if (/^[—–-]/.test(rest) || rest.startsWith("--")) {
    reason = rest.replace(/^[—–-\s]+/, "");
  } else {
    const match = /^(.*?)(?:\s+(?:—|–|--|-)\s+|:\s+)([\s\S]*)$/.exec(rest);
    if (match) {
      choices = match[1] ?? "";
      reason = match[2] ?? "";
    } else if (rest.includes("|")) {
      choices = rest;
    } else {
      reason = rest;
    }
  }
  const alternatives = choices.split("|").map(unquote).filter((item) => item !== "");
  return { alternatives, reason: reason.trim() };
}

function isGroupHeader(text: string): boolean {
  return text.length > 0
    && text.length <= 60
    && /[A-Za-z0-9]/.test(text)
    && !LABEL.test(text)
    && !/^[\W_]+$/.test(text);
}

function commentText(line: string): string | undefined {
  const trimmed = line.trim();
  if (!trimmed.startsWith("#")) return undefined;
  return trimmed.replace(/^#+\s?/, "").trim();
}

export function parseConstants(source: string): PriorConstant[] {
  const lines = source.split(/\r?\n/);
  const constants: PriorConstant[] = [];
  let group = "";
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index] ?? "";
    if (line.startsWith(" ") || line.startsWith("\t")) continue;
    const comment = commentText(line);
    if (comment !== undefined) {
      if (isGroupHeader(comment)) group = comment;
      continue;
    }
    const assignment = ASSIGN.exec(line.trim());
    if (!assignment) continue;
    const name = assignment[1] ?? "";
    const hash = (assignment[2] ?? "").indexOf("#");
    const rawValue = hash < 0 ? assignment[2] ?? "" : (assignment[2] ?? "").slice(0, hash);
    let labelText = hash < 0 ? "" : (assignment[2] ?? "").slice(hash + 1).trim();
    if (!LABEL.test(labelText)) {
      const following = commentText(lines[index + 1] ?? "");
      if (following && LABEL.test(following)) {
        labelText = following;
        index += 1;
      }
    }
    const match = LABEL.exec(labelText);
    const parsed = match ? splitLabel(match[2] ?? "") : { alternatives: [], reason: "" };
    constants.push({
      name,
      value: unquote(rawValue),
      line: index + 1,
      group,
      label: match ? match[1] as PriorLabel : null,
      alternatives: parsed.alternatives,
      reason: parsed.reason,
    });
  }
  return constants;
}

export function optionIds(constant: PriorConstant): string[] {
  const rest = constant.alternatives.filter((item) => item !== constant.value);
  return [constant.value, ...rest];
}
