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
  it("reports a missing license as metadata while enablement needs no ceremony", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-license-"));
    await writeSkill(root, "plugin", "name: plugin\ndescription: No license here");
    const registry = new SkillRegistry({ roots: [root] });
    await registry.discover();
    const descriptor = registry.list()[0]!;
    // License metadata stays advisory: it is derived from the frontmatter and
    // is never trusted as host-verified. Enablement is the explicit action;
    // only an explicit host denial is a runtime gate.
    expect(descriptor.licenseStatus).toBe("missing");
    expect(descriptor.approvalStatus).toBe("approved");
    expect(descriptor.enabled).toBe(false);
    expect(registry.enable("plugin").enabled).toBe(true);
    await expect(registry.load("plugin")).resolves.toMatchObject({ id: "plugin" });
  });

  it("never treats a declared license as host-verified, with or without admission evidence", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-license-"));
    await writeSkill(root, "approved", "name: approved\ndescription: Licensed\nlicense: MIT");
    const file = join(root, "approved", "SKILL.md");
    // A declared license can only ever read back as `declared`; no frontmatter
    // or admission payload may flip it to `verified`.
    const registry = new SkillRegistry({ roots: [root], approvals: { approved: { approved: true, sourcePath: file } } });
    await registry.discover();
    expect(registry.list()[0]?.licenseStatus).toBe("declared");
    expect(registry.list()[0]?.approvalStatus).toBe("approved");
    expect(registry.enable("approved").enabled).toBe(true);

    const admitted = new SkillRegistry({
      roots: [root],
      approvals: { approved: { approved: true, sourcePath: file, admission: await hostAdmission(file) } },
    });
    await admitted.discover();
    expect(admitted.list()[0]?.licenseStatus).toBe("declared");
    expect(admitted.list()[0]?.approvalStatus).toBe("approved");
    expect(admitted.enable("approved").enabled).toBe(true);
  });

  it("blocks a host-denied plugin regardless of license and surfaces blocked trust", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-license-"));
    await writeSkill(root, "blocked", "name: blocked\ndescription: Blocked\nlicense: MIT\ntrust: blocked");
    const registry = new SkillRegistry({ roots: [root], approvalMap: { blocked: { approved: false } } });
    await registry.discover();
    expect(registry.list()[0]?.trust).toBe("blocked");
    expect(registry.list()[0]?.approvalStatus).toBe("blocked");
    expect(() => registry.enable("blocked")).toThrow(/explicitly disabled/);
    await expect(registry.load("blocked")).rejects.toThrow(/not enabled/);
  });

  it("flags a content pin that no longer matches as stale instead of silently granting", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-license-"));
    await writeSkill(root, "stale", "name: stale\ndescription: Stale\nlicense: MIT");
    const file = join(root, "stale", "SKILL.md");
    await hostAdmission(file);
    const pinned = new SkillRegistry({
      roots: [root],
      approvals: { stale: { approved: true, sourcePath: file, sha256: "0".repeat(64) } },
    });
    await pinned.discover();
    // A pin whose hash no longer matches the discovered content reads back as
    // `stale`, never as a clean approval.
    expect(pinned.list()[0]?.licenseStatus).toBe("declared");
    expect(pinned.list()[0]?.approvalStatus).toBe("stale");
  });
});
