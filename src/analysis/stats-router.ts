/**
 * Analysis-mode stats intent router.
 * When matched in analysis mode, soft-takeover into the analysis-plan skill.
 * Does not compete with academic ARS soft-routing.
 */

export interface StatsIntentMatch {
  kind: "stats-analysis";
  reason: string;
}

const STATS_INTENT = /统计|分析数据|数据分析|跑(一下)?(检验|回归|方差|anova|相关)|t\s*检验|方差分析|回归分析|中介|调节|SEM|因子(分析)?|生存分析|功效|样本量|描述统计|探索性|EDA|analysis plan|统计方案|帮我分析|看一下(这个)?数据|dataset|csv|\.sav\b|独立样本|配对样本|重复测量|混合设计|多层(模型|线性)|meta[- ]?analysis|元分析/i;

const EXPLICIT_SKIP = /^\/(?:skill:|plan\b|ars(?:-|\b)|init\b|verify\b|grill\b|review\b|loop\b|mcp\b|agents\b|provider\b|panel\b|help\b)/i;

/** Academic writing intents should not steal analysis-plan takeover. */
const ACADEMIC_DOMINANT = /写论文|成稿|审稿|文献综述|润色终稿|\/ars-|academic-paper|同行评审/i;

export function resolveStatsIntent(text: string): StatsIntentMatch | null {
  const trimmed = text.trim();
  if (!trimmed || EXPLICIT_SKIP.test(trimmed)) return null;
  if (ACADEMIC_DOMINANT.test(trimmed) && !/先分析|先跑|数据分析|统计方案/.test(trimmed)) return null;
  if (!STATS_INTENT.test(trimmed)) return null;
  return { kind: "stats-analysis", reason: "statistical / data-analysis intent" };
}

export function formatAnalysisPlanTakeover(userText: string): string {
  return [
    "/skill:analysis-plan",
    "",
    "Analysis-plan soft takeover. Follow the analysis-plan skill stages now; do not ask the user to retype /skill:analysis-plan.",
    "Do not start academic/ARS writing. Do not invent numerical results.",
    "Default execution backend: write reproducible scripts under analysis/scripts/ using mature libraries (pandas/pingouin/statsmodels/scipy or R equivalents).",
    "Use MCP only when the user needs a special backend (SPSS/Mplus/MNE/Stata) or explicitly asks.",
    "Persist structured state with /plan (new|status|confirm|review|run|defer|handoff); soft confirm ≠ ARS checkpoint ≠ awaiting-human.",
    "User request:",
    userText.trim(),
  ].join("\n");
}

/** System-prompt contract for analysis sticky mode. */
export function analysisSoftRoutePrompt(): string {
  return [
    "## Analysis soft-route (stats plan)",
    "While analysis mode is active, clear statistical / data-analysis intents soft-takeover into `/skill:analysis-plan` without waiting for an explicit slash from the user.",
    "Stages: clarify + light EDA → structured proposal → soft human confirm (`/plan confirm`) → plan review (`/plan review`) → `/plan run` (now) or `/plan defer` (later).",
    "Default backend: local reproducible scripts under `analysis/scripts/`. MCP only for special backends or explicit request.",
    "Do not merge this with academic/ARS planning. After an accepted/completed plan (and results), update `analysis/HANDOFF.md` before switching to academic.",
    "Explicit `/skill:` or `/plan` always wins over soft routing. Academic writing intents belong in academic mode.",
  ].join("\n");
}
