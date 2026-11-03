import type { ResearchParadigm } from "../../core/contracts.js";

const PARADIGMS = new Set<ResearchParadigm>([
  "survey-observational",
  "qualitative-thematic",
  "experimental",
  "quasi-experimental",
  "longitudinal-panel",
  "meta-analysis",
  "ethnographic",
  "historical-documentary",
  "policy-legal",
  "mixed-methods",
]);

/** User-facing usage for `/init`. Prefix `Usage:` so telemetry treats it as expected. */
export const INIT_USAGE = "Usage: /init [--paradigm survey-observational] [研究目标]";

export type ParsedInitArgs =
  | { ok: true; goal?: string; paradigm?: ResearchParadigm }
  | { ok: false; message: string };

/**
 * Parse `/init` args without throwing. Bare `/init` still scaffolds; flag-shaped
 * input that is missing a goal or uses an unknown option returns a usage hint.
 */
export function parseInitArgs(args: string): ParsedInitArgs {
  const trimmed = args.trim();
  if (!trimmed) return { ok: true };

  if (trimmed.startsWith("-")) {
    const match = trimmed.match(/^--paradigm(?:=|\s+)(\S+)(?:\s+([\s\S]*))?$/i);
    const paradigm = match?.[1] as ResearchParadigm | undefined;
    const goal = match?.[2]?.trim();
    if (!match || !paradigm) {
      return { ok: false, message: INIT_USAGE };
    }
    if (!PARADIGMS.has(paradigm)) {
      return { ok: false, message: `Unsupported paradigm: ${paradigm}\n${INIT_USAGE}` };
    }
    if (!goal) {
      return { ok: false, message: INIT_USAGE };
    }
    return { ok: true, paradigm, goal };
  }

  return { ok: true, paradigm: "survey-observational", goal: trimmed };
}
