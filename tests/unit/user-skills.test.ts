import { describe, expect, it } from "vitest";
import { lstat, mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { isAbsolute, join } from "node:path";
import {
  enabledLocalSkillPaths,
  enabledLocalPromptPaths,
  installLocalSkill,
  localSkillRoots,
  readUserSkillState,
  scanLocalSkills,
  setLocalSkillEnabled,
  setLocalSkillsEnabled,
  skillNamesInPaths,
  userSkillId,
} from "../../src/skills/user-skills.js";

describe("user-installed Skill discovery", () => {
  it("expands discovery roots to the documented host agent directories", () => {
    const roots = localSkillRoots("/tmp/project");
    const joined = roots.join("\n").replaceAll("\\", "/");
    expect(joined).toContain(".claude/skills");
    expect(joined).toContain(".codex/skills");
    expect(joined).toContain(".agents/skills");
    expect(joined).toContain(".opencode/skills");
    expect(joined).toContain(".cc-switch/skills");
    expect(joined).toContain(".psyclaw/skills");
    expect(joined).toContain("/tmp/project/skills");
  });

  it("scans user skill directories and toggles them individually", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-user-skills-"));
    // Project-local `.claude/skills` directory with one skill.
    const skillsDir = join(root, ".claude", "skills");
    await mkdir(join(skillsDir, "my-analyzer"), { recursive: true });
    await writeFile(join(skillsDir, "my-analyzer", "SKILL.md"), "---\nname: my-analyzer\ndescription: Fixture\n---\n", "utf8");
    // Another skill in the project `skills/` root.
    await mkdir(join(root, "skills", "plotter"), { recursive: true });
    await writeFile(join(root, "skills", "plotter", "SKILL.md"), "---\nname: plotter\ndescription: Plot fixture\n---\n", "utf8");

    const skills = await scanLocalSkills(root, { includeManaged: false });
    const projectSkills = skills.filter((skill) => skill.path.startsWith(root));
    expect(projectSkills.map((skill) => skill.name).sort()).toEqual(["my-analyzer", "plotter"]);

    // Disabling one skill removes it from the load paths but keeps the other.
    await setLocalSkillEnabled(root, "my-analyzer", false);
    const loaded = await enabledLocalSkillPaths(root);
    expect(loaded.paths.some((path) => path.endsWith(join("my-analyzer")))).toBe(false);
    expect(loaded.paths.some((path) => path.endsWith(join("plotter")))).toBe(true);
    expect(loaded.warnings.join("\n")).toContain("my-analyzer");

    // Batch re-enable clears the disabled list.
    await setLocalSkillsEnabled(root, ["my-analyzer"], true);
    const state = await readUserSkillState(root);
    expect(state.disabled).toEqual([]);
  });

  it("derives management ids without colliding with recommended ids", () => {
    expect(userSkillId("nature-reader")).toBe("local:nature-reader");
  });

  it("expands configured paths and keeps one same-name Skill by stable precedence", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-user-skills-priority-"));
    const preferred = join(root, ".psyclaw", "skills", "shared");
    const duplicate = join(root, ".claude", "skills", "shared-copy");
    await mkdir(preferred, { recursive: true });
    await mkdir(duplicate, { recursive: true });
    await writeFile(join(preferred, "SKILL.md"), "---\nname: shared\ndescription: Preferred\n---\n", "utf8");
    await writeFile(join(duplicate, "SKILL.md"), "---\nname: shared\ndescription: Duplicate\n---\n", "utf8");

    const previous = process.env.PSYCLAW_SKILLS_PATH;
    process.env.PSYCLAW_SKILLS_PATH = "~/.agents/skills";
    try {
      expect(localSkillRoots(root).every(isAbsolute)).toBe(true);
      const scanned = (await scanLocalSkills(root, { includeManaged: false }))
        .find((skill) => skill.name === "shared");
      expect(scanned?.path).toBe(preferred);
      expect(scanned?.duplicatePaths).toContain(duplicate);

      const loaded = await enabledLocalSkillPaths(root);
      expect(loaded.paths.filter((path) => path === preferred || path === duplicate)).toEqual([preferred]);
      expect(loaded.paths).not.toContain(join(root, ".claude", "commands"));
    } finally {
      if (previous === undefined) delete process.env.PSYCLAW_SKILLS_PATH;
      else process.env.PSYCLAW_SKILLS_PATH = previous;
    }
  }, 15_000);

  it("does not reload a local Skill whose name is already provided", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-user-skills-excluded-"));
    const skill = join(root, "skills", "research-intake");
    await mkdir(skill, { recursive: true });
    await writeFile(join(skill, "SKILL.md"), "---\nname: research-intake\ndescription: Duplicate core\n---\n", "utf8");

    const loaded = await enabledLocalSkillPaths(root, { excludedNames: ["research-intake"] });
    expect(loaded.paths).not.toContain(skill);
  });

  it("loads Claude commands as deduplicated prompts instead of a commands Skill", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-user-prompts-"));
    const commands = join(root, ".claude", "commands");
    await mkdir(commands, { recursive: true });
    await writeFile(join(commands, "ars-full.md"), "Run ARS\n", "utf8");

    expect(await enabledLocalPromptPaths(root)).toContain(join(commands, "ars-full.md"));
    expect((await enabledLocalSkillPaths(root)).paths).not.toContain(commands);
  });

  it("reads selected Skill names without loading bodies", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-skill-names-"));
    const skill = join(root, "collection", "reader");
    await mkdir(skill, { recursive: true });
    await writeFile(join(skill, "SKILL.md"), "---\nname: reader\ndescription: Reader\n---\nBody\n", "utf8");
    expect(await skillNamesInPaths([join(root, "collection")])).toEqual(["reader"]);
  });

  it("installs a local Skill directory without copying dependency folders", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-local-skill-install-"));
    const source = join(root, "source");
    const targetRoot = join(root, "installed");
    await mkdir(join(source, "node_modules", "ignored"), { recursive: true });
    await writeFile(join(source, "SKILL.md"), "---\nname: local-reader\ndescription: Local reader\n---\nBody\n", "utf8");
    await writeFile(join(source, "reference.md"), "Reference\n", "utf8");

    const installed = await installLocalSkill(source, root, { targetRoot });
    expect(installed.target).toBe(join(targetRoot, "local-reader"));
    await expect(readFile(join(installed.target, "SKILL.md"), "utf8")).resolves.toContain("local-reader");
    await expect(lstat(join(installed.target, "node_modules"))).rejects.toMatchObject({ code: "ENOENT" });
    await expect(installLocalSkill(source, root, { targetRoot })).rejects.toThrow("already installed");
  });
});
