/**
 * Standing method rules and the on-demand detail layer.
 * The short rules ride in the plan template and the analysis prompt.
 * The matching skill body is injected on the turn that needs it, as part of
 * the user message, so the observation mask never clips it as a tool result.
 */
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const METHOD_TOPICS = [
  "change-scores",
  "interactions",
  "mediation",
  "multilevel",
  "sem",
  "report",
] as const;

export type MethodTopic = (typeof METHOD_TOPICS)[number];

export const METHOD_SKILL_NAMES: Record<MethodTopic, string> = {
  "change-scores": "method-change-scores",
  interactions: "method-interactions",
  mediation: "method-mediation",
  multilevel: "method-multilevel",
  sem: "method-sem",
  report: "report-checklist",
};

/** About 4k tokens at roughly 4 characters per token. */
export const METHOD_INJECT_CHAR_BUDGET = 16_000;

export const RESIDENT_METHOD_RULES = [
  "Subgroup claims: test the focal term × group in one pooled model and report each group's slope.",
  "Moderation with a grouping factor: include the three-way term.",
  "Exploratory variables: test the main effect and moderation of each focal exposure.",
  "Run every implied test for every outcome.",
  "Change across waves: test overall change first, then add terms.",
  "One pooled model per outcome; mean-centre continuous predictors that enter a product.",
  "Several treatment arms: each arm against the reference is primary; a pooled contrast is supplementary.",
  "Cross a measured predictor with each condition contrast.",
  "Clustered or repeated data: use the maximal random-effects structure the design justifies; simplify only when it fails to converge, and say what was dropped.",
  "Stimuli repeated within participants: add a crossed random intercept for the stimulus as a robustness model.",
  "State the sign of a difference score and check each interpretation against it.",
  "If you name a confound in your primary measure and a variant removes it, make the variant primary or report both side by side, and say why.",
  "Report every model term, covariates included.",
].join(" ");

// English stems are anchored at a word start so that "immediately" is not mediation and
// "moderately" is not moderation. Cues name the design (nesting, repeated measures, latent
// variables), not any one study.
const TOPIC_PATTERNS: Record<MethodTopic, RegExp> = {
  "change-scores": /差分|变化分数|前后测|前测|后测|基线|随访|配对样本|总体变化|纵向|两期|\b(?:longitudinal|time [12]|at each wave|each wave|difference scores?|change scores?|ancova|pre-?post|pre-?test|post-?test|baseline|follow-?up|baseline-adjust\w*|lord'?s paradox|across (?:the )?waves|two waves|paired (?:samples?|t-?test))\b/i,
  interactions: /交互|调节|简单斜率|三阶|中心化|\b(?:moderates? the (?:effect|association|relationship|link)|(?:stronger|weaker) (?:for|among|in)|moderat(?:or|ors|ion|ing|es)|moderated by|interactions?|simple slopes?|mean-cent\w*|centering|centred|johnson[- ]?neyman|differs? (?:by|between|across)|depends? on)\b/i,
  mediation: /中介|间接效应|\b(?:mediat\w*|indirect effects?)\b/i,
  multilevel: /多层|混合效应|混合模型|随机截距|随机斜率|嵌套|重复测量|被试内|日记|经验取样|逐试次|每个试次|每天|每晚|\b(?:on each trial|each trial|trial-by-trial|per trial|trials per (?:condition|block|participant)|each (?:day|night|evening|morning)|daily|every day|for \d+ (?:days|weeks)|multilevel|multi-level|hierarchical linear|mixed[- ](?:effects?|models?)|random (?:intercepts?|slopes?|effects?)|nested (?:with)?in|repeated measures?|within-(?:person|subjects?|participants?)|clustered|daily diary|diary study|experience sampling|ecological momentary|ema|trial-level|each (?:participant|person) completed (?:several|multiple|many))\b/i,
  sem: /结构方程|路径分析|验证性因子|因子分析|因子结构|因子模型|潜变量|测量模型|\b(?:[\w-]+-factor model|factor (?:model|structure)|SEM|structural equation|path (?:model|analysis)|confirmatory factor|factor analysis|latent (?:variables?|factors?)|measurement (?:model|invariance)|lavaan)\b/i,
  report: /写报告|结果报告|report\.md|\/paper\/|HANDOFF|handoff/i,
};

export function methodTopicsIn(text: string): MethodTopic[] {
  return METHOD_TOPICS.filter((topic) => TOPIC_PATTERNS[topic].test(text));
}

/** True when the message names a loaded skill as a whole word (not inside another word such as "semester"). */
export function mentionsLoadedSkill(text: string, names: readonly string[]): boolean {
  const lower = text.toLocaleLowerCase();
  const wordChar = /[a-z0-9_-]/;
  return names.some((name) => {
    const token = name.trim().toLocaleLowerCase();
    if (token.length < 2) return false;
    for (let at = lower.indexOf(token); at !== -1; at = lower.indexOf(token, at + 1)) {
      const before = at === 0 ? "" : lower[at - 1]!;
      const after = lower[at + token.length] ?? "";
      if (!wordChar.test(before) && !wordChar.test(after)) return true;
    }
    return false;
  });
}

export function bundledCoreSkillsDir(): string {
  let dir = dirname(fileURLToPath(import.meta.url));
  for (let depth = 0; depth < 6; depth += 1) {
    const candidate = join(dir, "skills", "core");
    if (existsSync(join(candidate, "manifest.json"))) return candidate;
    dir = dirname(dir);
  }
  throw new Error("Cannot locate skills/core");
}

export interface MethodSkillDocument {
  topic: MethodTopic;
  name: string;
  path: string;
  body: string;
}

export async function loadCoreMethodSkills(coreDir = bundledCoreSkillsDir()): Promise<MethodSkillDocument[]> {
  const loaded: MethodSkillDocument[] = [];
  for (const topic of METHOD_TOPICS) {
    const dir = join(coreDir, METHOD_SKILL_NAMES[topic]);
    const text = await readFile(join(dir, "SKILL.md"), "utf8");
    loaded.push({ topic, name: METHOD_SKILL_NAMES[topic], path: dir, body: skillBody(text) });
  }
  return loaded;
}

export function skillBody(markdown: string): string {
  const normalized = markdown.replace(/^\uFEFF/, "");
  const match = normalized.match(/^---[ \t]*\r?\n[\s\S]*?\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|$)/);
  return (match ? normalized.slice(match[0].length) : normalized).trim();
}

export interface InjectionBlock {
  topic: MethodTopic;
  skill: string;
  path: string;
  source: "core" | "user" | "both";
  body: string;
}

export function renderMethodBlocks(
  blocks: readonly InjectionBlock[],
  budget = METHOD_INJECT_CHAR_BUDGET,
): { text: string; included: MethodTopic[]; catalog: MethodTopic[] } {
  const parts: string[] = [];
  const catalogLines: string[] = [];
  const included: MethodTopic[] = [];
  const catalog: MethodTopic[] = [];
  let used = 0;
  for (const block of blocks) {
    const rendered = [
      `[psyclaw:method-skill topic=${block.topic} skill=${block.skill} source=${block.source} path=${block.path}]`,
      block.body,
      "[/psyclaw:method-skill]",
    ].join("\n");
    if (used + rendered.length > budget) {
      catalogLines.push(`- ${block.skill} (${block.topic}): ${block.path}`);
      catalog.push(block.topic);
      continue;
    }
    parts.push(rendered);
    included.push(block.topic);
    used += rendered.length;
  }
  if (catalogLines.length > 0) {
    parts.push(`[psyclaw:method-catalog]\n${catalogLines.join("\n")}\n[/psyclaw:method-catalog]`);
  }
  return { text: parts.join("\n\n"), included, catalog };
}

export function userSkillWinsNote(name: string, path: string, corePath: string): string {
  return `项目中有用户 skill ${name}（${path}），本回合以它为准。核心细则仅作目录：${corePath}`;
}
