import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  enabledRecommendedSkillPaths,
  normalizeRecommendedSkillId,
  readRecommendationState,
  readRecommendedCatalog,
  recommendedSkillTarget,
  saveRecommendationState,
  setRecommendedSkillEnabled,
  validateInstalledRecommendedSkill,
  validateModelInstalledRecommendedSkill,
  RecommendedSkillUnavailableError,
} from "../../src/skills/recommended.js";

const sha = (value: string): string => createHash("sha256").update(value).digest("hex");

async function managedFixture(root: string, id: string): Promise<string> {
  const catalog = await readRecommendedCatalog();
  const plan = catalog.installPrep.find((candidate) => candidate.id === id)!;
  const skillName = plan.skillName!;
  const directory = join(root, ".psyclaw", "imports", "recommended", skillName);
  const skill = `---\nname: ${skillName}\ndescription: Fixture\n---\n\n# Fixture\n`;
  const license = "MIT fixture\n";
  await mkdir(directory, { recursive: true });
  await writeFile(join(directory, "SKILL.md"), skill, "utf8");
  await writeFile(join(directory, "LICENSE"), license, "utf8");
  await writeFile(join(directory, "psyclaw-install.json"), `${JSON.stringify({
    schemaVersion: "psyclaw/recommended-skill-install/v1",
    id,
    skillName,
    source: { kind: "git", url: plan.sourceUrl, ref: plan.ref, path: plan.skillPath },
    license: { spdx: plan.license, evidence: "LICENSE", sha256: sha(license) },
    skillSha256: sha(skill),
    dependencies: plan.dependencies,
    installedAt: "2026-08-29T00:00:00.000Z",
  }, null, 2)}\n`, "utf8");
  return directory;
}

describe("recommended Skill lifecycle", () => {
  it("does not offer the system-integrated ARS as a recommended download", async () => {
    const catalog = await readRecommendedCatalog();
    const ars = catalog.plugins.find((plugin) => plugin.id === "academic-research-suite-plugin");
    expect(ars).toBeUndefined();
  });

  it("migrates the old MarkItDown id in recommendation state", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-recommendations-"));
    await mkdir(join(root, ".psyclaw"), { recursive: true });
    await writeFile(join(root, ".psyclaw", "recommendations.json"), JSON.stringify({
      schemaVersion: "psyclaw/recommendation-state/v1",
      skills: ["markitdown-pro"],
      mcp: [],
    }), "utf8");
    expect(normalizeRecommendedSkillId("markitdown-pro")).toBe("markitdown-bilibili");
    await expect(readRecommendationState(root)).resolves.toMatchObject({ skills: ["markitdown-bilibili"] });
  });

  it("loads only enabled installs whose source, license, and content hashes validate", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-recommendations-"));
    const path = await managedFixture(root, "academic-reference-matcher");
    await saveRecommendationState(root, {
      schemaVersion: "psyclaw/recommendation-state/v1",
      skills: ["academic-reference-matcher"],
      mcp: [],
    });
    await expect(validateInstalledRecommendedSkill(root, "academic-reference-matcher")).resolves.toMatchObject({ path });
    await expect(enabledRecommendedSkillPaths(root)).resolves.toEqual({ paths: [path], warnings: [] });

    await writeFile(join(path, "SKILL.md"), "tampered\n", "utf8");
    const result = await enabledRecommendedSkillPaths(root);
    expect(result.paths).toEqual([]);
    expect(result.warnings.join("\n")).toMatch(/changed|frontmatter/i);
  });

  it("does not create nested Git metadata in the managed layout", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-recommendations-"));
    const path = await managedFixture(root, "academic-reference-matcher");
    const manifest = JSON.parse(await readFile(join(path, "psyclaw-install.json"), "utf8")) as { source: { ref: string } };
    expect(manifest.source.ref).toMatch(/^[a-f0-9]{40}$/);
    await expect(readFile(join(path, ".git", "HEAD"), "utf8")).rejects.toMatchObject({ code: "ENOENT" });
  });

  it("refuses to enable a recommended skill whose SKILL.md is missing, including paths with spaces and non-ASCII", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-skill-enable-"));
    const project = join(root, "practical psycology", "练习");
    const id = "literature-review";
    const target = recommendedSkillTarget(project, id, "project");
    await mkdir(target, { recursive: true });
    await writeFile(join(target, "README.md"), "partial install\n", "utf8");

    const missingFile = await setRecommendedSkillEnabled(project, id, true);
    expect(missingFile.ok).toBe(false);
    if (!missingFile.ok) {
      expect(missingFile.code).toBe("missing-files");
      expect(missingFile.needsInstall).toBe(true);
      expect(missingFile.enabled).toBe(false);
      expect(missingFile.target).toBe(target);
      expect(missingFile.target).toContain(join("practical psycology", "练习"));
      expect(missingFile.message).toContain("SKILL.md");
      expect(missingFile.message).toContain(target);
      expect(missingFile.message).not.toMatch(/ENOENT/);
    }
    await expect(readFile(join(project, ".psyclaw", "recommendations.json"), "utf8")).rejects.toMatchObject({ code: "ENOENT" });
    await expect(validateModelInstalledRecommendedSkill(project, id, "project")).rejects.toBeInstanceOf(RecommendedSkillUnavailableError);

    const absent = join(root, "practical psycology", "未安装");
    const notInstalled = await setRecommendedSkillEnabled(absent, id, true, "project");
    expect(notInstalled.ok).toBe(false);
    if (!notInstalled.ok) {
      expect(notInstalled.code).toBe("not-installed");
      expect(notInstalled.needsInstall).toBe(true);
      expect(notInstalled.target).toBe(recommendedSkillTarget(absent, id, "project"));
      expect(notInstalled.target).toContain("未安装");
      expect(notInstalled.message).toContain("SKILL.md");
    }
    await expect(readRecommendationState(absent)).resolves.toMatchObject({ skills: [] });

    await saveRecommendationState(project, {
      schemaVersion: "psyclaw/recommendation-state/v1",
      skills: [id],
      mcp: [],
      skillScopes: { [id]: "project" },
    });
    const loaded = await enabledRecommendedSkillPaths(project);
    expect(loaded.paths).toEqual([]);
    expect(loaded.warnings.join("\n")).toContain("SKILL.md");
    expect(loaded.warnings.join("\n")).not.toMatch(/ENOENT/);

    const disabled = await setRecommendedSkillEnabled(project, id, false, "project");
    expect(disabled).toEqual({ ok: true, id, enabled: false });
    await expect(readRecommendationState(project)).resolves.toMatchObject({ skills: [] });
  });

  it("enables a recommended skill whose SKILL.md is present under a non-ASCII project path", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-skill-enable-"));
    const project = join(root, "practical psycology", "练习");
    const id = "literature-review";
    const target = recommendedSkillTarget(project, id, "project");
    await mkdir(target, { recursive: true });
    await writeFile(join(target, "SKILL.md"), "---\nname: literature-review\ndescription: Fixture\n---\n\n# Fixture\n", "utf8");

    const enabled = await setRecommendedSkillEnabled(project, id, true);
    expect(enabled).toEqual({ ok: true, id, enabled: true });
    await expect(readRecommendationState(project)).resolves.toMatchObject({
      skills: [id],
      skillScopes: { [id]: "project" },
    });
    await expect(validateModelInstalledRecommendedSkill(project, id, "project")).resolves.toMatchObject({ path: target });
  });

  it("keeps the recommended catalog academic-facing without author branding", async () => {
    const catalog = await readRecommendedCatalog();
    const blob = JSON.stringify(catalog);
    expect(blob).not.toMatch(/花叔|Huashu/);
    expect(catalog.items.some((item) => item.id === "mac-computer-use")).toBe(true);
    expect(catalog.items.some((item) => item.id === "huashu-weread")).toBe(false);
    expect(catalog.items.some((item) => item.id === "session-handoff")).toBe(false);
    expect(catalog.items.some((item) => item.id === "distill-scholar")).toBe(true);
  });
});
