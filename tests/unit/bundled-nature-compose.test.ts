import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { ACADEMIC_COMPOSE_SKILLS, NATURE_ARS_FILLERS } from "../../src/ars/profile.js";

describe("bundled Nature and academic compose skills", () => {
  it("lists Nature gap-fill and academic compose skills in the package manifest", async () => {
    const root = process.cwd();
    const manifest = JSON.parse(await readFile(join(root, "package.json"), "utf8")) as {
      pi: { skills: string[] };
      files: string[];
    };
    for (const filler of NATURE_ARS_FILLERS) {
      expect(manifest.pi.skills).toContain(`./vendor/nature-skills/skills/${filler.skill}`);
      await expect(readFile(join(root, "vendor", "nature-skills", "skills", filler.skill, "SKILL.md"), "utf8")).resolves.toContain(`name: ${filler.skill}`);
    }
    for (const skill of ACADEMIC_COMPOSE_SKILLS) {
      expect(manifest.pi.skills).toContain(`./vendor/academic-paper-skills/${skill}`);
      await expect(readFile(join(root, "vendor", "academic-paper-skills", skill, "SKILL.md"), "utf8")).resolves.toContain(`name: ${skill}`);
    }
    expect(manifest.files).toEqual(expect.arrayContaining([
      "vendor/nature-skills",
      "vendor/academic-paper-skills",
    ]));
    await expect(readFile(join(root, "vendor", "nature-skills", "LICENSE"), "utf8")).resolves.toMatch(/Apache License/i);
    await expect(readFile(join(root, "vendor", "academic-paper-skills", "LICENSE"), "utf8")).resolves.toContain("MIT License");
    const natureSource = JSON.parse(await readFile(join(root, "vendor", "nature-skills", "PSYCLAW_SOURCE.json"), "utf8")) as {
      commit: string;
      omissions: string[];
    };
    expect(natureSource.commit).toMatch(/^[a-f0-9]{40}$/);
    expect(natureSource.omissions.some((item) => item.includes("assets"))).toBe(true);
  });
});
