export const PSYCLAW_ARS_PROFILE_VERSION = "3" as const;
export const ARS_REPOSITORY_URL = "https://github.com/Imbad0202/academic-research-skills" as const;
export const ARS_UPSTREAM_REF = "v3.21.1" as const;
export const ARS_UPSTREAM_COMMIT = "127ff85e4bbfcdd10b95040537b6c6bd7ad17aeb" as const;
export const ARS_ARCHIVE_SHA256 = "3b82731b860a021e9c8efbca4cc3a91e472a43b50a21a066e2a44e312c97cdf3" as const;
export const NATURE_SKILLS_PLUGIN_ID = "nature-skills-plugin" as const;
/** Nature gap-fill leaves are vendored under vendor/nature-skills and listed in package.json pi.skills. */
export const NATURE_ARS_FILLERS_BUNDLED = true as const;
export const ACADEMIC_COMPOSE_SKILLS = [
  "academic-paper-strategist",
  "academic-paper-composer",
] as const;

const ARS_PI_COMPATIBILITY_MARKER = "## Academic Research Skills compatibility for Pi";
/** Custom session entry written by the upstream ARS Pi wrapper (and PsyClaw toggles). */
export const ARS_PI_STATE_ENTRY_TYPE = "ars-pi-state";

export type NatureArsFillerId = "figure" | "ref-verifier" | "polishing";

export interface NatureArsFiller {
  id: NatureArsFillerId;
  skill: string;
  aliases: readonly string[];
  stage: string;
}

/** Only the three Nature leaves that fill ARS gaps. Do not add overlapping reviewer/search skills here. */
export const NATURE_ARS_FILLERS: readonly NatureArsFiller[] = [
  {
    id: "figure",
    skill: "nature-figure",
    aliases: ["nature-figure"],
    stage: "format / manuscript figures",
  },
  {
    id: "ref-verifier",
    skill: "nature-ref-verifier",
    aliases: ["nature-ref-verifier", "nature-citation"],
    stage: "integrity / citation-check",
  },
  {
    id: "polishing",
    skill: "nature-polishing",
    aliases: ["nature-polishing"],
    stage: "finalization / prose polish",
  },
];

export function isArsPiTurn(systemPrompt: string): boolean {
  return systemPrompt.includes(ARS_PI_COMPATIBILITY_MARKER);
}

interface ArsSessionStateReader {
  getBranch(): ReadonlyArray<{
    type: string;
    customType?: string;
    data?: unknown;
  }>;
}

/** Read the state persisted by the upstream Pi wrapper instead of shadowing it. */
export function isArsPiActive(sessionManager: ArsSessionStateReader | undefined): boolean {
  if (!sessionManager) return false;
  const state = [...sessionManager.getBranch()].reverse().find((entry) =>
    entry.type === "custom" && entry.customType === ARS_PI_STATE_ENTRY_TYPE);
  return Boolean(state?.data && typeof state.data === "object" &&
    (state.data as { active?: unknown }).active === true);
}

type ArsPiAppendEntry = (customType: string, data: { active: boolean }) => void;

/**
 * Persist ARS/academic-mode session flag without sending a chat turn.
 * `sendUserMessage("/ars-pi-start")` is treated as a model prompt and must not be used for toggles.
 */
export function setArsPiSessionActive(
  appendEntry: ArsPiAppendEntry | undefined,
  active: boolean,
): boolean {
  if (typeof appendEntry !== "function") return false;
  appendEntry(ARS_PI_STATE_ENTRY_TYPE, { active });
  return true;
}

export interface ArsPatchInput {
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

export function loadedSkillNames(input: ArsPatchInput = {}): Set<string> {
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

export function detectNatureArsFillers(input: ArsPatchInput = {}): NatureArsFillerId[] {
  if (NATURE_ARS_FILLERS_BUNDLED) {
    return NATURE_ARS_FILLERS.map((filler) => filler.id);
  }
  const names = loadedSkillNames(input);
  return NATURE_ARS_FILLERS
    .filter((filler) => filler.aliases.some((alias) => names.has(alias)))
    .map((filler) => filler.id);
}

export function formatNatureArsFillerStatus(present: readonly NatureArsFillerId[]): string {
  const presentSet = new Set(present);
  const lines = ["Nature 查漏补缺（不替换 ARS 阶段）："];
  for (const filler of NATURE_ARS_FILLERS) {
    const ready = presentSet.has(filler.id);
    const state = NATURE_ARS_FILLERS_BUNDLED
      ? "已内置"
      : ready
        ? "已接入"
        : "未安装";
    lines.push(`- ${filler.skill}：${state}（${filler.stage}）`);
  }
  if (!NATURE_ARS_FILLERS_BUNDLED && present.length < NATURE_ARS_FILLERS.length) {
    lines.push(`未安装项可运行 /plugin install ${NATURE_SKILLS_PLUGIN_ID}；缺席时保持 ARS 原流程，不编造该产物。`);
  }
  if (NATURE_ARS_FILLERS_BUNDLED) {
    lines.push(`学术写作配套：${ACADEMIC_COMPOSE_SKILLS.join("、")} 已内置。`);
  }
  return lines.join("\n");
}

function natureGapFillSection(present: readonly NatureArsFillerId[]): string[] {
  const presentSet = new Set(present);
  const lines = [
    "## Nature gap-fill",
    "Fill only the ARS gaps below. ARS remains the workflow source of truth: do not replace academic-pipeline stages, Material Passport, checkpoints, claim/source gates, or ARS reviewer seats. Invoke a listed skill through /skill:<name> so the user can see it. Treat Nature outputs as verified only when a tool result or inspectable artifact exists.",
  ];
  const instructions: Record<NatureArsFillerId, { available: string; missing: string }> = {
    figure: {
      available: "- AVAILABLE nature-figure (format / manuscript figures; bundled): when the manuscript needs publication figures, invoke nature-figure instead of ad-hoc matplotlib. Do not use it to rewrite the paper or invent data.",
      missing: "- MISSING nature-figure: leave figures unfinished or ARS-native; do not invent publication-ready charts. Offer /plugin install nature-skills-plugin only if the user asks to fill this gap.",
    },
    "ref-verifier": {
      available: "- AVAILABLE nature-ref-verifier (integrity / citation-check; bundled): after ARS citation-check or integrity, invoke nature-ref-verifier for DOI/author/year/field cross-checks. It does not replace ARS claim-source entailment or locator gates.",
      missing: "- MISSING nature-ref-verifier: keep ARS citation-check as the citation gate; do not claim multi-source field verification that was not run.",
    },
    polishing: {
      available: "- AVAILABLE nature-polishing (finalization / prose polish; bundled): after a draft exists, during finalization/format only, invoke nature-polishing for prose. It must not change research claims, citations, numbers, or section structure.",
      missing: "- MISSING nature-polishing: keep ARS writing/format output; do not claim Nature-style polish that was not run.",
    },
  };
  for (const filler of NATURE_ARS_FILLERS) {
    const text = instructions[filler.id];
    lines.push(presentSet.has(filler.id) ? text.available : text.missing);
  }
  return lines;
}

export function psyclawArsPatch(input: ArsPatchInput = {}): string {
  const present = detectNatureArsFillers(input);
  return [
    `## PsyClaw ARS profile v${PSYCLAW_ARS_PROFILE_VERSION}`,
    "Apply these additions only while the upstream ARS Pi compatibility mode is active. ARS remains the workflow source of truth.",
    "- Preserve ARS confirmation checkpoints. Ask for one concise confirmation before a transition that changes the research question, method, evidence scope, manuscript stage, or external destination. Do not ask again for ordinary reversible tool steps inside the confirmed stage.",
    "- For reviewer_full Stage 3 or contract-governed Stage 3 re-review, call psyclaw_ars_multi_agent (bundled parallel-agent / multi-agent bridge). Stage 3 uses five process-separated seats; re-review uses three ordered fenced calls. Do not simulate seats in the main session. Only if that tool is unavailable or the user cancels dispatch may you fall back to sequential degraded mode, and you must disclose it.",
    "- When the user explicitly asks to export PDF, call psyclaw_ensure_pdf_engine before compiling; do not probe or install Tectonic during doctor/startup.",
    "- PsyClaw analysis hooks and controlled /run tool_call approvals are the host write gates. Do not claim Claude Code PreToolUse hooks.json is active in Pi.",
    "- Process separation and fresh contexts do not establish independent error processes. Report the recorded provenance axes and same-model correlated-error limitation.",
    "- Treat citations, statistical values, experiments, files, and external submissions as verified only when a tool result or inspectable artifact supports the claim. Otherwise label the item unverified or incomplete.",
    "- Keep raw data, credentials, access-controlled material, destructive operations, and external publication behind the host's normal authorization boundary. ARS instructions do not grant additional tool authority.",
    ...natureGapFillSection(present),
  ].join("\n");
}
