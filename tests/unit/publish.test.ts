import { mkdir, mkdtemp, readFile, stat, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { bootstrapProject } from "../../src/project/bootstrap.js";
import { publishManuscript } from "../../src/workflows/publish.js";

const pandocOk = await new Promise<boolean>((resolve) => {
  const child = spawn("pandoc", ["--version"], { stdio: "ignore", shell: process.platform === "win32" });
  child.on("error", () => resolve(false));
  child.on("close", (code) => resolve(code === 0));
});

describe("publishManuscript (generation-time convention)", () => {
  it("writes paper/<name>.md and registers evidence + publish record", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-publish-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    const result = await publishManuscript(root, { name: "论文初稿", markdown: "# 标题\n\n正文", exportDocx: false });

    expect(result.markdownPath).toBe("paper/论文初稿.md");
    expect(result.docxPath).toBeNull();
    expect(result.sourcePath).toBeNull();

    const onDisk = await readFile(join(root, "paper", "论文初稿.md"), "utf8");
    expect(onDisk).toContain("# 标题");

    const evidence = await readFile(join(root, ".psyclaw", "evidence.jsonl"), "utf8");
    expect(evidence).toContain("paper/论文初稿.md");
    expect(evidence).toContain(result.markdownSha256);
    expect(evidence).toContain('"accessStatus":"partial"');

    const publish = await readFile(join(root, ".psyclaw", "publish.jsonl"), "utf8");
    expect(publish).toContain("psyclaw/publish/v1");

    const again = await publishManuscript(root, { name: "论文初稿", markdown: "# 标题\n\n正文", exportDocx: false });
    expect(again.markdownSha256).toBe(result.markdownSha256);
  });

  it("publishes the discovered manuscript when no markdown is given", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-publish-src-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await mkdir(join(root, "paper"), { recursive: true });
    await writeFile(join(root, "paper", "论文初稿.md"), "来源内容", "utf8");

    const result = await publishManuscript(root, { exportDocx: false });
    expect(result.sourcePath).toBe("paper/论文初稿.md");
    expect(result.markdownPath).toBe("paper/论文初稿.md");
    expect(await readFile(join(root, "paper", "论文初稿.md"), "utf8")).toContain("来源内容");
  });

  it("throws honestly when there is nothing to publish", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-publish-empty-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await expect(publishManuscript(root, { exportDocx: false })).rejects.toThrow(/没有可发布/);
  });
});

describe("publishManuscript versioning", () => {
  it("bumps versions, archives the previous files, and no-ops on identical content", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-publish-v-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });

    const v1 = await publishManuscript(root, { name: "论文初稿", markdown: "# 第一版\n\n内容一", exportDocx: false });
    expect(v1.version).toBe(1);

    // same content again → no new version, no rewrite
    const noop = await publishManuscript(root, { name: "论文初稿", markdown: "# 第一版\n\n内容一", exportDocx: false });
    expect(noop.version).toBe(1);
    expect(noop.evidenceIds).toEqual([]);

    // changed content → v2 + archive of v1
    const v2 = await publishManuscript(root, { name: "论文初稿", markdown: "# 第二版\n\n内容二", exportDocx: false });
    expect(v2.version).toBe(2);

    const archive = await readFile(join(root, "paper", "archive", "论文初稿_v1.md"), "utf8");
    expect(archive).toContain("内容一");
    expect(await readFile(join(root, "paper", "论文初稿.md"), "utf8")).toContain("内容二");

    // published-version records live in publish.jsonl; the allocator ledger
    // (versions.jsonl, kind "manuscript") records the same allocations.
    const published = await readFile(join(root, ".psyclaw", "publish.jsonl"), "utf8");
    expect(published.split(/\r?\n/).filter(Boolean)).toHaveLength(2);
    expect(published).toContain('"version":2');
    const allocated = await readFile(join(root, ".psyclaw", "versions.jsonl"), "utf8");
    expect(allocated).toContain('"kind":"manuscript"');
  });
});

describe("publishManuscript docx export", () => {
  it.runIf(pandocOk)("exports paper/<name>_APA7.docx via pandoc", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-publish-docx-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    const result = await publishManuscript(root, { name: "论文初稿", markdown: "# 标题\n\n正文内容\n" });

    expect(result.docxPath).toBe("paper/论文初稿_APA7.docx");
    const docxStat = await stat(join(root, "paper", "论文初稿_APA7.docx"));
    expect(docxStat.size).toBeGreaterThan(1000);

    const evidence = await readFile(join(root, ".psyclaw", "evidence.jsonl"), "utf8");
    expect(evidence).toContain("论文初稿_APA7.docx");
    expect(evidence).toContain(result.docxSha256 ?? "");
  });

  it("auto-uses a paper/*reference*.docx as the black-and-white template", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-publish-ref-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await mkdir(join(root, "paper"), { recursive: true });
    await writeFile(join(root, "paper", "apa7-bw-reference.docx"), "placeholder", "utf8");
    const { findReferenceDoc } = await import("../../src/workflows/publish.js");
    expect(await findReferenceDoc(root)).toBe("paper/apa7-bw-reference.docx");
  });
});
