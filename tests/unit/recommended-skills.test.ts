import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { ExpectedUserError } from "../../src/observability/expected.js";
import {
  enabledRecommendedSkillPaths,
  normalizeRecommendedSkillId,
  projectRecommendationStatePath,
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
  it("does not offer the system-integrated ARS as a recommended download", async () => {
    const catalog = await readRecommendedCatalog();
    const ars = catalog.plugins.find((plugin) => plugin.id === "academic-research-suite-plugin");
    expect(ars).toBeUndefined();
  });

  it("migrates the old MarkItDown id in recommendation state", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-recommendations-"));
    const agentDir = await mkdtemp(join(tmpdir(), "psyclaw-agent-reco-"));
    await mkdir(join(root, ".psyclaw"), { recursive: true });
    await writeFile(join(root, ".psyclaw", "recommendations.json"), JSON.stringify({
      schemaVersion: "psyclaw/recommendation-state/v1",
      skills: ["markitdown-pro"],
      mcp: [],
    }), "utf8");
    expect(normalizeRecommendedSkillId("markitdown-pro")).toBe("markitdown-bilibili");
    await expect(readRecommendationState(root, { agentDir })).resolves.toMatchObject({ skills: ["markitdown-bilibili"] });
  });

  it("loads only enabled installs whose source, license, and content hashes validate", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-recommendations-"));
    const agentDir = await mkdtemp(join(tmpdir(), "psyclaw-agent-reco-"));
    const path = await managedFixture(root, "academic-reference-matcher");
    await saveRecommendationState(root, {
      schemaVersion: "psyclaw/recommendation-state/v1",
      skills: ["academic-reference-matcher"],
      mcp: [],
    }, { agentDir });
    await expect(validateInstalledRecommendedSkill(root, "academic-reference-matcher")).resolves.toMatchObject({ path });
    await expect(enabledRecommendedSkillPaths(root, { agentDir })).resolves.toEqual({ paths: [path], warnings: [] });

    await writeFile(join(path, "SKILL.md"), "tampered\n", "utf8");
    const result = await enabledRecommendedSkillPaths(root, { agentDir });
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

  it("keeps the recommended catalog academic-facing without author branding", async () => {
    const catalog = await readRecommendedCatalog();
    const blob = JSON.stringify(catalog);
    expect(blob).not.toMatch(/花叔|Huashu/);
    expect(catalog.items.some((item) => item.id === "mac-computer-use")).toBe(true);
    expect(catalog.items.some((item) => item.id === "huashu-weread")).toBe(false);
    expect(catalog.items.some((item) => item.id === "session-handoff")).toBe(false);
    expect(catalog.items.some((item) => item.id === "distill-scholar")).toBe(true);
  });

  it("stores user-scope recommendation state in the agent dir even when cwd is System32", async () => {
    const agentDir = await mkdtemp(join(tmpdir(), "psyclaw-agent-reco-"));
    const protectedCwd = "C:\\Windows\\System32";
    await saveRecommendationState(protectedCwd, {
      schemaVersion: "psyclaw/recommendation-state/v1",
      skills: ["scientific-visualization"],
      mcp: [],
      skillScopes: { "scientific-visualization": "user" },
    }, { agentDir });
    expect(existsSync(userRecommendationStatePath(agentDir))).toBe(true);
    expect(existsSync(resolve(protectedCwd, ".psyclaw"))).toBe(false);
    const state = await readRecommendationState(protectedCwd, { agentDir });
    expect(state.skills).toEqual(["scientific-visualization"]);
    expect(state.skillScopes?.["scientific-visualization"]).toBe("user");
  });

  it("does not mkdir project recommendation state under System32", async () => {
    const agentDir = await mkdtemp(join(tmpdir(), "psyclaw-agent-reco-"));
    const protectedCwd = "C:\\Windows\\System32";
    await expect(saveRecommendationState(protectedCwd, {
      schemaVersion: "psyclaw/recommendation-state/v1",
      skills: ["academic-reference-matcher"],
      mcp: [],
      skillScopes: { "academic-reference-matcher": "project" },
    }, { agentDir })).rejects.toSatisfy((error: unknown) => {
      return error instanceof ExpectedUserError
        && error.message.includes("无法写入")
        && (error as NodeJS.ErrnoException).code === "EPERM";
    });
    expect(existsSync(resolve(protectedCwd, ".psyclaw"))).toBe(false);
    expect(existsSync(projectRecommendationStatePath(protectedCwd))).toBe(false);
  });

  it("merges project and user recommendation state files", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-reco-merge-"));
    const agentDir = await mkdtemp(join(tmpdir(), "psyclaw-agent-merge-"));
    await saveRecommendationState(root, {
      schemaVersion: "psyclaw/recommendation-state/v1",
      skills: ["academic-reference-matcher", "mac-computer-use"],
      mcp: ["zotero"],
      skillScopes: {
        "academic-reference-matcher": "project",
        "mac-computer-use": "user",
      },
    }, { agentDir });
    const merged = await readRecommendationState(root, { agentDir });
    expect(merged.skills).toEqual(["academic-reference-matcher", "mac-computer-use"]);
    expect(merged.mcp).toEqual(["zotero"]);
    expect(merged.skillScopes).toMatchObject({
      "academic-reference-matcher": "project",
      "mac-computer-use": "user",
    });
    const projectFile = JSON.parse(await readFile(projectRecommendationStatePath(root), "utf8")) as {
      skills: string[];
      mcp: string[];
    };
    const userFile = JSON.parse(await readFile(userRecommendationStatePath(agentDir), "utf8")) as { skills: string[] };
    expect(projectFile.skills).toEqual(["academic-reference-matcher"]);
    expect(projectFile.mcp).toEqual(["zotero"]);
    expect(userFile.skills).toEqual(["mac-computer-use"]);
  });
});
