export type KnowledgeEntityType = "author" | "work" | "citation" | "concept" | "method";
export type KnowledgeRelation = "authored" | "cites" | "defines" | "uses-method" | "related-to";
export interface KnowledgeEntity { id: string; type: KnowledgeEntityType; label: string; sourceRefs: string[]; }
export interface KnowledgeEdge { id: string; from: string; relation: KnowledgeRelation; to: string; sourceRefs: string[]; }
export interface KnowledgeMap { schemaVersion: "psyclaw/knowledge-map/v1"; entities: KnowledgeEntity[]; edges: KnowledgeEdge[]; }
