import { readJsonl, appendJsonlIfMissing } from "../project/jsonl.js";
import { assertSafeProjectPath } from "../project/paths.js";
import type { DoiVerification } from "./doi.js";

/**
 * Project reference archive (.psyclaw/references.jsonl, append-only, idempotent
 * by DOI). Every in-text citation in the manuscript should be checked against
 * this archive — that is both the query source for citing and the
 * verification ledger for the citation-audit skill (docs/文档规范.md §7).
 */

export interface ReferenceRecord {
  schemaVersion: "psyclaw/reference/v1";
  doi: string;
  title: string;
  authors: string[];
  year?: number;
  venue?: string;
  verified: boolean;
  verification: DoiVerification;
  oaPdfUrl?: string;
  downloadedPath?: string;
  addedAt: string;
}

export interface CitationHit {
  surname: string;
  years: number[];
  matched: ReferenceRecord[];
}

export async function referencesPath(root: string): Promise<string> {
  return assertSafeProjectPath(root, ".psyclaw/references.jsonl");
}

export async function listReferences(root: string): Promise<ReferenceRecord[]> {
  return readJsonl<ReferenceRecord>(await referencesPath(root));
}

/** Idempotent by DOI: re-verifying or re-adding the same DOI returns the existing record. */
export async function upsertReference(root: string, record: ReferenceRecord): Promise<{ record: ReferenceRecord; appended: boolean }> {
  const result = await appendJsonlIfMissing(await referencesPath(root), record, (item) => item.doi);
  return { record, appended: result.appended };
}

export function referenceFromVerification(verification: DoiVerification): ReferenceRecord | null {
  if (verification.status === "error") return null;
  const crossref = verification.crossref;
  const title = crossref?.title ?? verification.openalex?.title;
  if (!title) return null;
  return {
    schemaVersion: "psyclaw/reference/v1",
    doi: verification.doi,
    title,
    authors: crossref?.authors ?? [],
    ...(crossref?.year === undefined ? {} : { year: crossref.year }),
    ...(crossref?.container === undefined ? {} : { venue: crossref.container }),
    verified: verification.status === "verified",
    verification,
    addedAt: new Date().toISOString(),
  };
}

const CITATION_GROUP = /[（(]([^（）()]*\d{4}[a-z]?[^（）()]*)[）)]/g;
// English "Kessler et al., 2005" / "Wanberg et al., 2010" / "A & B, 2005"
// and Chinese "张三，2020" / "张三 等，2020" items inside a group.
const CITATION_ITEM = /([\u4E00-\u9FFF]{2,4}(?:\s*等)?|[A-Z][A-Za-z\u00C0-\u024F'\-]+(?:\s+et al\.?)?(?:\s*&\s*[A-Z][A-Za-z\u00C0-\u024F'\-]+)?)\s*[,，]\s*(\d{4}[a-z]?)/g;

/**
 * Extract in-text citation items like `(Kessler et al., 2005; Wanberg et al.,
 * 2010)` into {surname, years} entries. Surname = first family name of the
 * first author of each item; Chinese-style `（作者，2005）` groups are included
 * via the same `(...)` capture.
 */
export function extractCitations(text: string): Array<{ surname: string; years: number[] }> {
  const found: Array<{ surname: string; years: number[] }> = [];
  const groups: string[] = [];
  for (const match of text.matchAll(CITATION_GROUP)) {
    const group = match[1] ?? "";
    groups.push(...group.split(";"));
  }
  for (const raw of groups) {
    const items: Array<{ surname: string; years: number[] }> = [];
    for (const item of raw.matchAll(CITATION_ITEM)) {
      const surname = (item[1] ?? "")
        .replace(/\s+et al\.?$/i, "")
        .replace(/\s+等$/, "")
        .replace(/\s*&\s*[A-Za-z\u00C0-\u024F'\-]+$/i, "")
        .trim()
        .split(/\s+/)[0] ?? "";
      const year = Number((item[2] ?? "").replace(/[a-z]$/i, ""));
      if (!surname || !Number.isFinite(year)) continue;
      const existing = items.find((entry) => entry.surname.toLowerCase() === surname.toLowerCase());
      if (existing) existing.years.push(year);
      else items.push({ surname, years: [year] });
    }
    found.push(...items);
  }
  // merge across groups
  const merged: Array<{ surname: string; years: number[] }> = [];
  for (const entry of found) {
    const existing = merged.find((item) => item.surname.toLowerCase() === entry.surname.toLowerCase());
    if (existing) existing.years.push(...entry.years);
    else merged.push({ surname: entry.surname, years: [...entry.years] });
  }
  return merged.map((entry) => ({ surname: entry.surname, years: [...new Set(entry.years)].sort((a, b) => a - b) }));
}

/**
 * Check every in-text citation against the archive. A citation is matched when
 * a reference's first author surname matches and at least one cited year is
 * present in the reference record (or the reference has no year).
 */
export function checkCitations(text: string, references: readonly ReferenceRecord[]): {
  citations: Array<CitationHit & { missing: boolean }>;
  matched: number;
  unmatched: number;
} {
  const citations = extractCitations(text).map((hit) => {
    const matched = references.filter((ref) => {
      const surname = ref.authors[0]?.split(/\s+/).at(-1) ?? "";
      if (!surname || surname.toLowerCase() !== hit.surname.toLowerCase()) return false;
      return ref.year === undefined || hit.years.some((year) => year === ref.year);
    });
    return { ...hit, matched, missing: matched.length === 0 };
  });
  return {
    citations,
    matched: citations.filter((item) => !item.missing).length,
    unmatched: citations.filter((item) => item.missing).length,
  };
}
