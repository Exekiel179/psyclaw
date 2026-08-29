import { basename, dirname, extname } from "node:path";
import { readFile } from "node:fs/promises";
import { markdownToDocx } from "../core/docx.js";
import { sha256File } from "../core/hash.js";
import { atomicWriteFile } from "../project/jsonl.js";
import { assertSafeProjectPath } from "../project/paths.js";
import { readManuscript } from "../project/manuscript.js";
import { findReferenceDoc, publishManuscript } from "./publish.js";

export type AcademicExportResult =
  | { kind: "manuscript"; markdownPath: string; docxPath: string | null; docxSha256: string | null }
  | { kind: "analysis-report"; markdownPath: string; docxPath: string; docxSha256: string; notice: string };

/** Export a real manuscript through its evidence gate, or explicitly export only an academic analysis report. */
export async function exportAcademicDocument(root: string): Promise<AcademicExportResult> {
  const document = await readManuscript(root);
  if (!document.exists || !document.path || !document.markdown.trim()) throw new Error("没有可导出的 Markdown 文档");
  const isManuscript = document.path === "notes/manuscript.md" || document.path.startsWith("paper/") || document.path.startsWith("docs/");
  if (isManuscript) {
    const result = await publishManuscript(root, { name: basename(document.path, extname(document.path)), exportDocx: true });
    return { kind: "manuscript", markdownPath: result.markdownPath, docxPath: result.docxPath, docxSha256: result.docxSha256 };
  }

  const source = await assertSafeProjectPath(root, document.path);
  const directory = dirname(document.path).replaceAll("\\", "/");
  const stem = basename(document.path, extname(document.path));
  const docxPath = `${directory}/${stem}_APA7.docx`;
  const target = await assertSafeProjectPath(root, docxPath);
  const reference = await findReferenceDoc(root);
  await markdownToDocx(source, target, reference ? await assertSafeProjectPath(root, reference) : undefined);
  const docxSha256 = await sha256File(target);
  await atomicWriteFile(await assertSafeProjectPath(root, ".psyclaw/analysis-report-export.json"), `${JSON.stringify({
    schemaVersion: "psyclaw/analysis-report-export/v1",
    markdownPath: document.path,
    docxPath,
    docxSha256,
    classification: "academic-analysis-report-not-manuscript",
    exportedAt: new Date().toISOString(),
  }, null, 2)}\n`);
  return {
    kind: "analysis-report",
    markdownPath: document.path,
    docxPath,
    docxSha256,
    notice: "前置的文献调研、全文写作和同行评审尚未完成；本文件仅为遵循学术报告规范的分析报告，不是论文。",
  };
}
