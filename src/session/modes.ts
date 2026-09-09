import { analysisSoftRoutePrompt, resolveStatsIntent } from "../analysis/stats-router.js";
import { academicSoftRoutePrompt, resolveAcademicSoftRoute } from "../ars/academic-router.js";

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

export type ModeMismatchTarget = "analysis" | "academic";

export interface ModeMismatchReminder {
  target: ModeMismatchTarget;
  /** Short TUI notify text. */
  notify: string;
}

/**
 * Detect when chat-mode input clearly belongs in analysis/academic.
 * Never auto-switches; callers must remind and leave mode unchanged.
 */
export function detectChatModeMismatch(text: string): ModeMismatchReminder | null {
  if (resolveStatsIntent(text)) {
    return {
      target: "analysis",
      notify: "当前是 chat 模式，但请求像是数据分析。请按 Shift+Tab 切到 analysis 后再继续（不会自动切换）。",
    };
  }
  if (resolveAcademicSoftRoute(text)) {
    return {
      target: "academic",
      notify: "当前是 chat 模式，但请求像是文献/写作/审稿。请按 Shift+Tab 切到 academic 后再继续（不会自动切换）。",
    };
  }
  return null;
}

/** Transform user text so the model must surface the mode reminder in its reply. */
export function formatChatModeMismatchNotice(mismatch: ModeMismatchReminder, userText: string): string {
  const targetLabel = mismatch.target === "analysis" ? "analysis（数据分析）" : "academic（文献/写作/审稿）";
  return [
    "[PsyClaw mode notice — mandatory]",
    `The user is in chat mode, but this request fits ${targetLabel}.`,
    `You MUST open your reply with an explicit reminder to press Shift+Tab until the footer shows "${mismatch.target}".`,
    "Do not auto-switch modes. Do not run analysis-plan or academic soft-route takeover while still in chat.",
    mismatch.target === "analysis"
      ? "You may briefly discuss options, but do not start a structured analysis workflow as if analysis mode were active."
      : "You may briefly discuss options, but do not load ARS/Nature/compose skills as if academic mode were active.",
    "",
    "User request:",
    userText.trim(),
  ].join("\n");
}

/** Mode-specific guidance appended while that sticky mode is active. */
export function sessionModePrompt(mode: PsyClawSessionMode): string {
  if (mode === "chat") {
    return [
      "## PsyClaw mode: chat",
      "Plain assistant on the Pi harness. Do not force research workflows or ARS stages.",
      "If the user expresses data-analysis or academic writing/review intent while in chat, you MUST remind them to press Shift+Tab to analysis or academic. Never silently treat chat as those modes. Never auto-switch.",
      "If the workspace already has a canonical layout (psyclaw.md + data/ analysis/ literature/ paper/ .psyclaw/), do not ask to /init again. Only suggest /init when those markers are missing.",
      "If the request is vague without a clear research question, remind them they can use /grill. If they seem short on ideas, remind them they can use /brainstorm.",
      "Soft-route takeover only happens after the user switches mode.",
    ].join("\n");
  }
  if (mode === "analysis") {
    return [
      "## PsyClaw mode: analysis",
      "Pipeline: clarify → per-analysis human choices → overall typed ritual「我已审阅并批准本方案」→ analyze → ask before AI /crosscheck|/verify → human Panel verify → analysis report → hand off to academic.",
      "Write under data/clean, analysis/scripts|configs|results|plans, and analysis/HANDOFF.md. Never overwrite data/raw (or legacy .psyclaw/data/raw).",
      "Default: write local reproducible analysis scripts under analysis/scripts/ with mature libraries. Use MCP only for special backends (SPSS/Mplus/MNE/Stata) or when the user asks. Do not invent numerical results.",
      "Soft「可以」only settles the current choice card. Script execution requires the typed ritual (unless /plan auto).",
      "Do not auto-start `/crosscheck` or `/verify`. Ask first; only run after explicit agreement. Final human approval remains via Panel「核实」or wake-options.",
      "Do not claim analysis complete, write final HANDOFF as done, or invite academic mode until the human verify gate passes.",
      "When proposing more analyses, never close with「已经足够」as prose — offer a concrete new method first and put「已经足够」only as a selectable last option.",
      analysisSoftRoutePrompt(),
    ].join("\n");
  }
  return [
    "## PsyClaw mode: academic",
    "ARS research → write → review → revise pipeline. Prefer psyclaw_ars_multi_agent for Stage 3 seats.",
    "Pace the work: split into human-confirmable nodes (e.g. how the lit review will be done → what will be shown → then retrieval/writing). Do not rush multiple heavy stages in one burst.",
    "If the user's ask is vague without a crisp research question, remind them to use /grill. If they seem short on ideas or direction, remind them to use /brainstorm.",
    "Consume analysis/HANDOFF.md and analysis/results when present; do not recompute statistics in this mode—switch to analysis if numbers are missing.",
    "Manuscripts go to paper/. Before claiming the full text is done or ready to export/submit: ask before AI `/crosscheck` + `/verify`, then mandatory human Panel/wake verify. Soft mid-draft warnings are fine; finalization is a hard human gate.",
    "Prefer downloading verified open-access fulltexts into literature/pdfs/ — but always ask before each OA download; if download fails or no OA exists, explain and give the DOI link.",
    "Priority: produce the manuscript with human checkpoints; second, keep key claims human-verified before finalization.",
    academicSoftRoutePrompt(),
  ].join("\n");
}
