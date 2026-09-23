import { describe, expect, it } from "vitest";
import {
  buildRecommendedSkillInstallTask,
  shouldSkipSkillInstallAsset,
} from "../../src/skills/install-guidance.js";

describe("skill install guidance", () => {
  it("uses a short academic-figure path that skips assets and QA scripts", () => {
    const text = buildRecommendedSkillInstallTask({
      name: "Academic Figure Skill",
      id: "academic-figure-skill",
      sourceRef: "https://github.com/TingxiYu/academic-figure-skill",
      target: "C:/proj/.psyclaw/imports/recommended/academic-figure-skill",
      scopeLabel: "项目目录（仅当前项目）",
    });
    expect(text).toContain("codeload.github.com/TingxiYu/academic-figure-skill");
    expect(text).toContain("assets/");
    expect(text).toContain("check_dimensions.py");
    expect(text).not.toContain("【下载】");
    expect(text).toContain("四步");
  });

  it("keeps a compact default path for other skills", () => {
    const text = buildRecommendedSkillInstallTask({
      name: "Paper to Zotero",
      id: "paper2zotero",
      sourceRef: "https://github.com/Timisic/paper2zotero-skill",
      target: "/tmp/x",
      scopeLabel: "项目目录",
    });
    expect(text).toContain("codeload");
    expect(text.length).toBeLessThan(900);
  });

  it("skips demo figure trees and large media", () => {
    expect(shouldSkipSkillInstallAsset("assets/figures/demo/a.png", "a.png", 100)).toBe(true);
    expect(shouldSkipSkillInstallAsset("scripts/check_dimensions.py", "check_dimensions.py", 12_000)).toBe(false);
    expect(shouldSkipSkillInstallAsset("assets/icon.png", "icon.png", 2 * 1024 * 1024)).toBe(true);
  });
});
