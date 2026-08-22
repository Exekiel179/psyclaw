import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { checkUpdates } from "../../src/updates/check.js";
import { checkSkillDrift } from "../../src/updates/skills.js";
import { PI_AI, PI_CODING_AGENT } from "../../src/updates/manifest.js";
import { createHttpRegistry, npmPackageName, pipxPackageName, type RegistryClient } from "../../src/updates/registry.js";
import { compareSemver, isUnpinnedRef, versionStatus } from "../../src/updates/status.js";
import { updateBundledPi } from "../../src/updates/update.js";

const sha = (text: string): string => createHash("sha256").update(text).digest("hex");

describe("version status", () => {
  it("compares semver and classifies pinned versions", () => {
    expect(compareSemver("0.1.0", "0.2.0")).toBe(-1);
    expect(compareSemver("1.0.0", "1.0.0")).toBe(0);
    expect(compareSemver("2.0.0", "1.9.9")).toBe(1);
    expect(compareSemver("not-a-version", "1.0.0")).toBeNull();
    expect(versionStatus("0.1.0", "0.2.0")).toBe("outdated");
    expect(versionStatus("1.0.0", "1.0.0")).toBe("up-to-date");
    expect(versionStatus("1.0.0", undefined)).toBe("unavailable");
  });

  it("treats unpinned refs as not comparable", () => {
    for (const ref of ["", "unpinned", "latest", "head", "master", "unknown", undefined]) {
      expect(isUnpinnedRef(ref)).toBe(true);
    }
    expect(isUnpinnedRef("1.2.3")).toBe(false);
  });
});

describe("registry helpers", () => {
  it("extracts package names and strips version specifiers", () => {
    expect(npmPackageName("npm install -g @anthropic-ai/claude-code")).toBe("@anthropic-ai/claude-code");
    expect(npmPackageName("npm install -g @anthropic-ai/claude-code@2.1.232")).toBe("@anthropic-ai/claude-code");
    expect(npmPackageName("npm install --global opencode-ai@1.18.18")).toBe("opencode-ai");
    expect(pipxPackageName("pipx install aider-chat")).toBe("aider-chat");
    expect(pipxPackageName("pipx install aider-chat==0.16.0")).toBe("aider-chat");
  });
});

describe("skill drift detection", () => {
  it("detects up-to-date, changed, and missing sources", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-drift-"));
    const sourceDir = await mkdtemp(join(tmpdir(), "psyclaw-source-"));
    const source = join(sourceDir, "SKILL.md");
    await writeFile(source, "# original\n", "utf8");

    const agentId = "claude-code";
    const manifestDir = join(root, ".psyclaw", "imports", agentId);
    await mkdir(manifestDir, { recursive: true });
    const manifestPath = join(manifestDir, "import-manifest.json");
    await writeFile(manifestPath, JSON.stringify({
      schemaVersion: "psyclaw/skill-import/v1",
      agentId,
      skills: [{ name: "sk", kind: "dir", files: [{ sourcePath: source, sha256: sha("# original\n") }] }],
    }), "utf8");

    await expect(checkSkillDrift(root, agentId)).resolves.toMatchObject({ status: "up-to-date" });

    await writeFile(source, "# changed\n", "utf8");
    const changed = await checkSkillDrift(root, agentId);
    expect(changed.status).toBe("changed");
    expect(changed.changed).toEqual([source]);

    await rm(source);
    const missing = await checkSkillDrift(root, agentId);
    expect(missing.status).toBe("missing");
    expect(missing.missing).toEqual([source]);
  });

  it("reports no-import when no manifest exists", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-drift-"));
    await expect(checkSkillDrift(root, "opencode")).resolves.toMatchObject({ status: "no-import" });
  });
});

describe("checkUpdates orchestration", () => {
  it("builds a self/agents/skills report without real network", async () => {
    const registry: RegistryClient = {
      latestNpm: async (pkg) => {
        if (pkg === "psyclaw") return "999.0.0";
        if (pkg === "@anthropic-ai/claude-code") return "2.0.0";
        return undefined;
      },
      latestPypi: async (pkg) => (pkg === "aider-chat" ? "1.0.0" : undefined),
      latestPiRelease: async () => ({ version: "0.84.2", packageName: PI_CODING_AGENT }),
    };
    const cwd = await mkdtemp(join(tmpdir(), "psyclaw-updates-"));
    const report = await checkUpdates({ registry, cwd, now: () => "2026-01-01T00:00:00.000Z" });

    expect(report.schemaVersion).toBe("psyclaw/update-report/v1");
    expect(report.self.status).toBe("outdated");
    expect(report.self.latest).toBe("999.0.0");

    expect(report.runtime.packageName).toBe(PI_CODING_AGENT);
    expect(report.runtime.current).toBe("0.84.1");
    expect(report.runtime.latest).toBe("0.84.2");
    expect(report.runtime.status).toBe("outdated");

    const claude = report.agents.find((agent) => agent.id === "claude-code")!;
    expect(claude.latest).toBe("2.0.0");
    expect(claude.status).toBe("up-to-date"); // pinned 2.1.232 is newer than the fake 2.0.0

    const aider = report.agents.find((agent) => agent.id === "aider")!;
    expect(aider.latest).toBe("1.0.0");
    expect(aider.status).toBe("outdated"); // pinned 0.16.0 is older than the fake 1.0.0

    expect(report.skills.length).toBeGreaterThan(0);
    expect(report.skills.every((skill) => skill.status === "no-import")).toBe(true);
  });
});

describe("latestPiRelease registry", () => {
  const fakeResponse = (body: unknown, ok = true): Response => ({ ok, json: async () => body }) as unknown as Response;

  it("returns the release when pi.dev reports a version", async () => {
    const registry = createHttpRegistry(async () => fakeResponse({ version: "0.84.2", packageName: PI_CODING_AGENT, note: "hi" }));
    await expect(registry.latestPiRelease()).resolves.toEqual({
      version: "0.84.2",
      packageName: PI_CODING_AGENT,
      note: "hi",
    });
  });

  it("fails closed on non-ok, missing version, or thrown fetch", async () => {
    const notOk = createHttpRegistry(async () => fakeResponse({ version: "0.84.2" }, false));
    await expect(notOk.latestPiRelease()).resolves.toBeUndefined();

    const noVersion = createHttpRegistry(async () => fakeResponse({ ok: true }));
    await expect(noVersion.latestPiRelease()).resolves.toBeUndefined();

    const broken = createHttpRegistry(async () => {
      throw new Error("boom");
    });
    await expect(broken.latestPiRelease()).resolves.toBeUndefined();
  });
});

describe("updateBundledPi", () => {
  const makeRoot = async (): Promise<string> => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-update-"));
    await writeFile(join(root, "package.json"), JSON.stringify({
      name: "psyclaw",
      version: "0.1.0",
      dependencies: { [PI_AI]: "0.84.1", [PI_CODING_AGENT]: "0.84.1" },
    }), "utf8");
    await writeFile(join(root, "pnpm-lock.yaml"), "", "utf8");
    return root;
  };

  const registry: RegistryClient = {
    latestNpm: async () => undefined,
    latestPypi: async () => undefined,
    latestPiRelease: async () => ({ version: "0.84.2", packageName: PI_CODING_AGENT }),
  };

  it("applies the bump through the injected executor", async () => {
    const root = await makeRoot();
    const steps: { command: string; cwd: string }[] = [];
    const receipt = await updateBundledPi({
      registry,
      packageRoot: root,
      now: () => "2026-01-01T00:00:00.000Z",
      executor: async (step) => {
        steps.push(step);
        return { exitCode: 0 };
      },
    });

    expect(receipt.ok).toBe(true);
    expect(receipt.executed).toBe(true);
    expect(receipt.reasonCode).toBe("update-applied");
    expect(receipt.before).toBe("0.84.1");
    expect(receipt.after).toBe("0.84.2");
    expect(steps).toHaveLength(1);
    expect(steps[0]!.cwd).toBe(root);
    expect(steps[0]!.command).toBe(`pnpm add --save-exact ${PI_AI}@0.84.2 ${PI_CODING_AGENT}@0.84.2`);
  });

  it("reports already-up-to-date without executing", async () => {
    const root = await makeRoot();
    const current = { ...registry, latestPiRelease: async () => ({ version: "0.84.1", packageName: PI_CODING_AGENT }) };
    let ran = false;
    const receipt = await updateBundledPi({
      registry: current,
      packageRoot: root,
      executor: async () => {
        ran = true;
        return { exitCode: 0 };
      },
    });
    expect(receipt.reasonCode).toBe("already-up-to-date");
    expect(receipt.executed).toBe(false);
    expect(ran).toBe(false);
  });

  it("returns a dry-run plan when no executor is provided", async () => {
    const root = await makeRoot();
    const receipt = await updateBundledPi({ registry, packageRoot: root });
    expect(receipt.ok).toBe(true);
    expect(receipt.executed).toBe(false);
    expect(receipt.reasonCode).toBe("update-skipped");
    expect(receipt.command).toContain("0.84.2");
    expect(receipt.after).toBe("0.84.2");
  });

  it("fails closed when the executor reports a non-zero exit", async () => {
    const root = await makeRoot();
    const receipt = await updateBundledPi({
      registry,
      packageRoot: root,
      executor: async () => ({ exitCode: 1 }),
    });
    expect(receipt.ok).toBe(false);
    expect(receipt.reasonCode).toBe("update-failed");
    expect(receipt.after).toBeUndefined();
  });

  it("refuses an unsafe version and never executes", async () => {
    const root = await makeRoot();
    const unsafe = { ...registry, latestPiRelease: async () => ({ version: "0.84.2; rm -rf /", packageName: PI_CODING_AGENT }) };
    let ran = false;
    const receipt = await updateBundledPi({
      registry: unsafe,
      packageRoot: root,
      executor: async () => {
        ran = true;
        return { exitCode: 0 };
      },
    });
    expect(receipt.reasonCode).toBe("update-skipped");
    expect(receipt.executed).toBe(false);
    expect(ran).toBe(false);
  });
});
