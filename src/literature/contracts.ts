import type { EvidenceLevel } from "../core/contracts.js";
import type { Evidence } from "../core/contracts.js";

export type LiteratureRequestMode = "browser" | "api";
export interface InstitutionalRequestPlan {
  schemaVersion: "psyclaw/institutional-request-plan/v1";
  mode: LiteratureRequestMode;
  target: { value: string; kind: "doi" | "publisher-url" | "title-or-query" };
  allowedDomains: string[];
  api?: { method: "GET"; url: string; headers: Record<string, string>; response: "pdf-or-html" | "metadata" };
  approval: { required: true; before: ("network" | "download" | "ledger-record")[]; status: "pending" | "approved" | "denied" };
  stopConditions: string[];
}
export interface MetadataCandidate { title?: string; doi?: string; authors?: string[]; source: "pdf" | "html" | "title-doi"; }
export interface MetadataCrossCheck { schemaVersion: "psyclaw/metadata-cross-check/v1"; match: boolean; confidence: "high" | "medium" | "low"; normalizedDoi?: string; titleMatch: boolean; doiMatch: boolean; reasons: string[]; }
export interface VerifiedFulltextRecord { evidence: Evidence; crossCheck: MetadataCrossCheck; contentType: "pdf" | "html"; sha256: string; approval: "approved"; }

export type AccessDecision = "pending" | "approved" | "denied" | "verified";

export interface InstitutionalAccessRequest {
  schemaVersion: "psyclaw/institutional-access/v1";
  requestId: string;
  identifier: string;
  identifierKind: "doi" | "url" | "title";
  authorization: "user-authenticated" | "institutional-license";
  browserSession: "existing-visible-session";
  approval: AccessDecision;
  createdAt: string;
}

export interface VerifiedFulltext {
  schemaVersion: "psyclaw/verified-fulltext/v1";
  path: string;
  sha256: string;
  bytes: number;
  contentType: "application/pdf";
  sourceLocator: string;
  access: "institutional-authorized" | "user-provided";
  verifiedAt: string;
  titleMatch: "verified" | "not-checked";
  doiMatch: "verified" | "not-checked";
}

export interface LiteratureLedgerEntry {
  schemaVersion: "psyclaw/literature-ledger/v1";
  id: string;
  kind: "work" | "evidence" | "artifact" | "claim";
  workId: string;
  title?: string;
  authors?: string[];
  doi?: string;
  sourceLocator: string;
  evidenceLevel: EvidenceLevel;
  verification: "unverified" | "verified" | "uncertain";
  evidenceIds: string[];
  artifactIds: string[];
  recordedAt: string;
}

export interface KnowledgeNode {
  id: string;
  type: "work" | "person" | "concept" | "method" | "dataset" | "claim";
  label: string;
  verified: boolean;
  sourceIds: string[];
}

export interface KnowledgeEdge {
  id: string;
  subject: string;
  predicate: "authored-by" | "cites" | "uses-method" | "studies" | "supports" | "contradicts" | "related-to";
  object: string;
  sourceIds: string[];
  verified: boolean;
}

export interface VerifiedKnowledgeMap {
  schemaVersion: "psyclaw/knowledge-map/v1";
  nodes: KnowledgeNode[];
  edges: KnowledgeEdge[];
  generatedAt: string;
  sourceLedgerHash: string;
}
