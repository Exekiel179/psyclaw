import { mkdir, mkdtemp, readFile, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { discoverAgents } from "../../src/agents/discover.js";
import { importAgentSkills, SkillImportError } from "../../src/agents/import.js";

async function setupHome(): Promise<string> {
  const home = await mkdtemp(join(tmpdir(), "psyclaw-import-home-"));
  await mkdir(join(home, ".claude", "skills", "foo"), { recursive: true });
  await writeFile(join(home, ".claude", "skills", "foo", "SKILL.md"), "# foo\n", "utf8");
  await mkdir(join(home, ".claude", "commands"), { recursive: true });
  await writeFile(join(home, ".claude", "commands", "bar.md"), "# bar\n", "utf8");
  return home;
}

describe("skill import", () => {
  it("copies skills under approval and records provenance hashes", async () => {
    const home = await setupHome();
    const root = await mkdtemp(join(tmpdir(), "psyclaw-import-root-"));
    const [agent] = (await discoverAgents({ homeDir: home })).filter((scan) => scan.id === "claude-code");

    const result = await importAgentSkills({
      root,
      agent: agent!,
      approval: { approved: true, actor: "researcher", reason: "test" },
      now: () => "2026-01-01T00:00:00.000Z",
    });
    expect(result.importedCount).toBe(2);
    expect(result.manifest.schemaVersion).toBe("psyclaw/skill-import/v1");
    const manifest = JSON.parse(await readFile(result.manifestPath, "utf8"));
    expect(manifest.skills).toHaveLength(2);
    for (const skill of manifest.skills) {
      expect(skill.files.length).toBeGreaterThan(0);
      for (const file of skill.files) {
        expect(file.sha256).toMatch(/^[a-f0-9]{64}$/);
        expect(file.sourcePath).toContain(home);
        expect(file.destinationPath).toContain(".psyclaw");
      }
    }
    const copied = await readFile(join(root, ".psyclaw", "imports", "claude-code", "foo", "SKILL.md"), "utf8");
    expect(copied).toBe("# foo\n");
  });

  it("refuses to import without explicit approval", async () => {
    const home = await setupHome();
    const root = await mkdtemp(join(tmpdir(), "psyclaw-import-deny-"));
    const [agent] = (await discoverAgents({ homeDir: home })).filter((scan) => scan.id === "claude-code");
    await expect(importAgentSkills({
      root,
      agent: agent!,
      approval: { approved: false, actor: "policy", reason: "denied" },
    })).rejects.toThrow(/approval/);
  });

  it("skips symlinked skill entries", async () => {
    const home = await mkdtemp(join(tmpdir(), "psyclaw-import-sym-"));
    const outside = await mkdtemp(join(tmpdir(), "psyclaw-import-out-"));
    await writeFile(join(outside, "secret.md"), "do not copy", "utf8");
    await mkdir(join(home, ".claude", "skills"), { recursive: true });
    await symlink(join(outside, "secret.md"), join(home, ".claude", "skills", "link.md"), "file");
    const root = await mkdtemp(join(tmpdir(), "psyclaw-import-root2-"));
    const [agent] = (await discoverAgents({ homeDir: home })).filter((scan) => scan.id === "claude-code");
    const result = await importAgentSkills({
      root,
      agent: agent!,
      approval: { approved: true, actor: "researcher", reason: "test" },
    });
    expect(result.importedCount).toBe(0);
  });

  it("rejects forged agent and skill path segments before writing", async () => {
    const home = await setupHome();
    const root = await mkdtemp(join(tmpdir(), "psyclaw-import-forged-"));
    const [scan] = (await discoverAgents({ homeDir: home })).filter((candidate) => candidate.id === "claude-code");
    await expect(importAgentSkills({
      root,
      agent: { ...scan!, id: ".." },
      approval: { approved: true, actor: "researcher", reason: "test" },
    })).rejects.toMatchObject({ code: "import.path-invalid" } satisfies Partial<SkillImportError>);
    await expect(importAgentSkills({
      root,
      agent: {
        ...scan!,
        skills: [{ ...scan!.skills[0]!, name: "../escape" }],
      },
      approval: { approved: true, actor: "researcher", reason: "test" },
    })).rejects.toMatchObject({ code: "import.path-invalid" } satisfies Partial<SkillImportError>);
  });

  it("rejects a renamed skill that could target an existing file", async () => {
    const home = await setupHome();
    const root = await mkdtemp(join(tmpdir(), "psyclaw-import-name-conflict-"));
    const [scan] = (await discoverAgents({ homeDir: home })).filter((candidate) => candidate.id === "claude-code");
    await expect(importAgentSkills({
      root,
      agent: {
        ...scan!,
        skills: [{ ...scan!.skills.find((skill) => skill.kind === "dir")!, name: "bar" }],
      },
      approval: { approved: true, actor: "researcher", reason: "test" },
    })).rejects.toMatchObject({ code: "import.skill-name-mismatch" } satisfies Partial<SkillImportError>);
  });

  it("blocks sensitive files and suspicious binaries inside an allowlisted directory", async () => {
    const home = await mkdtemp(join(tmpdir(), "psyclaw-import-sensitive-home-"));
    const skillRoot = join(home, ".claude", "skills", "foo");
    await mkdir(join(skillRoot, "references"), { recursive: true });
    await writeFile(join(skillRoot, "SKILL.md"), "# foo\n", "utf8");
    await writeFile(join(skillRoot, "references", ".env"), "TOKEN=do-not-read\n", "utf8");
    const root = await mkdtemp(join(tmpdir(), "psyclaw-import-sensitive-root-"));
    const [scan] = (await discoverAgents({ homeDir: home })).filter((candidate) => candidate.id === "claude-code");
    await expect(importAgentSkills({
      root,
      agent: scan!,
      approval: { approved: true, actor: "researcher", reason: "test" },
    })).rejects.toMatchObject({ code: "import.path-invalid" } satisfies Partial<SkillImportError>);

    await writeFile(join(skillRoot, "references", ".env"), "safe-name-but-not-binary\n", "utf8");
    await mkdir(join(skillRoot, "assets"), { recursive: true });
    await writeFile(join(skillRoot, "assets", "payload.bin"), Buffer.from([0x4d, 0x5a, 0x00, 0x01]));
    const [rescan] = (await discoverAgents({ homeDir: home })).filter((candidate) => candidate.id === "claude-code");
    await expect(importAgentSkills({
      root: await mkdtemp(join(tmpdir(), "psyclaw-import-binary-root-")),
      agent: rescan!,
      approval: { approved: true, actor: "researcher", reason: "test" },
    })).rejects.toMatchObject({ code: "import.suspicious-binary" } satisfies Partial<SkillImportError>);
  });

  it("fails closed when the destination is a symlink", async () => {
    const home = await setupHome();
    const outside = await mkdtemp(join(tmpdir(), "psyclaw-import-target-out-"));
    const root = await mkdtemp(join(tmpdir(), "psyclaw-import-target-root-"));
    await mkdir(join(root, ".psyclaw", "imports"), { recursive: true });
    await symlink(outside, join(root, ".psyclaw", "imports", "claude-code"), "junction");
    const [scan] = (await discoverAgents({ homeDir: home })).filter((candidate) => candidate.id === "claude-code");
    await expect(importAgentSkills({
      root,
      agent: scan!,
      approval: { approved: true, actor: "researcher", reason: "test" },
    })).rejects.toMatchObject({ code: "import.symlink-path" } satisfies Partial<SkillImportError>);
  });

  it("imports when trusted source and project roots have system-style symlink ancestors", async () => {
    const actualHome = await setupHome();
    const actualProjectParent = await mkdtemp(join(tmpdir(), "psyclaw-import-actual-root-"));
    const actualProject = join(actualProjectParent, "project");
    await mkdir(actualProject);
    const links = await mkdtemp(join(tmpdir(), "psyclaw-import-links-"));
    const home = join(links, "home");
    const projectAlias = join(links, "projects");
    const root = join(projectAlias, "project");
    await symlink(actualHome, home, "junction");
    await symlink(actualProjectParent, projectAlias, "junction");
    const [discovered] = (await discoverAgents({ homeDir: actualHome })).filter((candidate) => candidate.id === "claude-code");
    const scan = {
      ...discovered!,
      skillDirs: discovered!.skillDirs.map((path) => path.replace(actualHome, home)),
      skills: discovered!.skills.map((skill) => ({ ...skill, path: skill.path.replace(actualHome, home) })),
    };
    const result = await importAgentSkills({
      root,
      agent: scan,
      approval: { approved: true, actor: "researcher", reason: "test" },
    });
    expect(result.importedCount).toBe(2);
    await expect(readFile(join(actualProject, ".psyclaw", "imports", "claude-code", "foo", "SKILL.md"), "utf8"))
      .resolves.toBe("# foo\n");
  });

  it("replays an identical import without overwriting the manifest", async () => {
    const home = await setupHome();
    const root = await mkdtemp(join(tmpdir(), "psyclaw-import-replay-"));
    const [scan] = (await discoverAgents({ homeDir: home })).filter((candidate) => candidate.id === "claude-code");
    const first = await importAgentSkills({
      root,
      agent: scan!,
      approval: { approved: true, actor: "researcher", reason: "test" },
      now: () => "2026-01-01T00:00:00.000Z",
    });
    const before = await readFile(first.manifestPath, "utf8");
    const second = await importAgentSkills({
      root,
      agent: scan!,
      approval: { approved: true, actor: "researcher", reason: "different timestamp" },
      now: () => "2027-01-01T00:00:00.000Z",
    });
    expect(second.importedCount).toBe(0);
    expect(second.receipt.reasonCode).toBe("import.already-recorded");
    expect(await readFile(first.manifestPath, "utf8")).toBe(before);
  });
});
