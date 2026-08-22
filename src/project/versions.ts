import { readJsonl, appendJsonl } from "./jsonl.js";
import { projectPaths } from "./paths.js";

export type VersionedArtifactKind = "analysis-plan" | "manuscript-revision" | "figure" | "table" | "manuscript";

export interface VersionRecord {
  schemaVersion: "psyclaw/version-record/v1";
  kind: VersionedArtifactKind;
  version: number;
  runId: string;
  createdAt: string;
}

/** Allocate monotonically within a project and persist the allocation. */
export async function allocateProjectVersion(root: string, kind: VersionedArtifactKind, runId: string, now = new Date().toISOString()): Promise<string> {
  const path = projectPaths(root).versions;
  const records = await readJsonl<Partial<VersionRecord>>(path);
  const max = records
    .filter((record) => record.kind === kind && Number.isInteger(record.version) && (record.version ?? 0) > 0)
    .reduce((highest, record) => Math.max(highest, record.version ?? 0), 0);
  const version = max + 1;
  await appendJsonl<VersionRecord>(path, { schemaVersion: "psyclaw/version-record/v1", kind, version, runId, createdAt: now });
  return `v${version}`;
}
