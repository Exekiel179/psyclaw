import {
  DEFAULT_ECOSYSTEM_FILLER_IDS,
  type EcosystemFillerId,
} from "./ecosystem-fillers.js";
import {
  installRecommendedSkill,
  readRecommendationState,
  saveRecommendationState,
  validateInstalledRecommendedSkill,
} from "../skills/recommended.js";

export interface DefaultFillerEnsureResult {
  seeded: EcosystemFillerId[];
  installed: EcosystemFillerId[];
  alreadyPresent: EcosystemFillerId[];
  failed: Array<{ id: EcosystemFillerId; reason: string }>;
}

/**
 * Seed recommendation state with default workflow fillers and best-effort install.
 * Offline or install failures are recorded, never thrown: core PsyClaw must still start.
 */
export async function ensureDefaultEcosystemFillers(
  root: string,
  options: { install?: boolean; ids?: readonly EcosystemFillerId[] } = {},
): Promise<DefaultFillerEnsureResult> {
  const ids = [...(options.ids ?? DEFAULT_ECOSYSTEM_FILLER_IDS)];
  const shouldInstall = options.install !== false;
  const state = await readRecommendationState(root);
  const before = new Set(state.skills);
  const seeded = ids.filter((id) => !before.has(id));
  if (seeded.length > 0 || ids.some((id) => !state.skills.includes(id))) {
    const mergedSkills = [...new Set([...state.skills, ...ids])].sort();
    const skillScopes = { ...(state.skillScopes ?? {}) };
    for (const id of ids) {
      skillScopes[id] = skillScopes[id] ?? "project";
    }
    await saveRecommendationState(root, {
      ...state,
      skills: mergedSkills,
      skillScopes,
    });
  }

  const installed: EcosystemFillerId[] = [];
  const alreadyPresent: EcosystemFillerId[] = [];
  const failed: Array<{ id: EcosystemFillerId; reason: string }> = [];

  for (const id of ids) {
    try {
      await validateInstalledRecommendedSkill(root, id);
      alreadyPresent.push(id);
      continue;
    } catch {
      /* not installed yet */
    }
    if (!shouldInstall) continue;
    try {
      const result = await installRecommendedSkill(root, id);
      if (result.installed) installed.push(id);
      else alreadyPresent.push(id);
    } catch (error) {
      failed.push({
        id,
        reason: error instanceof Error ? error.message : String(error),
      });
    }
  }

  return { seeded, installed, alreadyPresent, failed };
}
