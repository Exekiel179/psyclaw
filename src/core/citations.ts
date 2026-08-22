import { sha256Text } from "./hash.js";
import { readJsonl, appendJsonlIfMissing } from "../project/jsonl.js";
import { assertSafeProjectPath } from "../project/paths.js";
import { referenceFromVerification, upsertReference, type ReferenceRecord } from "./references.js";
import { verifyDoi, type DoiVerification } from "./doi.js";

/**
 * Citation-usage ledger (.psyclaw/citations.jsonl).
 *
 * When a paper is generated, every in-text citation should be recorded with
 * BOTH its evidence (the DOI reference, verified against the reference
 * archive) AND the reason it was cited (one line) plus the sentence context.
 * This makes the reference archive traceable: which citation appears where in
 * the manuscript, why it was chosen, and whether its metadata was verified.
 */

export interface CitationUseRecord {
  schemaVersion: "psyclaw/citation-use/v1";
  citationId: string;
  doi: string;
  surname: string;
  year?: number;
  reason: string;
  context: string;
  section?: string;
  claimId?: string;
  verified: boolean;
  recordedAt: string;
}

export interface RecordCitationInput {
  doi: string;
  reason: string;
  context: string;
  section?: string;
  claimId?: string;
}

export async function citationsPath(root: string): Promise<string> {
  return assertSafeProjectPath(root, ".psyclaw/citations.jsonl");
}

export async function listCitationUses(root: string): Promise<CitationUseRecord[]> {
  return readJsonl<CitationUseRecord>(await citationsPath(root));
}

/**
 * Record one citation use: verify the DOI (real network unless a verifier is
 * injected), archive the reference when verifiable, then append the use with
 * its reason. The use is always recorded (with `verified` reflecting the
 * verification outcome) so the citation reason is never lost.
 */
export async function recordCitationUse(
  root: string,
  input: RecordCitationInput,
  verify: (doi: string) => Promise<DoiVerification> = verifyDoi,
): Promise<{ record: CitationUseRecord; reference: ReferenceRecord | null; appended: boolean }> {
  const doi = input.doi.trim();
  const reason = input.reason.trim();
  const context = input.context.trim();
  if (!doi || !reason || !context) {
    throw new Error("doi, reason, and context are all required");
  }

  const verification = await verify(doi);
  const reference = referenceFromVerification(verification);
  if (reference !== null) {
    await upsertReference(root, reference);
  }

  const surname = (reference?.authors[0]?.split(/\s+/).at(-1) ?? doi.split("/")[0] ?? doi).slice(0, 40);
  const citationId = `cite_${sha256Text(`${doi}\u0000${reason}\u0000${context}`).slice(0, 16)}`;
  const record: CitationUseRecord = {
    schemaVersion: "psyclaw/citation-use/v1",
    citationId,
    doi,
    surname,
    ...(reference?.year === undefined ? {} : { year: reference.year }),
    reason,
    context,
    ...(input.section === undefined || input.section.trim() === "" ? {} : { section: input.section.trim() }),
    ...(input.claimId === undefined || input.claimId.trim() === "" ? {} : { claimId: input.claimId.trim() }),
    verified: verification.status === "verified",
    recordedAt: new Date().toISOString(),
  };
  const { appended } = await appendJsonlIfMissing(await citationsPath(root), record, (item) => item.citationId);
  return { record, reference, appended };
}
