/**
 * Academic-mode soft router: natural-language intent → a small allowlist of
 * bundled writing/review skills. Skills outside this set must be invoked
 * explicitly with `/skill:<name>` (or equivalent).
 */

export const ACADEMIC_SOFT_ROUTE_SKILLS = [
  "deep-research",
  "academic-paper",
  "academic-paper-reviewer",
  "academic-pipeline",
  "academic-paper-strategist",
  "academic-paper-composer",
  "nature-figure",
  "nature-ref-verifier",
  "nature-polishing",
] as const;

export type AcademicSoftRouteSkill = (typeof ACADEMIC_SOFT_ROUTE_SKILLS)[number];

export interface AcademicSoftRouteMatch {
  skill: AcademicSoftRouteSkill;
  reason: string;
  /** Optional ARS/academic-paper mode hint for the skill body. */
  modeHint?: string;
  priority: number;
}

interface RouteRule {
  skill: AcademicSoftRouteSkill;
  reason: string;
  modeHint?: string;
  /** Higher wins when several rules match. */
  priority: number;
  pattern: RegExp;
}

const ROUTE_RULES: readonly RouteRule[] = [
  {
    skill: "nature-figure",
    reason: "figure / plotting request",
    priority: 100,
    pattern: /nature[- ]?figure|配图|作图|画图|出图|科研绘图|论文图表|森林图|forest\s*plot|可视化图|manuscript figure|publication[- ]ready (figure|plot)|graphical abstract|机制示意|投稿级配图|投稿级.{0,6}图/i,
  },
  {
    skill: "nature-ref-verifier",
    reason: "citation field cross-check",
    priority: 95,
    pattern: /nature[- ]?ref|引用交叉|核对引用字段|交叉核验|多源字段核验|cross[- ]?check (refs?|citations?)|doi.*(核验|核对|verify)|verify.*(doi|citation|reference)|作者年份/i,
  },
  {
    skill: "nature-polishing",
    reason: "prose polish / finalization",
    priority: 90,
    pattern: /nature[- ]?polish|润色|polish(ing)? (the )?(prose|manuscript|paper|abstract)|终稿润色|语言润色|submission[- ]ready polish|只做.{0,8}润色|不改(结论|数据|引用|结构).{0,12}润色|润色.{0,12}不改(结论|数据|引用)/i,
  },
  {
    skill: "academic-paper-strategist",
    reason: "outline / writing strategy",
    priority: 88,
    pattern: /strategist|写作策略|优化大纲|规划大纲|详细大纲|paper strategy|optimize (the )?outline|重构论证|贡献点|大纲权衡|动笔前/i,
  },
  {
    skill: "academic-paper-composer",
    reason: "compose full manuscript from outline",
    priority: 86,
    pattern: /composer|按大纲写|按.{0,6}大纲写成|执行大纲|写成全文|写完整篇|通篇写作|compose (the )?(full )?manuscript|write (the )?paper from (this |the )?outline|execute the outline|章节级质量/i,
  },
  {
    skill: "academic-paper-reviewer",
    reason: "peer review / revision coaching",
    priority: 84,
    pattern: /reviewer|peer review|同行评审|模拟审稿|改稿|revision coach|rebuttal|点对点回复|审稿意见|方法学质疑/i,
  },
  {
    skill: "academic-pipeline",
    reason: "full ARS academic pipeline",
    priority: 82,
    pattern: /academic[- ]?pipeline|完整流水线|全流程写作|完整.{0,8}pipeline|端到端.{0,8}pipeline|end[- ]to[- ]end (paper|manuscript) pipeline|从选题到成稿/i,
  },
  {
    skill: "deep-research",
    reason: "literature research / synthesis",
    priority: 78,
    pattern: /deep[- ]?research|文献调研|文献检索|系统综述检索|annotated bibliography|knowledge map|文献地图|知识地图|检索式|可纳入的研究/i,
  },
  {
    skill: "academic-paper",
    reason: "ARS academic-paper lit-review mode",
    modeHint: "lit-review",
    priority: 70,
    pattern: /lit[- ]?review|文献综述(节|章节|写作)?|literature review section|放入论文引言/i,
  },
  {
    skill: "academic-paper",
    reason: "ARS academic-paper abstract mode",
    modeHint: "abstract",
    priority: 69,
    pattern: /\babstract\b|写摘要|摘要撰写|structured abstract|写一个.{0,12}abstract/i,
  },
  {
    skill: "academic-paper",
    reason: "ARS academic-paper outline mode",
    modeHint: "outline",
    priority: 68,
    pattern: /(?<!详细|优化|规划|重构)(写大纲|论文大纲|section outline)|\boutline\b(?!.*strategist)/i,
  },
  {
    skill: "academic-paper",
    reason: "ARS academic-paper citation-check mode",
    modeHint: "citation-check",
    priority: 72,
    pattern: /citation[- ]?check|引用检查|核对文末参考文献|reference list check|引文和文末|一一对应/i,
  },
  {
    skill: "academic-paper",
    reason: "ARS academic-paper writing / format",
    modeHint: "writing",
    priority: 50,
    pattern: /写论文|撰写论文|manuscript(?!\s+prose)|学术写作|format convert|排版导出|转 docx|转 pdf/i,
  },
];

const EXPLICIT_SKILL_OR_ARS = /^\/(?:skill:|ars(?:-|\b)|create-|agents\b|init\b|verify\b|grill\b|review\b|loop\b|mcp\b|plugin\b|provider\b|panel\b|pet\b|help\b|export\b)/i;

/** Out-of-allowlist or non-academic intents that must not soft-route. */
const HARD_NEGATIVE = /academic-grill|逐题追问|(独立样本|配对|重复测量).{0,6}t\s*检验|跑一下.{0,12}(回归|方差|anova)|不要写论文|今天天气/i;

export function isAcademicSoftRouteSkill(name: string): boolean {
  return (ACADEMIC_SOFT_ROUTE_SKILLS as readonly string[]).includes(name.trim());
}

function matchIndex(text: string, pattern: RegExp): number {
  const flags = pattern.flags.includes("g") ? pattern.flags : `${pattern.flags}g`;
  const re = new RegExp(pattern.source, flags);
  const hit = re.exec(text);
  return hit?.index ?? Number.POSITIVE_INFINITY;
}

function matchesFor(text: string): Array<AcademicSoftRouteMatch & { index: number }> {
  const hits: Array<AcademicSoftRouteMatch & { index: number }> = [];
  for (const rule of ROUTE_RULES) {
    const index = matchIndex(text, rule.pattern);
    if (!Number.isFinite(index)) continue;
    hits.push({
      skill: rule.skill,
      reason: rule.reason,
      priority: rule.priority,
      index,
      ...(rule.modeHint ? { modeHint: rule.modeHint } : {}),
    });
  }
  return hits;
}

/**
 * Rank allowlisted skills for academic-mode natural language (deduped by skill,
 * keeping the highest-priority rule per skill).
 *
 * Primary order for multi-intent asks: earliest cue in the utterance, then
 * rule priority. That keeps “先 A 再 B” routing to A first while still
 * surfacing B in the ranked follow-ups.
 */
export function rankAcademicSoftRoutes(text: string, limit: number = ACADEMIC_SOFT_ROUTE_SKILLS.length): AcademicSoftRouteMatch[] {
  const trimmed = text.trim();
  if (!trimmed || EXPLICIT_SKILL_OR_ARS.test(trimmed) || HARD_NEGATIVE.test(trimmed)) return [];
  const bestBySkill = new Map<AcademicSoftRouteSkill, AcademicSoftRouteMatch & { index: number }>();
  for (const hit of matchesFor(trimmed)) {
    const existing = bestBySkill.get(hit.skill);
    if (!existing || hit.priority > existing.priority || (hit.priority === existing.priority && hit.index < existing.index)) {
      bestBySkill.set(hit.skill, hit);
    }
  }
  return [...bestBySkill.values()]
    .sort((a, b) => a.index - b.index || b.priority - a.priority || a.skill.localeCompare(b.skill))
    .slice(0, Math.max(0, limit))
    .map(({ index: _index, ...match }) => match);
}

/**
 * Resolve the best allowlisted skill for academic-mode natural language.
 * Returns null when the utterance is explicit slash routing or too ambiguous.
 */
export function resolveAcademicSoftRoute(text: string): AcademicSoftRouteMatch | null {
  return rankAcademicSoftRoutes(text, 1)[0] ?? null;
}

/** Expand a soft-route match into a Pi skill invocation the user need not type. */
export function formatAcademicSoftRouteInvocation(
  match: AcademicSoftRouteMatch,
  userText: string,
  also: AcademicSoftRouteMatch[] = [],
): string {
  const modeLine = match.modeHint
    ? `Preferred mode / focus: ${match.modeHint}.`
    : "";
  const followUps = also
    .filter((item) => item.skill !== match.skill)
    .map((item) => item.skill);
  const followLine = followUps.length > 0
    ? `After the primary skill, continue with these allowlisted skills in order when the user request clearly needs them: ${followUps.join(" → ")}.`
    : "";
  return [
    `/skill:${match.skill}`,
    "",
    `Academic soft-route (${match.reason}). Load and follow this skill now; do not ask the user to retype /skill:${match.skill}.`,
    modeLine,
    followLine,
    "Pace with human checkpoints: split work into nodes (e.g. lit-review method → what will be shown → then execute). Confirm each node before the next heavy stage.",
    "If the user request is vague without a crisp research question, remind them to use /grill. If they seem short on ideas, remind them to use /brainstorm.",
    "Do not auto-start /crosscheck or /verify; ask first and wait for explicit agreement.",
    "Before downloading any open-access PDF, ask the user; if download fails or OA is unavailable, explain and provide the DOI link.",
    "User request:",
    userText.trim(),
  ].filter((line) => line !== undefined && line !== "").join("\n");
}

/** System-prompt contract for academic sticky mode. */
export function academicSoftRoutePrompt(): string {
  const list = ACADEMIC_SOFT_ROUTE_SKILLS.map((name) => `- ${name}`).join("\n");
  return [
    "## Academic soft-route (allowlist only)",
    "While academic mode is active, you may silently load and follow only these bundled skills without waiting for an explicit `/skill:` from the user:",
    list,
    "Routing preference (pick one primary skill, state it briefly, then proceed; for clearly multi-step asks, chain allowlisted skills in order):",
    "- Literature search / synthesis → deep-research",
    "- Paper-format lit-review / abstract / outline / citation-check / manuscript drafting → academic-paper",
    "- Peer review / revision / rebuttal → academic-paper-reviewer",
    "- End-to-end ARS pipeline → academic-pipeline",
    "- Writing strategy / optimized outline → academic-paper-strategist",
    "- Execute outline into full manuscript → academic-paper-composer",
    "- Publication figures → nature-figure",
    "- DOI/author/year field cross-check after citation work → nature-ref-verifier",
    "- Final prose polish only → nature-polishing",
    "Invoke the chosen skill via `/skill:<name>` (or the host skill tool) so the user can see it, then follow that skill. Do not ask the user to type the slash command when the intent is clear.",
    "Skills outside this allowlist must NOT be auto-selected. If another skill is needed, tell the user to run `/skill:<name>` explicitly (or `/skill` to manage installs).",
    "Explicit user `/skill:` or `/ars-*` always wins over soft routing.",
    "When intent is vague, prefer reminding `/grill` (pressure-test) or `/brainstorm` (ideation) over silently launching a full pipeline.",
    "Prefer more, smaller human-confirmable nodes over racing through lit-review + writing + verify in one pass.",
  ].join("\n");
}
