import { createHash } from "node:crypto";
import { mkdtemp, mkdir, readFile, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { SkillRegistry } from "../../src/skills/registry.js";

async function tempRoot(): Promise<string> {
  return mkdtemp(join(tmpdir(), "psyclaw-skills-"));
}

async function writeSkill(root: string, directory: string, frontmatter: string, body = "# body\n"): Promise<string> {
  const folder = join(root, directory);
  await mkdir(folder, { recursive: true });
  const file = join(folder, "SKILL.md");
  await writeFile(file, `---\n${frontmatter}\n---\n${body}`, "utf8");
  return file;
}

async function hostApproval(sourcePath: string) {
  const contentSha256 = createHash("sha256").update(await readFile(sourcePath)).digest("hex");
  return {
    approved: true as const,
    sourcePath,
    admission: {
      schemaVersion: "psyclaw/skill-admission/v1" as const,
      contentSha256,
      licenseSpdx: "MIT",
      licenseEvidenceRef: "LICENSE",
      dependencyEvidenceRef: "manifest.json",
      sbomSha256: "a".repeat(64),
    },
  };
}

describe("SkillRegistry", () => {
  it("discovers metadata without exposing the Markdown body and loads it on demand", async () => {
    const root = await tempRoot();
    const file = await writeSkill(root, "brief", "name: research-brief\ndescription: Make a brief\nlicense: MIT\ndependencies: []", "private body\n");
    const registry = new SkillRegistry({ roots: [root], approvals: { "research-brief": await hostApproval(file) } });
    const report = await registry.discover();
    expect(report.diagnostics).toEqual([]);
    expect(report.skills).toHaveLength(1);
    const descriptor = report.skills[0]!;
    expect(descriptor.id).toBe("research-brief");
    expect(descriptor.sourcePath).toBe(file);
    expect(descriptor.resolvedPath).toBe(file);
    expect(descriptor.sha256).toMatch(/^[a-f0-9]{64}$/);
    expect(descriptor.licenseStatus).toBe("declared");
    expect(descriptor.dependencyStatus).toBe("ready");
    expect(descriptor.approvalStatus).toBe("approved");
    expect(descriptor.enabled).toBe(false);
    expect("body" in descriptor).toBe(false);
    expect(() => registry.enable("research-brief")).not.toThrow();
    const loaded = await registry.load("research-brief");
    expect(loaded.body).toContain("private body");
    expect(loaded.body).not.toContain("name: research-brief");
  });

  it("reports duplicate ids and refuses ambiguous load or enable", async () => {
    const first = await tempRoot();
    const second = await tempRoot();
    await writeSkill(first, "one", "name: same\ndescription: First");
    await writeSkill(second, "two", "name: same\ndescription: Second");
    const registry = new SkillRegistry([first, second]);
    const report = await registry.discover();
    expect(report.skills).toHaveLength(2);
    expect(report.skills.every((skill) => skill.conflicted)).toBe(true);
    expect(report.diagnostics.some((item) => item.code === "duplicate-id")).toBe(true);
    await expect(registry.load("same")).rejects.toThrow("ambiguous");
    expect(() => registry.enable("same")).toThrow("ambiguous");
  });

  it("supports in-memory enable/disable state and search ranking", async () => {
    const root = await tempRoot();
    await writeSkill(root, "one", "name: alpha\ndescription: Qualitative coding", "alpha body");
    const betaFile = await writeSkill(root, "two", "name: beta\ndescription: Survey intake\ntags: [survey]", "beta body");
    const registry = new SkillRegistry({ roots: [root], approvals: { beta: await hostApproval(betaFile) } });
    await registry.discover();
    expect(registry.list({ enabledOnly: true })).toHaveLength(0);
    expect(registry.search("survey")[0]?.id).toBe("beta");
    expect(registry.enable("beta").enabled).toBe(true);
    expect(registry.list({ enabledOnly: true }).map((skill) => skill.id)).toEqual(["beta"]);
    expect(registry.disable("beta").enabled).toBe(false);
  });

  it("rejects symlinked roots and skill paths, and root traversal", async () => {
    const root = await tempRoot();
    const outside = await tempRoot();
    await writeSkill(outside, "outside", "name: outside\ndescription: Should not load");
    const link = join(root, "linked");
    await symlink(outside, link, "junction");
    const registry = new SkillRegistry([link]);
    const report = await registry.discover();
    expect(report.skills).toEqual([]);
    expect(report.diagnostics.some((item) => item.code === "root-symlink")).toBe(true);
    // Keep the traversal segment in the caller input; `path.join` normalizes
    // it away before the registry can apply its boundary check.
    const traversal = new SkillRegistry([`${root}\\..`]);
    const traversalReport = await traversal.discover();
    expect(traversalReport.skills).toEqual([]);
    expect(traversalReport.diagnostics.some((item) => item.code === "path-traversal")).toBe(true);
  });

  it("detects a file mutation between discovery and load", async () => {
    const root = await tempRoot();
    const file = await writeSkill(root, "mutable", "name: mutable\ndescription: Mutable");
    const registry = new SkillRegistry({ roots: [root], approvals: { mutable: await hostApproval(file) } });
    await registry.discover();
    registry.enable("mutable");
    await writeFile(file, "---\nname: mutable\ndescription: Changed\n---\nchanged\n", "utf8");
    await expect(registry.load("mutable")).rejects.toThrow("changed since discovery");
  });

  it("rejects blocked skills from being enabled", async () => {
    const root = await tempRoot();
    await writeSkill(root, "blocked", "name: blocked\ndescription: Blocked\ntrust: blocked");
    const registry = new SkillRegistry({ roots: [root], approvedIds: ["blocked"] });
    await registry.discover();
    expect(() => registry.enable("blocked")).toThrow("blocked by trust policy");
  });

  it("ignores frontmatter enabled flags and self-reported trust", async () => {
    const root = await tempRoot();
    await writeSkill(root, "default", "name: default\ndescription: Default\nenabledByDefault: true\ntrust: trusted");
    const registry = new SkillRegistry({ roots: [root], enableByDefault: true });
    await registry.discover();
    expect(registry.list({ enabledOnly: true })).toEqual([]);
    expect(() => registry.enable("default")).toThrow("explicit approval");
    await expect(registry.load("default")).rejects.toThrow("not enabled");
  });

  it("requires explicit approval for unknown, untrusted, and self-reported trusted skills", async () => {
    const root = await tempRoot();
    await writeSkill(root, "unknown", "name: unknown\ndescription: Unknown");
    await writeSkill(root, "untrusted", "name: untrusted\ndescription: Untrusted\ntrust: untrusted");
    await writeSkill(root, "claimed", "name: claimed\ndescription: Claimed\ntrust: trusted");
    const registry = new SkillRegistry([root]);
    await registry.discover();
    for (const id of ["unknown", "untrusted", "claimed"]) {
      expect(registry.list().find((skill) => skill.id === id)?.approvalStatus).toBe("discover-only");
      expect(() => registry.enable(id)).toThrow("explicit approval");
      await expect(registry.load(id)).rejects.toThrow("not enabled");
    }
  });

  it("supports a richer approval map with content and path pins", async () => {
    const root = await tempRoot();
    const file = await writeSkill(root, "pinned", "name: pinned\ndescription: Pinned");
    const registry = new SkillRegistry({
      roots: [root],
      approval: new Map([["pinned", await hostApproval(file)]]),
    });
    await registry.discover();
    expect(registry.list()[0]?.approvalStatus).toBe("approved");
    registry.enable("pinned");
    await expect(registry.load("pinned")).resolves.toMatchObject({ id: "pinned" });

    const stale = new SkillRegistry({
      roots: [root],
      approvals: { pinned: { ...(await hostApproval(file)), sha256: "0".repeat(64) } },
    });
    await stale.discover();
    expect(stale.list()[0]?.approvalStatus).toBe("stale");
    expect(() => stale.enable("pinned")).toThrow("explicit approval");
  });

  it("lets explicit denies override the approved id shorthand", async () => {
    const root = await tempRoot();
    await writeSkill(root, "denied", "name: denied\ndescription: Denied");
    const registry = new SkillRegistry({
      roots: [root],
      approvedIds: ["denied"],
      approvalMap: { denied: { approved: false } },
    });
    await registry.discover();
    expect(registry.list()[0]?.approvalStatus).toBe("blocked");
    expect(() => registry.enable("denied")).toThrow("explicit approval");
  });

  it("fails closed when an approved file is replaced with a symlink", async () => {
    const root = await tempRoot();
    const outside = await tempRoot();
    const file = await writeSkill(root, "swap", "name: swap\ndescription: Swap", "inside\n");
    const outsideFile = await writeSkill(outside, "outside", "name: swap\ndescription: Outside", "outside\n");
    const registry = new SkillRegistry({ roots: [root], approvals: { swap: await hostApproval(file) } });
    await registry.discover();
    registry.enable("swap");
    await writeFile(file, await readFile(file, "utf8"), "utf8");
    // Replacing the path is intentionally attempted only after discovery;
    // load must reject the symlink rather than follow it outside the root.
    const { rm } = await import("node:fs/promises");
    await rm(file);
    await symlink(outsideFile, file, "file");
    await expect(registry.load("swap")).rejects.toThrow(/symlink|changed/i);
  });

  it("does not grant execution for a no-pin approvedIds shorthand", async () => {
    const root = await tempRoot();
    await writeSkill(root, "short", "name: short\ndescription: Short\nlicense: MIT");
    const registry = new SkillRegistry({ roots: [root], approvedIds: ["short"] });
    await registry.discover();
    const descriptor = registry.list()[0]!;
    expect(descriptor.licenseStatus).toBe("declared");
    expect(descriptor.approvalStatus).toBe("discover-only");
    expect(() => registry.enable("short")).toThrow("explicit approval");
  });

  it("downgrades self-reported license/dependency/trust status to host-decided values", async () => {
    const root = await tempRoot();
    await writeSkill(root, "self", [
      "name: self",
      "description: Self",
      "license: MIT",
      "licenseStatus: verified",
      "trust: trusted",
      "dependencies: [missing-pkg]",
      "dependencyStatus: ready",
    ].join("\n"));
    const registry = new SkillRegistry({ roots: [root] });
    await registry.discover();
    const descriptor = registry.list()[0]!;
    expect(descriptor.licenseStatus).toBe("declared");
    expect(descriptor.dependencyStatus).toBe("declared");
    expect(descriptor.trust).toBe("unknown");
    expect(descriptor.approvalStatus).toBe("discover-only");
  });
});
