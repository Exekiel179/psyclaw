import { describe, expect, it } from "vitest";
import {
  ACADEMIC_COMPOSE_SKILLS,
  ARS_PI_STATE_ENTRY_TYPE,
  detectNatureArsFillers,
  formatNatureArsFillerStatus,
  NATURE_ARS_FILLERS,
  NATURE_ARS_FILLERS_BUNDLED,
  PSYCLAW_ARS_PROFILE_VERSION,
  psyclawArsPatch,
  setArsPiSessionActive,
} from "../../src/ars/profile.js";

describe("PsyClaw ARS profile v3", () => {
  it("keeps ARS as the workflow source and gap-fills with bundled Nature leaves", () => {
    const patch = psyclawArsPatch();
    expect(PSYCLAW_ARS_PROFILE_VERSION).toBe("3");
    expect(NATURE_ARS_FILLERS_BUNDLED).toBe(true);
    expect(patch).toContain("## PsyClaw ARS profile v3");
    expect(patch).toContain("ARS remains the workflow source of truth");
    expect(patch).toContain("psyclaw_ars_multi_agent");
    expect(patch).toContain("## Nature gap-fill");
    expect(patch).toContain("do not replace academic-pipeline stages");
    expect(NATURE_ARS_FILLERS.map((filler) => filler.skill)).toEqual([
      "nature-figure",
      "nature-ref-verifier",
      "nature-polishing",
    ]);
    expect(ACADEMIC_COMPOSE_SKILLS).toEqual([
      "academic-paper-strategist",
      "academic-paper-composer",
    ]);
  });

  it("treats bundled Nature fillers as always available", () => {
    expect(detectNatureArsFillers()).toEqual(["figure", "ref-verifier", "polishing"]);
    expect(detectNatureArsFillers({ systemPrompt: "use nature-figure" })).toEqual([
      "figure",
      "ref-verifier",
      "polishing",
    ]);
    const patch = psyclawArsPatch();
    expect(patch).toContain("AVAILABLE nature-figure");
    expect(patch).toContain("AVAILABLE nature-ref-verifier");
    expect(patch).toContain("AVAILABLE nature-polishing");
    expect(patch).not.toContain("MISSING nature-figure");
  });

  it("reports Chinese filler status as built-in without plugin install hint", () => {
    const text = formatNatureArsFillerStatus(["figure", "ref-verifier", "polishing"]);
    expect(text).toContain("nature-figure：已内置");
    expect(text).toContain("nature-ref-verifier：已内置");
    expect(text).toContain("nature-polishing：已内置");
    expect(text).toContain("academic-paper-strategist");
    expect(text).toContain("academic-paper-composer");
    expect(text).not.toContain("/plugin install nature-skills-plugin");
  });

  it("setArsPiSessionActive writes ars-pi-state without requiring a chat turn", () => {
    const entries: Array<{ type: string; data: { active: boolean } }> = [];
    expect(setArsPiSessionActive((type, data) => entries.push({ type, data }), true)).toBe(true);
    expect(setArsPiSessionActive(undefined, true)).toBe(false);
    expect(entries).toEqual([{ type: ARS_PI_STATE_ENTRY_TYPE, data: { active: true } }]);
  });
});
