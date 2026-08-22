import { lstat, mkdtemp, readFile, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { bootstrapProject, writeHandoff } from "../../src/project/bootstrap.js";
import { assertSafeProjectPath, projectPaths } from "../../src/project/paths.js";

async function tempProject(): Promise<string> {
  return mkdtemp(join(tmpdir(), "psyclaw-test-"));
}

describe("project bootstrap", () => {
  it("creates the project state and a paired handoff", async () => {
    const root = await tempProject();
    const project = await bootstrapProject({
      root,
      goal: "Study a bounded social process",
      paradigm: "qualitative-thematic",
      projectId: "project-test",
      now: "2026-01-01T00:00:00.000Z",
    });
    expect(project.id).toBe("project-test");
    await writeHandoff(root, {
      projectId: project.id,
      runId: "run-test",
      goal: project.goal,
      completed: ["bootstrap"],
      verified: ["project.json"],
      blocked: [],
      nextSteps: ["capture evidence"],
      verificationCommands: ["pnpm test"],
      generatedAt: "2026-01-01T00:00:00.000Z",
    });
    const paths = projectPaths(root);
    expect(JSON.parse(await readFile(paths.project, "utf8")).id).toBe(project.id);
    expect(JSON.parse(await readFile(paths.handoffJson, "utf8")).schemaVersion).toBe("psyclaw/handoff/v1");
    expect(await readFile(paths.handoffMarkdown, "utf8")).toContain("`pnpm test`");
  });

  it("rejects a second initialization", async () => {
    const root = await tempProject();
    const options = { root, goal: "A goal", paradigm: "survey-observational" as const };
    await bootstrapProject(options);
    await expect(bootstrapProject(options)).rejects.toThrow("already initialized");
  });

  it("validates an empty goal before creating project directories", async () => {
    const root = await tempProject();
    await expect(bootstrapProject({ root, goal: "   ", paradigm: "survey-observational" })).rejects.toThrow(
      "Research goal cannot be empty",
    );
    await expect(lstat(join(root, ".psyclaw"))).rejects.toMatchObject({ code: "ENOENT" });
  });

  it("rejects traversal, protected raw data, and symlink targets", async () => {
    const root = await tempProject();
    await expect(assertSafeProjectPath(root, "../outside.txt")).rejects.toThrow("escapes");
    await expect(assertSafeProjectPath(root, "..")).rejects.toThrow("escapes");
    await expect(assertSafeProjectPath(root, "..\\outside.txt")).rejects.toThrow("escapes");
    await expect(assertSafeProjectPath(root, "/tmp/outside.txt")).rejects.toThrow("escapes");
    await expect(assertSafeProjectPath(root, "C:\\outside.txt")).rejects.toThrow("escapes");
    await expect(assertSafeProjectPath(root, "\\\\server\\share\\outside.txt")).rejects.toThrow("escapes");
    await expect(assertSafeProjectPath(root, "data/raw/new.csv")).rejects.toThrow("Protected");
    const target = join(root, "notes");
    const outside = await tempProject();
    await symlink(outside, target, "junction");
    await expect(assertSafeProjectPath(root, "notes/file.md")).rejects.toThrow();
  });

  it("does not treat a user supplied symlink as an evidence file", async () => {
    const root = await tempProject();
    const outside = await tempProject();
    const source = join(outside, "source.md");
    await writeFile(source, "private source", "utf8");
    const link = join(root, "linked.md");
    await symlink(source, link, "file");
    const stat = await import("node:fs/promises").then(({ lstat }) => lstat(link));
    expect(stat.isSymbolicLink()).toBe(true);
  });
});
