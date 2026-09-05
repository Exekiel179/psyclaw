import { describe, expect, it } from "vitest";
import {
  detectNatureArsFillers,
  formatNatureArsFillerStatus,
  NATURE_ARS_FILLERS,
  PSYCLAW_ARS_PROFILE_VERSION,
  psyclawArsPatch,
} from "../../src/ars/profile.js";

describe("PsyClaw ARS profile v2", () => {
  it("keeps ARS as the workflow source and only gap-fills with Nature leaves", () => {
    const patch = psyclawArsPatch();
    expect(PSYCLAW_ARS_PROFILE_VERSION).toBe("2");
    expect(patch).toContain("## PsyClaw ARS profile v2");
    expect(patch).toContain("ARS remains the workflow source of truth");
    expect(patch).toContain("independent multi-agent review");
    expect(patch).toContain("## Nature gap-fill");
    expect(patch).toContain("do not replace academic-pipeline stages");
    expect(NATURE_ARS_FILLERS.map((filler) => filler.skill)).toEqual([
      "nature-figure",
      "nature-ref-verifier",
      "nature-polishing",
    ]);
  });

  it("does not treat identity-prompt mentions as installed Nature skills", () => {
    const present = detectNatureArsFillers({
      systemPrompt: "Figure generation should use nature-figure instead of matplotlib defaults.",
    });
    expect(present).toEqual([]);
    expect(psyclawArsPatch({ systemPrompt: "use nature-figure" })).toContain("MISSING nature-figure");
    expect(psyclawArsPatch({ systemPrompt: "use nature-figure" })).not.toContain("AVAILABLE nature-figure");
  });

  it("activates only loaded Nature fillers from Pi skill XML or skill names", () => {
    const xml = [
      "<available_skills>",
      "  <skill>",
      "    <name>nature-figure</name>",
      "    <description>Publication figures</description>",
      "  </skill>",
      "</available_skills>",
    ].join("\n");
    expect(detectNatureArsFillers({ systemPrompt: xml })).toEqual(["figure"]);
    expect(detectNatureArsFillers({ skills: [{ name: "nature-ref-verifier" }, { name: "nature-polishing" }] })).toEqual([
      "ref-verifier",
      "polishing",
    ]);
    const patch = psyclawArsPatch({ skills: [{ name: "nature-figure" }] });
    expect(patch).toContain("AVAILABLE nature-figure");
    expect(patch).toContain("MISSING nature-ref-verifier");
    expect(patch).toContain("MISSING nature-polishing");
    expect(patch).not.toContain("AVAILABLE nature-reviewer");
  });

  it("reports Chinese filler status without claiming missing skills are attached", () => {
    const text = formatNatureArsFillerStatus(["figure"]);
    expect(text).toContain("nature-figure：已接入");
    expect(text).toContain("nature-ref-verifier：未安装");
    expect(text).toContain("nature-polishing：未安装");
    expect(text).toContain("/plugin install nature-skills-plugin");
  });
});
