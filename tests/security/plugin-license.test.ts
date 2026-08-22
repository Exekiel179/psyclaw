import { createHash } from "node:crypto";
import { mkdtemp, mkdir, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { SkillRegistry } from "../../src/skills/registry.js";

async function writeSkill(root: string, dir: string, frontmatter: string): Promise<void> {
  await mkdir(join(root, dir), { recursive: true });
  await writeFile(join(root, dir, "SKILL.md"), `---\n${frontmatter}\n---\nbody\n`, "utf8");
}

async function hostAdmission(file: string) {
  return {
    schemaVersion: "psyclaw/skill-admission/v1" as const,
    contentSha256: createHash("sha256").update(await readFile(file)).digest("hex"),
    licenseSpdx: "MIT",
    licenseEvidenceRef: "LICENSE",
    dependencyEvidenceRef: "manifest.json",
    sbomSha256: "a".repeat(64),
  };
}

describe("supply-chain admission", () => {
  it("keeps an unknown-license plugin discover-only and non-executable", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-license-"));
    await writeSkill(root, "plugin", "name: plugin\ndescription: No license here");
    const registry = new SkillRegistry({ roots: [root] });
    await registry.discover();
    const descriptor = registry.list()[0]!;
    expect(descriptor.licenseStatus).toBe("missing");
    expect(descriptor.approvalStatus).toBe("discover-only");
    expect(descriptor.enabled).toBe(false);
    expect(() => registry.enable("plugin")).toThrow(/explicit approval/);
    await expect(registry.load("plugin")).rejects.toThrow(/not enabled/);
  });

  it("does not treat a declared license as verified without host admission evidence", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-license-"));
    await writeSkill(root, "approved", "name: approved\ndescription: Licensed\nlicense: MIT");
    const file = join(root, "approved", "SKILL.md");
    const registry = new SkillRegistry({ roots: [root], approvals: { approved: { approved: true, sourcePath: file } } });
    await registry.discover();
    const descriptor = registry.list()[0]!;
    expect(descriptor.licenseStatus).toBe("declared");
    expect(descriptor.approvalStatus).toBe("discover-only");
    expect(() => registry.enable("approved")).toThrow(/explicit approval/);

    const admitted = new SkillRegistry({
      roots: [root],
      approvals: { approved: { approved: true, sourcePath: file, admission: await hostAdmission(file) } },
    });
    await admitted.discover();
    expect(admitted.list()[0]?.approvalStatus).toBe("approved");
    expect(admitted.enable("approved").enabled).toBe(true);
  });

  it("treats a blocked-trust plugin as non-executable regardless of license", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-license-"));
    await writeSkill(root, "blocked", "name: blocked\ndescription: Blocked\nlicense: MIT\ntrust: blocked");
    const registry = new SkillRegistry({ roots: [root], approvedIds: ["blocked"] });
    await registry.discover();
    expect(registry.list()[0]?.approvalStatus).toBe("blocked");
    expect(() => registry.enable("blocked")).toThrow(/blocked by trust policy/);
  });

  it("rejects admission evidence bound to a different content hash", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-license-"));
    await writeSkill(root, "stale", "name: stale\ndescription: Stale\nlicense: MIT");
    const file = join(root, "stale", "SKILL.md");
    const admission = await hostAdmission(file);
    const registry = new SkillRegistry({
      roots: [root],
      approvals: { stale: { approved: true, sourcePath: file, admission: { ...admission, contentSha256: "0".repeat(64) } } },
    });
    await registry.discover();
    expect(registry.list()[0]?.approvalStatus).toBe("stale");
    expect(() => registry.enable("stale")).toThrow(/explicit approval/);
  });
});
