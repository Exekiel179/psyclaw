/**
 * Ecosystem gap-fill skills for the research/manuscript workflow.
 *
 * These do not replace PsyClaw core skills or an ARS pipeline when present.
 * They only fill thin stages: figures, bibliographic field checks, prose polish,
 * outline planning, and systematic composition.
 */

export const NATURE_SKILLS_PLUGIN_ID = "nature-skills-plugin" as const;
export const ACADEMIC_PAPER_SKILLS_PLUGIN_ID = "academic-paper-skills-plugin" as const;

export type EcosystemFillerId =
  | "nature-figure"
  | "nature-ref-verifier"
  | "nature-polishing"
  | "academic-paper-strategist"
  | "academic-paper-composer";

export interface EcosystemFiller {
  id: EcosystemFillerId;
  skill: string;
  aliases: readonly string[];
  stage: string;
  suite: "nature" | "academic-paper";
  /** Installed into new projects by default when network/catalog allow. */
  defaultInstall: boolean;
}

/** Default workflow fillers: Nature leaf skills + academic-paper planning/writing. */
export const ECOSYSTEM_FILLERS: readonly EcosystemFiller[] = [
  {
    id: "nature-figure",
    skill: "nature-figure",
    aliases: ["nature-figure"],
    stage: "figures / format",
    suite: "nature",
    defaultInstall: true,
  },
  {
    id: "nature-ref-verifier",
    skill: "nature-ref-verifier",
    aliases: ["nature-ref-verifier", "nature-citation"],
    stage: "integrity / citation-check",
    suite: "nature",
    defaultInstall: true,
  },
  {
    id: "nature-polishing",
    skill: "nature-polishing",
    aliases: ["nature-polishing"],
    stage: "finalization / prose polish",
    suite: "nature",
    defaultInstall: true,
  },
  {
    id: "academic-paper-strategist",
    skill: "academic-paper-strategist",
    aliases: ["academic-paper-strategist"],
    stage: "planning / outline",
    suite: "academic-paper",
    defaultInstall: true,
  },
  {
    id: "academic-paper-composer",
    skill: "academic-paper-composer",
    aliases: ["academic-paper-composer"],
    stage: "manuscript writing",
    suite: "academic-paper",
    defaultInstall: true,
  },
];

export const DEFAULT_ECOSYSTEM_FILLER_IDS: readonly EcosystemFillerId[] = ECOSYSTEM_FILLERS
  .filter((filler) => filler.defaultInstall)
  .map((filler) => filler.id);

export interface EcosystemFillerInput {
  skills?: ReadonlyArray<{ name?: string }> | undefined;
  systemPrompt?: string | undefined;
}

function namesFromAvailableSkillsBlock(systemPrompt: string): string[] {
  const block = systemPrompt.match(/<available_skills>([\s\S]*?)<\/available_skills>/i)?.[1];
  if (!block) return [];
  return [...block.matchAll(/<name>\s*([^<]+?)\s*<\/name>/gi)]
    .map((match) => match[1]?.trim().toLowerCase())
    .filter((name): name is string => Boolean(name));
}

export function loadedSkillNames(input: EcosystemFillerInput = {}): Set<string> {
  const names = new Set<string>();
  for (const skill of input.skills ?? []) {
    const name = skill.name?.trim().toLowerCase();
    if (name) names.add(name);
  }
  if (input.systemPrompt) {
    for (const name of namesFromAvailableSkillsBlock(input.systemPrompt)) names.add(name);
  }
  return names;
}

export function detectEcosystemFillers(input: EcosystemFillerInput = {}): EcosystemFillerId[] {
  const names = loadedSkillNames(input);
  return ECOSYSTEM_FILLERS
    .filter((filler) => filler.aliases.some((alias) => names.has(alias)))
    .map((filler) => filler.id);
}

export function formatEcosystemFillerStatus(present: readonly EcosystemFillerId[]): string {
  const presentSet = new Set(present);
  const lines = ["工作流查漏补缺 Skill（不替换核心流程）："];
  for (const filler of ECOSYSTEM_FILLERS) {
    const ready = presentSet.has(filler.id);
    lines.push(`- ${filler.skill}：${ready ? "已接入" : "未安装"}（${filler.stage}）`);
  }
  if (present.length < ECOSYSTEM_FILLERS.length) {
    lines.push(
      `未安装项会在项目初始化或启动时尝试默认安装；也可运行 /skill install <id>，或安装 Plugin ${NATURE_SKILLS_PLUGIN_ID} / ${ACADEMIC_PAPER_SKILLS_PLUGIN_ID}。`,
    );
  }
  return lines.join("\n");
}

function fillerInstructions(id: EcosystemFillerId, available: boolean): string {
  const table: Record<EcosystemFillerId, { available: string; missing: string }> = {
    "nature-figure": {
      available: "- AVAILABLE nature-figure (figures / format): when the manuscript needs publication figures, invoke nature-figure instead of ad-hoc matplotlib. Do not use it to rewrite the paper or invent data.",
      missing: "- MISSING nature-figure: leave figures unfinished or core-native; do not invent publication-ready charts.",
    },
    "nature-ref-verifier": {
      available: "- AVAILABLE nature-ref-verifier (integrity / citation-check): after citation audit, invoke nature-ref-verifier for DOI/author/year/field cross-checks. It does not replace claim-source entailment.",
      missing: "- MISSING nature-ref-verifier: keep citation-audit as the citation gate; do not claim multi-source field verification that was not run.",
    },
    "nature-polishing": {
      available: "- AVAILABLE nature-polishing (finalization / prose polish): after a draft exists, during finalization only, invoke nature-polishing for prose. It must not change research claims, citations, numbers, or section structure.",
      missing: "- MISSING nature-polishing: keep core writing output; do not claim Nature-style polish that was not run.",
    },
    "academic-paper-strategist": {
      available: "- AVAILABLE academic-paper-strategist (planning / outline): before full manuscript writing, invoke academic-paper-strategist for venue/style learning, evidence-backed gap framing, and a reviewer-scored outline. It plans; it does not fabricate citations or results.",
      missing: "- MISSING academic-paper-strategist: keep core planning/outline; do not claim strategist quality gates that were not run.",
    },
    "academic-paper-composer": {
      available: "- AVAILABLE academic-paper-composer (manuscript writing): after an outline exists, invoke academic-paper-composer for chapter-by-chapter writing with quality checkpoints. Preserve verified claims and citations; do not invent sources.",
      missing: "- MISSING academic-paper-composer: keep core writing path; do not claim composer quality checkpoints that were not run.",
    },
  };
  return available ? table[id].available : table[id].missing;
}

/** Prompt patch for an active research/manuscript turn. */
export function ecosystemFillerPatch(input: EcosystemFillerInput = {}): string {
  const present = new Set(detectEcosystemFillers(input));
  return [
    "## Ecosystem gap-fill",
    "Fill only the workflow gaps below. PsyClaw core skills (and ARS when active) remain the workflow source of truth: do not replace intake, evidence capture, claim/source gates, or researcher checkpoints. Invoke a listed skill through the visible skill tool so the user can see it. Treat outputs as verified only when a tool result or inspectable artifact exists.",
    ...ECOSYSTEM_FILLERS.map((filler) => fillerInstructions(filler.id, present.has(filler.id))),
  ].join("\n");
}
