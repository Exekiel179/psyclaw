import { lstat, mkdir, mkdtemp, readFile, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { createHash } from "node:crypto";
import { KNOWN_AGENTS } from "../../src/agents/catalog.js";
import { asToolReceipt } from "../../src/core/schemas.js";
import {
  InMemoryInstallLedger,
  FileInstallLedger,
  installSkillPackage,
  planAgentInstall,
  planSkillInstall,
  runInstall,
  verifyFileSha256,
  type InstallPlan,
} from "../../src/install/installer.js";

const clock = () => "2026-01-01T00:00:00.000Z";
const approved = { approved: true, actor: "researcher", reason: "fixture" };
const denied = { approved: false, actor: "policy", reason: "denied" };
const sha = (text: string): string => createHash("sha256").update(text).digest("hex");

async function skillPlan(root: string, content: string, overrides: Partial<Parameters<typeof planSkillInstall>[0]> = {}): Promise<InstallPlan> {
  const dependencies = overrides.dependencies ?? [{ name: "fixture-dependency", version: "1.0.0", license: "MIT" }];
  const sbomText = JSON.stringify({
    bomFormat: "CycloneDX",
    specVersion: "1.5",
    components: dependencies.map((dependency) => ({ name: dependency.name, version: dependency.version })),
  });
  return planSkillInstall({
    targetId: "nature-reader",
    sourceRef: "https://example.test/nature-reader",
    ref: "v1.2.3",
    command: "download",
    target: join(root, "skills", "nature-reader"),
    stagingDir: join(root, "staging", "nature-reader"),
    expectedSha256: sha(content),
    license: "MIT",
    dependencies,
    sbom: { format: "CycloneDX", specVersion: "1.5", path: "sbom.cdx.json", sha256: sha(sbomText) },
    ...overrides,
  });
}

async function writeStaging(plan: InstallPlan, content: string): Promise<void> {
  await mkdir(plan.stagingDir!, { recursive: true });
  await writeFile(join(plan.stagingDir!, plan.contentFile ?? "SKILL.md"), content, "utf8");
  if (plan.sbom !== undefined) {
    await writeFile(join(plan.stagingDir!, plan.sbom.path), JSON.stringify({
      bomFormat: "CycloneDX",
      specVersion: "1.5",
      components: (plan.dependencies ?? []).map((dependency) => ({ name: dependency.name, version: dependency.version })),
    }), "utf8");
  }
}

describe("installer security loop", () => {
  it("stages, verifies, then activates on success", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-install-"));
    const plan = await skillPlan(root, "correct content");
    let calls = 0;
    const runner = async () => {
      calls += 1;
      await writeStaging(plan, "correct content");
      return { exitCode: 0 };
    };
    const result = await installSkillPackage(plan, approved, runner, { ledger: new InMemoryInstallLedger(), now: clock });
    expect(result.status).toBe("installed");
    expect(result.verified).toBe(true);
    expect(result.receipt.ok).toBe(true);
    expect(calls).toBe(1);
    expect(await readFile(join(plan.target!, "SKILL.md"), "utf8")).toBe("correct content");
    // staging is consumed and no longer present
    await expect(import("node:fs/promises").then(({ lstat }) => lstat(plan.stagingDir!))).rejects.toMatchObject({ code: "ENOENT" });
  });

  it("blocks a hash mismatch without activating or overwriting", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-install-"));
    const plan = await skillPlan(root, "expected");
    const runner = async () => {
      await writeStaging(plan, "wrong content");
      return { exitCode: 0 };
    };
    const result = await installSkillPackage(plan, approved, runner, { now: clock });
    expect(result.status).toBe("blocked");
    expect(result.receipt.reasonCode).toBe("install.hash-mismatch");
    expect(result.verificationReason).toMatch(/mismatch/i);
    await expect(readFile(join(plan.target!, "SKILL.md"), "utf8")).rejects.toMatchObject({ code: "ENOENT" });
  });

  it("blocks a missing or malformed content pin before running", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-install-"));
    let calls = 0;
    const runner = async () => {
      calls += 1;
      return { exitCode: 0 };
    };

    const missing = await skillPlan(root, "x", { expectedSha256: undefined });
    const missingResult = await installSkillPackage(missing, approved, runner, { now: clock });
    expect(missingResult.status).toBe("blocked");
    expect(missingResult.receipt.reasonCode).toBe("install.missing-pin");

    const malformed = await skillPlan(root, "x", { expectedSha256: "not-a-sha" });
    const malformedResult = await installSkillPackage(malformed, approved, runner, { now: clock });
    expect(malformedResult.status).toBe("blocked");
    expect(malformedResult.receipt.reasonCode).toBe("install.malformed-pin");
    expect(calls).toBe(0);
  });

  it("blocks an unverified global agent command before it can run", async () => {
    const claude = KNOWN_AGENTS.find((agent) => agent.id === "claude-code")!;
    let calls = 0;
    const unpinnedReceipt = await runInstall(
      planAgentInstall(claude),
      approved,
      async () => { calls += 1; throw new Error("secret boom details"); },
      { now: clock },
    );
    expect(unpinnedReceipt.reasonCode).toBe("install.missing-pin");
    expect(calls).toBe(0);

    const pinnedPlan = { ...planAgentInstall(claude), expectedSha256: "a".repeat(64) };
    const receipt = await runInstall(
      pinnedPlan,
      approved,
      async () => { throw new Error("secret boom details"); },
      { now: clock },
    );
    expect(receipt.ok).toBe(false);
    expect(receipt.reasonCode).toBe("install.agent-staging-required");
    expect(calls).toBe(0);
    expect(() => asToolReceipt(receipt)).not.toThrow();
  });

  it("executes an identical install identity only once", async () => {
    const claude = KNOWN_AGENTS.find((agent) => agent.id === "claude-code")!;
    const ledger = new InMemoryInstallLedger();
    let calls = 0;
    const runner = async () => {
      calls += 1;
      return { exitCode: 0 };
    };
    const plan = { ...planAgentInstall(claude), kind: "package" as const, target: "target", stagingDir: "staging", expectedSha256: "a".repeat(64) };
    const first = await runInstall(plan, approved, runner, { now: clock, ledger });
    const second = await runInstall(plan, approved, runner, { now: clock, ledger });
    expect(first.ok).toBe(true);
    expect(second.ok).toBe(true);
    expect(second.reasonCode).toBe("install.already-recorded");
    expect(calls).toBe(1);
  });

  it("never overwrites an existing target with different content", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-install-"));
    const plan = await skillPlan(root, "new content");
    await mkdir(plan.target!, { recursive: true });
    await writeFile(join(plan.target!, "SKILL.md"), "old content", "utf8");
    const runner = async () => {
      await writeStaging(plan, "new content");
      return { exitCode: 0 };
    };
    const result = await installSkillPackage(plan, approved, runner, { now: clock });
    expect(result.status).toBe("blocked");
    expect(result.receipt.reasonCode).toBe("install.target-conflict");
    expect(await readFile(join(plan.target!, "SKILL.md"), "utf8")).toBe("old content");
  });

  it("carries the pinned ref in the plan", () => {
    const claude = KNOWN_AGENTS.find((agent) => agent.id === "claude-code")!;
    const plan = planAgentInstall(claude);
    expect(plan.ref).toBe("2.1.232");
  });

  it("fails closed for a denied agent install", async () => {
    const claude = KNOWN_AGENTS.find((agent) => agent.id === "claude-code")!;
    const receipt = await runInstall(planAgentInstall(claude), denied, async () => ({ exitCode: 0 }), { now: clock });
    expect(receipt.ok).toBe(false);
    expect(receipt.reasonCode).toBe("install.approval-required");
  });

  it("does not execute a package runner without a content pin", async () => {
    const plan = planSkillInstall({
      targetId: "unpinned-skill",
      sourceRef: "https://example.test/unpinned-skill",
      ref: "v1.0.0",
      command: "download",
      target: "target",
      stagingDir: "staging",
      license: "MIT",
      dependencies: [],
      sbom: { format: "CycloneDX", specVersion: "1.5", path: "sbom.cdx.json", sha256: "a".repeat(64) },
    });
    let calls = 0;
    const receipt = await runInstall(plan, approved, async () => {
      calls += 1;
      return { exitCode: 0 };
    }, { now: clock });
    expect(receipt.reasonCode).toBe("install.missing-pin");
    expect(calls).toBe(0);
  });

  it("verifies a downloaded file against an expected hash", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-install-"));
    const file = join(root, "skill.md");
    await writeFile(file, "content", "utf8");
    await expect(verifyFileSha256(file, sha("content"))).resolves.toEqual({ ok: true });
    await expect(verifyFileSha256(file, "0".repeat(64))).resolves.toMatchObject({ ok: false });
    await expect(verifyFileSha256(file, "not-a-hash")).resolves.toMatchObject({ ok: false });
  });

  it("persists the idempotency reservation across ledger instances", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-install-ledger-"));
    const plan = { ...planAgentInstall(KNOWN_AGENTS.find((agent) => agent.id === "claude-code")!), kind: "package" as const, target: "target", stagingDir: "staging", projectRoot: root, expectedSha256: "a".repeat(64) };
    const firstLedger = new FileInstallLedger(root);
    const secondLedger = new FileInstallLedger(root);
    let calls = 0;
    const runner = async () => {
      calls += 1;
      await new Promise((resolve) => setTimeout(resolve, 15));
      return { exitCode: 0 };
    };
    const [first, second] = await Promise.all([
      runInstall(plan, approved, runner, { now: clock, ledger: firstLedger }),
      runInstall(plan, approved, runner, { now: clock, ledger: secondLedger }),
    ]);
    expect(first.ok).toBe(true);
    expect(second.ok).toBe(true);
    expect([first.reasonCode, second.reasonCode]).toContain("install.already-recorded");
    expect(calls).toBe(1);
    const third = await runInstall(plan, approved, runner, { now: clock, ledger: new FileInstallLedger(root) });
    expect(third.reasonCode).toBe("install.already-recorded");
    await expect(lstat(join(root, ".psyclaw", "installs.jsonl"))).resolves.toBeDefined();
  });

  it("blocks unsafe project paths before creating staging or invoking the runner", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-install-path-"));
    const plan = await skillPlan(root, "content", {
      projectRoot: root,
      stagingDir: join(root, "..", "outside-staging"),
    });
    let calls = 0;
    const result = await installSkillPackage(plan, approved, async () => {
      calls += 1;
      return { exitCode: 0 };
    }, { now: clock });
    expect(result.receipt.reasonCode).toBe("install.path-invalid");
    expect(calls).toBe(0);
  });

  it("installs beneath a trusted root with a system-style symlink ancestor", async () => {
    const actualParent = await mkdtemp(join(tmpdir(), "psyclaw-install-actual-"));
    const actualRoot = join(actualParent, "project");
    await mkdir(actualRoot);
    const links = await mkdtemp(join(tmpdir(), "psyclaw-install-links-"));
    const alias = join(links, "projects");
    const root = join(alias, "project");
    await symlink(actualParent, alias, "junction");
    const plan = await skillPlan(root, "correct content", { projectRoot: root });
    const runner = async () => {
      await writeStaging(plan, "correct content");
      return { exitCode: 0 };
    };
    const result = await installSkillPackage(plan, approved, runner, { now: clock });
    expect(result.status).toBe("installed");
    await expect(readFile(join(actualRoot, "skills", "nature-reader", "SKILL.md"), "utf8"))
      .resolves.toBe("correct content");
  });

  it("fails closed when license, dependency audit, or SBOM metadata is absent", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-install-preflight-"));
    const base = await skillPlan(root, "content");
    const runner = async (command: string, context?: { plan: InstallPlan; stagingDir?: string }) => {
      await writeStaging(context!.plan, "content");
      return { exitCode: 0 };
    };
    const missingLicense = await installSkillPackage({ ...base, license: undefined }, approved, runner, { now: clock });
    expect(missingLicense.receipt.reasonCode).toBe("install.license-missing");
    const missingDependencies = await installSkillPackage({ ...base, dependencies: undefined }, approved, runner, { now: clock });
    expect(missingDependencies.receipt.reasonCode).toBe("install.dependency-audit-missing");
    const missingSbom = await installSkillPackage({ ...base, sbom: undefined }, approved, runner, { now: clock });
    expect(missingSbom.receipt.reasonCode).toBe("install.sbom-missing");
  });

  it("does not retry after an unknown runner exception once reserved", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-install-reservation-"));
    const plan = { ...planAgentInstall(KNOWN_AGENTS.find((agent) => agent.id === "claude-code")!), kind: "package" as const, target: "target", stagingDir: "staging", projectRoot: root, expectedSha256: "a".repeat(64) };
    const ledger = new InMemoryInstallLedger();
    let calls = 0;
    const first = await runInstall(plan, approved, async () => {
      calls += 1;
      throw new Error("opaque external failure");
    }, { now: clock, ledger });
    const second = await runInstall(plan, approved, async () => {
      calls += 1;
      return { exitCode: 0 };
    }, { now: clock, ledger });
    expect(first.reasonCode).toBe("install.runner-error");
    expect(second.reasonCode).toBe("install.already-recorded");
    expect(calls).toBe(1);
  });
});
