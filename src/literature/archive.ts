import { mkdir, readFile, writeFile } from "node:fs/promises";
import { sha256Text } from "../core/hash.js";
import { sniffKindFromBuffer } from "../core/filekind.js";
import { lookupOaPdfUrl } from "../core/doi.js";
import { atomicWriteFile, readJsonl } from "../project/jsonl.js";
import { assertSafeProjectPath, projectPaths } from "../project/paths.js";

export type ReferenceFulltextStatus = "downloaded" | "manual-download-required" | "download-failed";

export interface ReferenceFulltextRecord {
  schemaVersion: "psyclaw/reference-fulltext/v1";
  doi: string;
  doiUrl: string;
  status: ReferenceFulltextStatus;
  localPath: string;
  sourceUrl?: string;
  reason?: string;
  checkedAt: string;
}

export interface CitationFulltextAudit {
  schemaVersion: "psyclaw/citation-fulltext-audit/v1";
  ok: boolean;
  citedDois: string[];
  verifiedDois: string[];
  downloadedDois: string[];
  missingVerification: string[];
  missingPdfs: Array<{ doi: string; doiUrl: string; expectedPath: string; reason?: string }>;
}

function normalizedDoi(value: string): string {
  return value.trim().replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, "").toLowerCase();
}

export function referencePdfPath(doi: string): string {
  return `literature/pdfs/doi-${sha256Text(normalizedDoi(doi)).slice(0, 20)}.pdf`;
}

function recordPath(doi: string): string {
  return `.psyclaw/fulltexts/${sha256Text(normalizedDoi(doi)).slice(0, 20)}.json`;
}

async function saveRecord(root: string, record: ReferenceFulltextRecord): Promise<void> {
  await atomicWriteFile(await assertSafeProjectPath(root, recordPath(record.doi)), `${JSON.stringify(record, null, 2)}\n`);
}

async function readRecord(root: string, doi: string): Promise<ReferenceFulltextRecord | null> {
  try {
    return JSON.parse(await readFile(await assertSafeProjectPath(root, recordPath(doi)), "utf8")) as ReferenceFulltextRecord;
  } catch {
    return null;
  }
}

async function isPdf(root: string, relativePath: string): Promise<boolean> {
  try {
    const bytes = await readFile(await assertSafeProjectPath(root, relativePath));
    return sniffKindFromBuffer(bytes.subarray(0, 512)) === "pdf";
  } catch {
    return false;
  }
}

/** Download only a verified open-access location. Paywalled items stay as a DOI link and an exact local target. */
export async function archiveOpenAccessPdf(
  root: string,
  doi: string,
  fetchFn: typeof fetch = fetch,
): Promise<ReferenceFulltextRecord> {
  const normalized = normalizedDoi(doi);
  if (!/^10\.\d{4,9}\/\S+$/i.test(normalized)) throw new Error(`Invalid DOI: ${doi}`);
  const checkedAt = new Date().toISOString();
  const doiUrl = `https://doi.org/${normalized}`;
  const localPath = referencePdfPath(normalized);
  await mkdir(projectPaths(root).literaturePdfs, { recursive: true });

  if (await isPdf(root, localPath)) {
    const record: ReferenceFulltextRecord = { schemaVersion: "psyclaw/reference-fulltext/v1", doi: normalized, doiUrl, status: "downloaded", localPath, checkedAt };
    await saveRecord(root, record);
    return record;
  }

  const lookup = await lookupOaPdfUrl(normalized, fetchFn);
  if (!lookup.oaPdfUrl || !/^https?:\/\//i.test(lookup.oaPdfUrl)) {
    const record: ReferenceFulltextRecord = {
      schemaVersion: "psyclaw/reference-fulltext/v1",
      doi: normalized,
      doiUrl,
      status: "manual-download-required",
      localPath,
      reason: "No verified open-access PDF was found. Use lawful personal or institutional access; PsyClaw will not bypass a paywall.",
      checkedAt,
    };
    await saveRecord(root, record);
    return record;
  }

  try {
    const response = await fetchFn(lookup.oaPdfUrl, { redirect: "follow", signal: AbortSignal.timeout(30_000) });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const bytes = Buffer.from(await response.arrayBuffer());
    if (bytes.byteLength > 100 * 1024 * 1024) throw new Error("PDF exceeds the 100 MiB project limit");
    if (sniffKindFromBuffer(bytes.subarray(0, 512)) !== "pdf") throw new Error("downloaded content is not a recognizable PDF");
    const target = await assertSafeProjectPath(root, localPath);
    try { await writeFile(target, bytes, { flag: "wx" }); }
    catch (error) { if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error; }
    if (!(await isPdf(root, localPath))) throw new Error("local PDF verification failed");
    const record: ReferenceFulltextRecord = { schemaVersion: "psyclaw/reference-fulltext/v1", doi: normalized, doiUrl, status: "downloaded", localPath, sourceUrl: lookup.oaPdfUrl, checkedAt };
    await saveRecord(root, record);
    return record;
  } catch (error) {
    const record: ReferenceFulltextRecord = {
      schemaVersion: "psyclaw/reference-fulltext/v1",
      doi: normalized,
      doiUrl,
      status: "download-failed",
      localPath,
      sourceUrl: lookup.oaPdfUrl,
      reason: error instanceof Error ? error.message : String(error),
      checkedAt,
    };
    await saveRecord(root, record);
    return record;
  }
}

/** Final manuscript gate: every cited DOI must be metadata-verified and backed by a recognizable local PDF. */
export async function auditCitationFulltexts(root: string): Promise<CitationFulltextAudit> {
  const [uses, references] = await Promise.all([
    readJsonl<{ doi: string }>(await assertSafeProjectPath(root, ".psyclaw/citations.jsonl")),
    readJsonl<{ doi: string; verified: boolean }>(await assertSafeProjectPath(root, ".psyclaw/references.jsonl")),
  ]);
  const citedDois = [...new Set(uses.map((item) => normalizedDoi(item.doi)))].sort();
  const verified = new Set(references.filter((item) => item.verified).map((item) => normalizedDoi(item.doi)));
  const verifiedDois = citedDois.filter((doi) => verified.has(doi));
  const missingVerification = citedDois.filter((doi) => !verified.has(doi));
  const downloadedDois: string[] = [];
  const missingPdfs: CitationFulltextAudit["missingPdfs"] = [];
  for (const doi of citedDois) {
    const localPath = referencePdfPath(doi);
    if (await isPdf(root, localPath)) {
      downloadedDois.push(doi);
      continue;
    }
    const record = await readRecord(root, doi);
    missingPdfs.push({ doi, doiUrl: `https://doi.org/${doi}`, expectedPath: localPath, ...(record?.reason ? { reason: record.reason } : {}) });
  }
  return {
    schemaVersion: "psyclaw/citation-fulltext-audit/v1",
    ok: citedDois.length > 0 && missingVerification.length === 0 && missingPdfs.length === 0,
    citedDois,
    verifiedDois,
    downloadedDois,
    missingVerification,
    missingPdfs,
  };
}
