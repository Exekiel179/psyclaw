import { randomUUID } from "node:crypto";
import { lstat, readFile, readdir } from "node:fs/promises";
import { join } from "node:path";
import { markdownToDocx } from "../core/docx.js";
import { sha256File, sha256Text } from "../core/hash.js";
import { atomicWriteFile, appendJsonlIfMissing, readJsonl } from "../project/jsonl.js";
import { assertSafeProjectPath, projectPaths } from "../project/paths.js";
import { readManuscript } from "../project/manuscript.js";
import { allocateProjectVersion } from "../project/versions.js";

/**
 * Generation-time manuscript publishing with versioning (convention:
 * docs/文档规范.md).
 *
 *   paper/<name>.md                latest editable Markdown source
 *   paper/<name>_APA7.docx         latest APA-7 DOCX export
 *   paper/archive/<name>_v{n}.md   archived previous versions
 *   .psyclaw/versions.jsonl          version allocation (allocateProjectVersion,
 *                                  kind "manuscript")
 *   .psyclaw/publish.jsonl           published-version records (idempotent by sha)
 *
 * Re-publishing identical content is a no-op (no new version); changed content
 * archives the previous files and bumps the version. Both files are registered
 * in the evidence ledger with their SHA-256 fingerprints.
 */

/** A published manuscript version (one record per publish). */
export interface PublishedVersion {
  schemaVersion: "psyclaw/publish/v1";
  version: number;
  name: string;
  markdownPath: string;
  docxPath: string | null;
  markdownSha256: string;
  docxSha256: string | null;
  sourcePath: string | null;
  publishedAt: string;
}

export async function readPublishedVersions(root: string): Promise<PublishedVersion[]> {
  return readJsonl<PublishedVersion>(await assertSafeProjectPath(root, ".psyclaw/publish.jsonl"));
}

async function archiveFile(root: string, sourceRel: string, targetRel: string): Promise<void> {
  try {
    const source = await assertSafeProjectPath(root, sourceRel);
    const contents = await readFile(source, "utf8");
    await atomicWriteFile(await assertSafeProjectPath(root, targetRel), contents);
  } catch { /* nothing to archive */ }
}

/** Find a black-and-white reference document (paper/apa7-bw-reference.docx or similar). */
export async function findReferenceDoc(root: string): Promise<string | null> {
  let entries: import("node:fs").Dirent[] = [];
  try { entries = await readdir(join(root, "paper"), { withFileTypes: true }); } catch { return null; }
  for (const entry of entries) {
    if (!entry.isFile() || !/\.docx$/i.test(entry.name)) continue;
    if (/reference|模板|template/i.test(entry.name)) {
      const path = `paper/${entry.name}`;
      const stat = await lstat(await assertSafeProjectPath(root, path)).catch(() => undefined);
      if (stat?.isFile()) return path;
    }
  }
  return null;
}

export interface PublishOptions {
  /** Base file name, e.g. "论文初稿" (default). */
  name?: string;
  /** Manuscript source (Markdown). If omitted, the discovered manuscript is used. */
  markdown?: string;
  /** Export the APA-7 DOCX (default true). */
  exportDocx?: boolean;
}

export interface PublishResult {
  schemaVersion: "psyclaw/publish/v1";
  version: number;
  name: string;
  markdownPath: string;
  docxPath: string | null;
  markdownSha256: string;
  docxSha256: string | null;
  evidenceIds: string[];
  sourcePath: string | null;
  publishedAt: string;
}

export async function publishManuscript(root: string, options: PublishOptions = {}): Promise<PublishResult> {
  const name = (options.name ?? "论文初稿").trim().replace(/\.(md|docx)$/i, "");
  if (!name) throw new Error("manuscript name is required");
  const exportDocx = options.exportDocx ?? true;

  const existing = await readManuscript(root);
  const sourcePath = existing.exists ? existing.path : null;
  const markdown = options.markdown ?? existing.markdown;
  if (!markdown.trim()) {
    throw new Error("没有可发布的手稿内容：请先在编辑器写入内容，或先运行工作流生成论文初稿");
  }

  const markdownPath = `paper/${name}.md`;
  const markdownTarget = await assertSafeProjectPath(root, markdownPath);
  const written = markdown.endsWith("\n") ? markdown : `${markdown}\n`;
  const markdownSha256 = sha256Text(written);

  const published = await readPublishedVersions(root);
  const last = published.at(-1);
  if (last && last.markdownSha256 === markdownSha256) {
    // Re-publishing identical content is a no-op: no new version, no rewrite.
    return {
      schemaVersion: "psyclaw/publish/v1",
      version: last.version,
      name: last.name,
      markdownPath: last.markdownPath,
      docxPath: last.docxPath,
      markdownSha256,
      docxSha256: last.docxSha256,
      evidenceIds: [],
      sourcePath,
      publishedAt: last.publishedAt,
    };
  }

  // Archive the current files under the version they were last published as.
  if (last) {
    await archiveFile(root, markdownPath, `paper/archive/${name}_v${last.version}.md`);
    if (last.docxPath) await archiveFile(root, last.docxPath, `paper/archive/${name}_v${last.version}_APA7.docx`);
  }

  // Allocate the next manuscript version through the shared project allocator.
  const runId = `publish_${randomUUID().replaceAll("-", "")}`;
  const versionLabel = await allocateProjectVersion(root, "manuscript", runId);
  const version = Number(versionLabel.replace(/^v/i, ""));
  await atomicWriteFile(markdownTarget, written);

  const evidenceIds: string[] = [];
  const recordEvidence = async (path: string, sha256: string): Promise<string> => {
    const id = `evidence_${sha256.slice(0, 16)}`;
    // Idempotent by evidence id: publishing and importing the same file must
    // not create duplicate ledger entries.
    await appendJsonlIfMissing(projectPaths(root).evidence, {
      id,
      source: { kind: "file", locator: path, title: path.split("/").pop() ?? path },
      level: "fulltext",
      retrievedAt: new Date().toISOString(),
      sha256,
      accessStatus: "partial",
      locators: [{ kind: "file", value: path }],
    }, (item) => item.id);
    return id;
  };

  evidenceIds.push(await recordEvidence(markdownPath, markdownSha256));

  let docxPath: string | null = null;
  let docxSha256: string | null = null;
  if (exportDocx) {
    docxPath = `paper/${name}_APA7.docx`;
    const docxTarget = await assertSafeProjectPath(root, docxPath);
    const referenceDoc = await findReferenceDoc(root);
    const referenceTarget = referenceDoc ? await assertSafeProjectPath(root, referenceDoc) : undefined;
    await markdownToDocx(markdownTarget, docxTarget, referenceTarget);
    docxSha256 = await sha256File(docxTarget);
    evidenceIds.push(await recordEvidence(docxPath, docxSha256));
  }

  const publishedAt = new Date().toISOString();
  const versionRecord: PublishedVersion = {
    schemaVersion: "psyclaw/publish/v1",
    version,
    name,
    markdownPath,
    docxPath,
    markdownSha256,
    docxSha256,
    sourcePath,
    publishedAt,
  };
  await appendJsonlIfMissing(await assertSafeProjectPath(root, ".psyclaw/publish.jsonl"), versionRecord, (record) => record.markdownSha256);

  const result: PublishResult = {
    schemaVersion: "psyclaw/publish/v1",
    version,
    name,
    markdownPath,
    docxPath,
    markdownSha256,
    docxSha256,
    evidenceIds,
    sourcePath,
    publishedAt,
  };

  const receipt = {
    schemaVersion: "psyclaw/tool-receipt/v1",
    runId,
    taskId: "workflow.publish.manuscript",
    tool: "workflow.publish.manuscript",
    effect: "write",
    approval: "approved",
    idempotencyKey: `publish:${markdownSha256}`,
    ok: true,
    startedAt: publishedAt,
    finishedAt: publishedAt,
  };
  await atomicWriteFile(await assertSafeProjectPath(root, `.psyclaw/manifests/${runId}.receipt.json`), `${JSON.stringify(receipt, null, 2)}\n`);

  return result;
}
