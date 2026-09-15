import { describe, expect, it } from "vitest";
import { existsSync } from "node:fs";
import { chmod, mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { ExpectedUserError } from "../../src/observability/expected.js";
import { bootstrapProject, writeHandoff, hasCanonicalWorkspace, ensureProjectBinding } from "../../src/project/bootstrap.js";
import {
  assertSafeProjectPath,
  ensureProjectDirectories,
  isUnsuitableProjectRoot,
  projectPaths,
} from "../../src/project/paths.js";

async function tempProject(): Promise<string> {
  return mkdtemp(join(tmpdir(), "psyclaw-test-"));
}

describe("project bootstrap 0.29", () => {
  it("scaffolds clean workspace with data/raw and psyclaw.md without grill", async () => {
    const root = await tempProject();
    const project = await bootstrapProject({
      root,
      projectId: "project-test",
      now: "2026-01-01T00:00:00.000Z",
    });
    expect(project.goal).toBe("未命名研究项目");
    const paths = projectPaths(root);
    expect(paths.raw).toBe(join(root, "data", "raw"));
    expect(existsSync(paths.raw)).toBe(true);
    expect(existsSync(join(root, "data", "clean"))).toBe(true);
    expect(existsSync(join(root, "paper"))).toBe(true);
    expect(existsSync(join(root, "analysis", "results"))).toBe(true);
    expect(existsSync(join(root, ".psyclaw", "skills"))).toBe(true);
    expect(await readFile(join(root, "psyclaw.md"), "utf8")).toContain("Shift+Tab");
    expect(await readFile(join(root, "analysis", "HANDOFF.md"), "utf8")).toContain("Analysis → Academic");
    expect(existsSync(join(root, "notes", "research-spec.md"))).toBe(false);
    await writeHandoff(root, {
      projectId: project.id,
      runId: "run-test",
      goal: project.goal,
      completed: ["bootstrap"],
      verified: ["project.json"],
      blocked: [],
      nextSteps: ["analyze"],
      verificationCommands: ["pnpm test"],
      generatedAt: "2026-01-01T00:00:00.000Z",
    });
    expect(JSON.parse(await readFile(paths.handoffJson, "utf8")).schemaVersion).toBe("psyclaw/handoff/v1");
  });

  it("rejects protected raw writes under data/raw", async () => {
    const root = await tempProject();
    await expect(assertSafeProjectPath(root, "data/raw/new.csv")).rejects.toThrow("Protected");
    await expect(assertSafeProjectPath(root, ".psyclaw/data/raw/new.csv")).rejects.toThrow("Protected");
  });

  it("reuses canonical workspace across sessions without re-init error", async () => {
    const root = await tempProject();
    const first = await bootstrapProject({
      root,
      projectId: "project-reuse",
      now: "2026-01-01T00:00:00.000Z",
    });
    expect(await hasCanonicalWorkspace(root)).toBe(true);
    const second = await bootstrapProject({ root, goal: "新目标" });
    expect(second.id).toBe(first.id);
    const rebound = await ensureProjectBinding({ root });
    expect(rebound.project.id).toBe(first.id);
    expect(rebound.created).toBe(false);
  });

  it("treats Windows System32 and Program Files as unsuitable project roots", () => {
    expect(isUnsuitableProjectRoot("C:\\Windows\\System32", { platform: "win32" })).toBe(true);
    expect(isUnsuitableProjectRoot("C:/Windows/SysWOW64", { platform: "linux" })).toBe(true);
    expect(isUnsuitableProjectRoot("C:\\Program Files\\Git", { platform: "win32" })).toBe(true);
    expect(isUnsuitableProjectRoot("C:\\Users\\researcher\\study", { platform: "win32" })).toBe(false);
    expect(isUnsuitableProjectRoot("/etc", { platform: "linux" })).toBe(true);
    expect(isUnsuitableProjectRoot(resolve("C:\\Windows\\System32"))).toBe(true);
  });

  it("refuses to mkdir project dirs under System32 before Node EPERM", async () => {
    const root = "C:\\Windows\\System32";
    await expect(ensureProjectDirectories(root)).rejects.toSatisfy((error: unknown) => {
      return error instanceof ExpectedUserError
        && error.message.includes("无法在当前工作目录创建项目文件")
        && (error as NodeJS.ErrnoException).code === "EPERM"
        && String((error as NodeJS.ErrnoException).path ?? "").replaceAll("\\", "/").includes(".psyclaw");
    });
    await expect(bootstrapProject({ root, goal: "不应建仓" })).rejects.toBeInstanceOf(ExpectedUserError);
    expect(existsSync(resolve(root, ".psyclaw"))).toBe(false);
  });

  it("refuses an unwritable project root with a Chinese path error", async () => {
    if (typeof process.getuid === "function" && process.getuid() === 0) return;
    const root = await tempProject();
    await chmod(root, 0o555);
    try {
      await expect(ensureProjectDirectories(root)).rejects.toSatisfy((error: unknown) => {
        return error instanceof ExpectedUserError && error.message.includes("无法在当前工作目录创建项目文件");
      });
      expect(existsSync(join(root, ".psyclaw"))).toBe(false);
    } finally {
      await chmod(root, 0o755);
    }
  });
});
