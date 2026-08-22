import { createHash } from "node:crypto";
import type { KnowledgeEdge, KnowledgeNode, LiteratureLedgerEntry, VerifiedKnowledgeMap } from "./contracts.js";

export function buildVerifiedKnowledgeMap(entries: LiteratureLedgerEntry[], now = new Date().toISOString()): VerifiedKnowledgeMap {
  const nodes = new Map<string, KnowledgeNode>();
  const edges: KnowledgeEdge[] = [];
  for (const entry of entries) {
    if (entry.verification !== "verified") continue;
    const work: KnowledgeNode = nodes.get(entry.workId) ?? { id: entry.workId, type: "work", label: entry.title ?? entry.workId, verified: true, sourceIds: [] };
    work.sourceIds = [...new Set([...work.sourceIds, entry.id])]; nodes.set(work.id, work);
    for (const author of entry.authors ?? []) {
      const id = `person:${author.toLowerCase()}`;
      nodes.set(id, nodes.get(id) ?? { id, type: "person", label: author, verified: true, sourceIds: [entry.id] });
      edges.push({ id: `${entry.workId}:authored-by:${id}`, subject: entry.workId, predicate: "authored-by", object: id, sourceIds: [entry.id], verified: true });
    }
  }
  const sourceLedgerHash = createHash("sha256").update(JSON.stringify(entries)).digest("hex");
  return { schemaVersion: "psyclaw/knowledge-map/v1", nodes: [...nodes.values()], edges, generatedAt: now, sourceLedgerHash };
}
