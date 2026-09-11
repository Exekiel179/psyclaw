import { describe, expect, it } from "vitest";
import {
  DEFAULT_ECOSYSTEM_FILLER_IDS,
  detectEcosystemFillers,
  ecosystemFillerPatch,
  formatEcosystemFillerStatus,
} from "../../src/workflows/ecosystem-fillers.js";

describe("ecosystem gap-fill skills", () => {
  it("defaults to Nature three + academic-paper strategist/composer", () => {
    expect(DEFAULT_ECOSYSTEM_FILLER_IDS).toEqual([
      "nature-figure",
      "nature-ref-verifier",
      "nature-polishing",
      "academic-paper-strategist",
      "academic-paper-composer",
    ]);
  });

  it("detects loaded fillers from skill names and available_skills blocks", () => {
    expect(detectEcosystemFillers({
      skills: [{ name: "nature-figure" }, { name: "academic-paper-composer" }],
    })).toEqual(["nature-figure", "academic-paper-composer"]);

    expect(detectEcosystemFillers({
      systemPrompt: `<available_skills><skill><name>nature-citation</name></skill></available_skills>`,
    })).toEqual(["nature-ref-verifier"]);
  });

  it("emits available/missing instructions without replacing core gates", () => {
    const patch = ecosystemFillerPatch({
      skills: [{ name: "nature-polishing" }, { name: "academic-paper-strategist" }],
    });
    expect(patch).toContain("## Ecosystem gap-fill");
    expect(patch).toContain("AVAILABLE nature-polishing");
    expect(patch).toContain("AVAILABLE academic-paper-strategist");
    expect(patch).toContain("MISSING nature-figure");
    expect(patch).toContain("MISSING academic-paper-composer");
    expect(patch).toMatch(/do not replace intake|claim\/source gates|core skills/i);
  });

  it("formats a Chinese status line for /init notifications", () => {
    const status = formatEcosystemFillerStatus(["nature-figure", "academic-paper-strategist"]);
    expect(status).toContain("nature-figure：已接入");
    expect(status).toContain("nature-ref-verifier：未安装");
    expect(status).toContain("academic-paper-composer：未安装");
    expect(status).toContain("academic-paper-skills-plugin");
  });
});
