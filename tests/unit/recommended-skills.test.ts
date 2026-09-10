import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  enabledRecommendedSkillPaths,
  normalizeRecommendedSkillId,
  partitionRecommendationState,
  readRecommendationState,
  readRecommendedCatalog,
  saveRecommendationState,
  userRecommendationStatePath,
  validateInstalledRecommendedSkill,
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
    const path = await managedFixture(root, "session-handoff");
    await saveRecommendationState(root, {
      schemaVersion: "psyclaw/recommendation-state/v1",
      skills: ["session-handoff"],
      mcp: [],
    });
    await expect(validateInstalledRecommendedSkill(root, "session-handoff")).resolves.toMatchObject({ path });
    await expect(enabledRecommendedSkillPaths(root)).resolves.toEqual({ paths: [path], warnings: [] });

    await writeFile(join(path, "SKILL.md"), "tampered\n", "utf8");
    const result = await enabledRecommendedSkillPaths(root);
    expect(result.paths).toEqual([]);
    expect(result.warnings.join("\n")).toMatch(/changed|frontmatter/i);
  });

  it("stores user-scope recommendation desire-state in the agent dir, not cwd/.psyclaw", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-rec-project-"));
    const agentDir = await mkdtemp(join(tmpdir(), "psyclaw-rec-agent-"));
    await saveRecommendationState(root, {
      schemaVersion: "psyclaw/recommendation-state/v1",
      skills: ["session-handoff"],
      mcp: [],
      skillScopes: { "session-handoff": "user" },
    }, { agentDir });
    await expect(readFile(join(root, ".psyclaw", "recommendations.json"), "utf8")).rejects.toMatchObject({ code: "ENOENT" });
    const userFile = JSON.parse(await readFile(userRecommendationStatePath(agentDir), "utf8")) as {
      skills: string[];
      skillScopes?: Record<string, string>;
    };
    expect(userFile.skills).toEqual(["session-handoff"]);
    expect(userFile.skillScopes).toEqual({ "session-handoff": "user" });
    await expect(readRecommendationState(root, { agentDir })).resolves.toMatchObject({
      skills: ["session-handoff"],
      skillScopes: { "session-handoff": "user" },
    });
    const parts = partitionRecommendationState({
      schemaVersion: "psyclaw/recommendation-state/v1",
      skills: ["session-handoff", "academic-reference-matcher"],
      mcp: ["zotero"],
      skillScopes: { "session-handoff": "user", "academic-reference-matcher": "project" },
    });
    expect(parts.user.skills).toEqual(["session-handoff"]);
    expect(parts.project.skills).toEqual(["academic-reference-matcher"]);
    expect(parts.project.mcp).toEqual(["zotero"]);
    expect(parts.user.mcp).toEqual([]);
  });

  it("does not create nested Git metadata in the managed layout", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-recommendations-"));
    const path = await managedFixture(root, "academic-reference-matcher");
    const manifest = JSON.parse(await readFile(join(path, "psyclaw-install.json"), "utf8")) as { source: { ref: string } };
    expect(manifest.source.ref).toMatch(/^[a-f0-9]{40}$/);
    await expect(readFile(join(path, ".git", "HEAD"), "utf8")).rejects.toMatchObject({ code: "ENOENT" });
  });
});
