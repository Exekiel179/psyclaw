import { appendJsonl, readJsonl } from "../project/jsonl.js";
import { projectPaths } from "../project/paths.js";
import type { LiteratureLedgerEntry } from "./contracts.js";

function validate(entry: LiteratureLedgerEntry): LiteratureLedgerEntry {
  if (entry.schemaVersion !== "psyclaw/literature-ledger/v1" || !entry.id || !entry.workId || !entry.sourceLocator) throw new Error("invalid literature ledger entry");
  if (entry.verification === "verified" && entry.evidenceLevel === "fulltext" && entry.artifactIds.length === 0) throw new Error("verified full-text entry requires an artifact");
  return entry;
}

export async function appendLiteratureLedgerEntry(root: string, entry: LiteratureLedgerEntry): Promise<void> {
  await appendJsonl(projectPaths(root).evidence, validate(entry));
}

export async function loadLiteratureLedger(root: string): Promise<LiteratureLedgerEntry[]> {
  const values = await readJsonl<unknown>(projectPaths(root).evidence);
  return values.filter((value): value is LiteratureLedgerEntry => typeof value === "object" && value !== null && (value as { schemaVersion?: unknown }).schemaVersion === "psyclaw/literature-ledger/v1").map(validate);
}
