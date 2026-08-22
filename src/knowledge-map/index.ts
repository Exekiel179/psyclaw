import type { Claim, Evidence } from "../core/contracts.js";
import type { KnowledgeEdge, KnowledgeEntity, KnowledgeMap } from "./contracts.js";
export * from "./contracts.js";

export function buildKnowledgeMap(evidence: Evidence[], claims: Claim[]): KnowledgeMap {
  const entities = new Map<string, KnowledgeEntity>(); const edges: KnowledgeEdge[] = [];
  const add = (entity: KnowledgeEntity) => { if (!entities.has(entity.id)) entities.set(entity.id, entity); };
  for (const item of evidence) {
    const workId = `work:${item.id}`; add({ id: workId, type: "work", label: item.source.title ?? item.source.locator, sourceRefs: [item.id] });
    const citationId = `citation:${item.id}`; add({ id: citationId, type: "citation", label: item.source.locator, sourceRefs: [item.id] });
    edges.push({ id: `${workId}->${citationId}`, from: workId, relation: "cites", to: citationId, sourceRefs: [item.id] });
    if (item.source.title) { const match = item.source.title.match(/^(.+?)\s+\((\d{4})\)\s*[-–:]\s*(.+)$/); if (match) { const author = match[1]!; const authorId = `author:${author.trim().toLowerCase()}`; add({ id: authorId, type: "author", label: author.trim(), sourceRefs: [item.id] }); edges.push({ id: `${authorId}->${workId}`, from: authorId, relation: "authored", to: workId, sourceRefs: [item.id] }); } }
  }
  for (const claim of claims) { const conceptId = `concept:${claim.id}`; add({ id: conceptId, type: "concept", label: claim.text, sourceRefs: claim.evidenceIds }); for (const evidenceId of claim.evidenceIds) { const workId = `work:${evidenceId}`; if (entities.has(workId)) edges.push({ id: `${workId}->${conceptId}`, from: workId, relation: "defines", to: conceptId, sourceRefs: [evidenceId] }); } if (claim.kind === "method") { const methodId = `method:${claim.id}`; add({ id: methodId, type: "method", label: claim.text, sourceRefs: claim.evidenceIds }); edges.push({ id: `${conceptId}->${methodId}`, from: conceptId, relation: "uses-method", to: methodId, sourceRefs: claim.evidenceIds }); } }
  return { schemaVersion: "psyclaw/knowledge-map/v1", entities: [...entities.values()], edges };
}
