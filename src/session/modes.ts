import { RESIDENT_METHOD_RULES } from "../analysis/method-rules.js";
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
  // Explicit literature/writing/review intent wins when the same request also
  // mentions an analysis construct (for example, a literature review about
  // multiple mediation). The research topic must not reroute the requested
  // academic task into analysis mode.
  if (resolveAcademicSoftRoute(text)) {
    return {
      target: "academic",
      notify: "当前是 chat 模式，但请求像是文献调研/写作/审稿。请按 Shift+Tab 直到底部显示 academic 后再继续（不会自动切换）。",
    };
  }
  if (resolveStatsIntent(text)) {
    return {
      target: "analysis",
      notify: "当前是 chat 模式，但请求像是数据分析。请按 Shift+Tab 直到底部显示 analysis 后再继续（不会自动切换）。",
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

/** Extra analysis-mode guidance for unattended runs (no UI, e.g. `psyclaw run` / Pi --print). */
export function unattendedAnalysisPrompt(): string {
  return [
    "## Unattended run (no interactive UI)",
    "Nobody can review intermediate files in this run, so skip the steps that only serve an interactive reviewer. These rules take precedence over the analysis workflow above where they conflict.",
    "- Take the task from the brief and the files it names. Do not explore plan or HANDOFF templates to understand the task. Skills listed in the system prompt may be read.",
    "- If the task names where deliverables go, write the analysis script there and run it from there. Do not keep a second copy under analysis/scripts/ and do not add a run_all wrapper.",
    "- One-off exploratory checks (value counts, cross-tabs, a variable's range) may run inline through bash with `Rscript -e` or `python3 -c`. Write a script file only for analyses that belong in the reproducible pipeline.",
    "- Explore the data in one or two batched checks (structure, codings, value counts, missingness, group cross-tabs together), not one variable per call.",
    "- Write the complete analysis script once the plan lists every model. Fix errors with targeted edits; add a late analysis as one appended section and rerun once.",
    "- Have the script print a short summary and write every reported number to tables or a key-numbers file. Read that file; do not page through long logs with sed, awk or tail.",
    "- When an approver tool is available, ask only about decisions the brief leaves open that change the analysis (sample rules, coding and scoring, missing data, model specification, inference and decision rules). Settle one decision per question: each option is one way to settle that single point, within the tool's option limit. Do not bundle several choices (for example interval type, number of resamples and a decision rule) into one option.",
    "- Offer the standard alternatives for that point first (for example 1000, 5000 or 10000 bootstrap resamples; a percentile or BCa interval; each exclusion rule as its own question rather than a final N), and state the facts each option relies on so that their counts add up to the total.",
    "- If every option is rejected, do not switch to a new bundle: split the rejected options into single components and ask about each until each is settled. When the approver says which part of a plan is wrong, ask about the rules of that part one at a time, not about its result (each exclusion rule, not which N).",
    "- Before settling a standard element yourself, ask whether it was planned: scale scoring, missing-data handling, a latent or measurement model and its estimator, fit criteria, and decision rules such as an equivalence bound.",
    "- Ask for each approval of a whole plan or report once; if it does not settle, proceed and record that in the report.",
    "- Costly computations: time a bootstrap, permutation test, simulation or repeated refit at a small size first (for example B = 50 or a subsample) and estimate the full run time. If it exceeds a few minutes, use an analytic equivalent or fewer draws yourself, without asking, and record the timing and the choice in decisions.md.",
    "- Do not run /crosscheck, /verify or a re-implementation of the analysis in a second language unless the task asks for it. State in the report that the results were not cross-checked (未经核对).",
    "- Do not produce figures unless the task asks for them.",
    "- Fill in analysis/plans/plan.md once, before executing. Do not write analysis/HANDOFF.md unless the task asks for it.",
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
      "Use psyclaw_data_profile for row counts, columns, and missingness, and with query to look up variables in an xlsx codebook; psyclaw_run_analysis to run any project R or Python script, exploratory or the full pipeline; psyclaw_read_results for a saved confirmatory table. Those results stay in context. A long bash or read result is clipped after you reply; its tail names a log under .psyclaw/cache/tool-output. Use psyclaw_recall_output with a line range to bring that middle back. Edit scripts with edit or write. Do not use bash for cat, sed, ls, grep, find, or python/heredoc file patches. bash is only for a command none of those tools can run.",
      "data/secret is script-only unless .psyclaw/data-access.json sets it to full: do not read, cat, head, or grep its contents. Analysis scripts may open it on disk. data/raw stays readable. The researcher sets other files with /data-access; do not edit that config.",
      "Soft「可以」only settles the current choice card. Script execution requires the typed ritual (unless /plan auto).",
      `Standing method rules: ${RESIDENT_METHOD_RULES}`,
      "Costly computations: before a bootstrap, permutation test, simulation or repeated refit, time it at a small size (for example B = 50 or a subsample) and estimate the full run time. If it exceeds a few minutes, do not decide yourself: present a choice card with the estimate and the options (run in full, fewer draws, an analytic equivalent, or skip), and wait for the user's choice.",
      "Before asking for plan approval, fill in the hypotheses-to-models table already laid out in analysis/plans/plan.md (one row per hypothesis and exploratory variable; keep its columns). When the approver can only pick options, the approval card lists approve plus one revise_<element> option per element, each with its concrete alternative.",
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
