import { analysisSoftRoutePrompt } from "../analysis/stats-router.js";
import { academicSoftRoutePrompt } from "../ars/academic-router.js";

/** PsyClaw session modes cycled by Shift+Tab. */
export type PsyClawSessionMode = "chat" | "analysis" | "academic";

export const SESSION_MODES: readonly PsyClawSessionMode[] = ["chat", "analysis", "academic"] as const;

/** Footer status label. */
export const MODE_STATUS: Record<PsyClawSessionMode, string | undefined> = {
  chat: "chat",
  analysis: "analysis",
  academic: "academic",
};

export const MODE_BORDER: Record<PsyClawSessionMode, ((text: string) => string) | undefined> = {
  chat: undefined,
  // amber-ish for analysis
  analysis: (text: string) => `\x1b[38;2;229;192;123m${text}\x1b[39m`,
  // teal for academic (ARS)
  academic: (text: string) => `\x1b[38;2;46;196;182m${text}\x1b[39m`,
};

export function nextSessionMode(current: PsyClawSessionMode): PsyClawSessionMode {
  const index = SESSION_MODES.indexOf(current);
  return SESSION_MODES[(index + 1) % SESSION_MODES.length] ?? "chat";
}

export function parseSessionMode(value: unknown): PsyClawSessionMode | undefined {
  if (value === "chat" || value === "analysis" || value === "academic") return value;
  return undefined;
}

/** Mode-specific guidance appended while that sticky mode is active. */
export function sessionModePrompt(mode: PsyClawSessionMode): string {
  if (mode === "chat") {
    return [
      "## PsyClaw mode: chat",
      "Plain assistant on the Pi harness. Do not force research workflows, /init, or ARS stages.",
      "If the user wants structured research, suggest Shift+Tab to analysis or academic, or /init to scaffold the project tree.",
    ].join("\n");
  }
  if (mode === "analysis") {
    return [
      "## PsyClaw mode: analysis",
      "Priority: get runnable analysis results; then AI `/crosscheck`, then mandatory human approval before treating the analysis as complete.",
      "Pipeline: clarify → review → plan → review → analyze → AI /crosscheck → human Panel verify → analysis report → hand off to academic.",
      "Write under data/clean, analysis/scripts|configs|results|plans, and analysis/HANDOFF.md. Never overwrite data/raw (or legacy .psyclaw/data/raw).",
      "Default: write local reproducible analysis scripts under analysis/scripts/ with mature libraries. Use MCP only for special backends (SPSS/Mplus/MNE/Stata) or when the user asks. Do not invent numerical results.",
      "After analysis (and before /handoff), run AI `/crosscheck` (process: data, citation existence, format) and `/verify` (substance: results hold, citation/method reasonableness). Human approval is forced by the completion gate via Panel「核实」or wake-options — not a user slash. AI-checked and skipped do not pass the gate.",
      "Do not claim analysis complete, write final HANDOFF as done, or invite academic mode until the human verify gate passes.",
      "When proposing more analyses, never close with「已经足够」as prose — offer a concrete new method first and put「已经足够」only as a selectable last option.",
      "Prefer natural-language confirmation (「可以」). That is not the same as the post-analysis human verify gate.",
      analysisSoftRoutePrompt(),
    ].join("\n");
  }
  return [
    "## PsyClaw mode: academic",
    "ARS research → write → review → revise pipeline. Prefer psyclaw_ars_multi_agent for Stage 3 seats.",
    "Consume analysis/HANDOFF.md and analysis/results when present; do not recompute statistics in this mode—switch to analysis if numbers are missing.",
    "Manuscripts go to paper/. Before claiming the full text is done or ready to export/submit: AI `/crosscheck` + `/verify`, then mandatory human Panel/wake verify (automatic gate; not a slash). Soft mid-draft warnings are fine; finalization is a hard human gate.",
    "Priority: produce the manuscript; second, keep key claims human-verified before finalization.",
    academicSoftRoutePrompt(),
  ].join("\n");
}
