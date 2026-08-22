export const CONTRACT_VERSION = "psyclaw/core/v1" as const;

export type Effect = "read" | "write" | "network" | "destructive";
export type EvidenceLevel = "metadata" | "abstract" | "snippet" | "fulltext" | "user";
export type ClaimStatus = "supported" | "uncertain" | "unsupported";
export type Relation = "supports" | "contradicts" | "context";
export type ResearchParadigm =
  | "survey-observational"
  | "qualitative-thematic"
  | "experimental"
  | "quasi-experimental"
  | "longitudinal-panel"
  | "meta-analysis"
  | "ethnographic"
  | "historical-documentary"
  | "policy-legal"
  | "mixed-methods";

export interface ResearchProject {
  id: string;
  root: string;
  paradigm: ResearchParadigm;
  goal: string;
  policyVersion: string;
  createdAt: string;
}

export interface SourceRef {
  kind: "doi" | "url" | "file" | "user" | "mcp";
  locator: string;
  title?: string;
}

export interface Evidence {
  id: string;
  source: SourceRef;
  level: EvidenceLevel;
  quote?: string;
  retrievedAt: string;
  sha256?: string;
  accessStatus: "verified" | "partial" | "unavailable";
  locators: EvidenceLocator[];
}

export interface EvidenceLocator {
  kind: "doi" | "url" | "file" | "page" | "section" | "offset" | "row";
  value: string;
}

export type ClaimKind = "existence" | "definition" | "method" | "result" | "interpretation";

export interface Claim {
  recordType?: "claim";
  id: string;
  text: string;
  kind: ClaimKind;
  evidenceIds: string[];
  status: ClaimStatus;
  uncertainty?: string;
}

export interface ClaimEvidenceLink {
  recordType?: "claim-evidence-link";
  claimId: string;
  evidenceId: string;
  relation: Relation;
  locator?: EvidenceLocator;
  rationale: string;
}

export interface EvidencePolicy {
  paradigm: ResearchParadigm;
  claimKind: ClaimKind;
  minimumLevel: EvidenceLevel;
  locatorRequired: boolean;
  requiresIndependentSource: boolean;
  requiresArtifactRun: boolean;
}

export interface Artifact {
  id: string;
  path: string;
  sha256: string;
  producedBy: string;
  inputIds: string[];
  reproducible: boolean;
}

export interface ToolReceipt {
  schemaVersion: "psyclaw/tool-receipt/v1";
  runId: string;
  taskId: string;
  tool: string;
  effect: Effect;
  approval: "not-needed" | "approved" | "denied";
  idempotencyKey?: string;
  ok: boolean;
  /** Stable, non-sensitive diagnostic code for a denied or failed call. */
  reasonCode?: string;
  resultHash?: string;
  startedAt: string;
  finishedAt: string;
}

export interface GateResult {
  gateId: string;
  ok: boolean;
  severity: "block" | "warn";
  reason: string;
  claimIds?: string[];
  evidenceIds?: string[];
}

export interface MemoryRecord {
  id: string;
  kind: "profile" | "decision" | "fact" | "lesson" | "evidence";
  scope: "session" | "project" | "user";
  content: unknown;
  sourceRefs: string[];
  confidence: number;
  status: "pending" | "active" | "archived";
  createdAt: string;
  updatedAt: string;
}

export interface Handoff {
  schemaVersion: "psyclaw/handoff/v1";
  projectId: string;
  runId: string;
  goal: string;
  completed: string[];
  verified: string[];
  blocked: string[];
  nextSteps: string[];
  verificationCommands: string[];
  generatedAt: string;
}

export interface ResearchRequest {
  goal: string;
  paradigm: ResearchParadigm;
  output: "brief" | "ledger";
  sourcePaths: string[];
}
