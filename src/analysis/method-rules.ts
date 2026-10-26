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
].join(" ");

const TOPIC_PATTERNS: Record<MethodTopic, RegExp> = {
  "change-scores": /差分|变化分数|difference score|ancova|前后测|配对样本|总体变化|change score|baseline-adjust|lord/i,
  interactions: /交互|调节|moderat|interaction|简单斜率|simple slope|三阶|中心化|mean-cent|centering|johnson[- ]?neyman/i,
  mediation: /中介|mediat/i,
  multilevel: /多层|混合效应|混合模型|multilevel|mixed[- ](?:effect|model)|随机截距|random intercept/i,
  sem: /\bSEM\b|结构方程|路径分析|验证性因子|confirmatory factor/i,
  report: /写报告|结果报告|report\.md|\/paper\/|HANDOFF|handoff/i,
};

export function methodTopicsIn(text: string): MethodTopic[] {
  return METHOD_TOPICS.filter((topic) => TOPIC_PATTERNS[topic].test(text));
}

export function mentionsLoadedSkill(text: string, names: readonly string[]): boolean {
  const lower = text.toLocaleLowerCase();
  return names.some((name) => {
    const token = name.trim().toLocaleLowerCase();
    return token.length >= 2 && lower.includes(token);
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
