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
      "Priority: get runnable analysis results first; then reduce hallucination via AI field checks and human verify marks.",
      "Pipeline (soft, not hard-blocking): clarify → review → plan → review → analyze → analysis report → review → hand off to academic.",
      "Write under data/clean, analysis/scripts|configs|results|plans, and analysis/HANDOFF.md. Never overwrite data/raw (or legacy .psyclaw/data/raw).",
      "Default: write local reproducible analysis scripts under analysis/scripts/ with mature libraries. Use MCP only for special backends (SPSS/Mplus/MNE/Stata) or when the user asks. Do not invent numerical results.",
      "For important fields (N, primary effects, table–text consistency), run an AI semantic check and ask the human to mark items verified via /verify. Do not treat file hashes as academic proof.",
      "Do not hard-block ordinary progress for missing verify marks; label unverified claims clearly and continue unless the user stops you.",
      "Do not start ARS/paper writing here; bridge via analysis/HANDOFF.md after the plan has results.",
      analysisSoftRoutePrompt(),
    ].join("\n");
  }
  return [
    "## PsyClaw mode: academic",
    "ARS research → write → review → revise pipeline. Prefer psyclaw_ars_multi_agent for Stage 3 seats.",
    "Consume analysis/HANDOFF.md and analysis/results when present; do not recompute statistics in this mode—switch to analysis if numbers are missing.",
    "Manuscripts go to paper/. Per-stage reviews use AI field checks + human /verify marks; soft warnings only unless external publish or raw-data mutation.",
    "Priority: produce the manuscript and review artifacts; second, keep key claims human-verified where it matters.",
    academicSoftRoutePrompt(),
  ].join("\n");
}
