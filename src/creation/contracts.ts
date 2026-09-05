import type { AgentRole } from "../orchestration/contracts.js";
import type { AnalysisHookEvent, AnalysisHookSeverity } from "../analysis/hooks.js";

export type CreationKind = "skill" | "hook" | "rule" | "subagent";

export interface CreationRequest {
  kind: CreationKind;
  id: string;
  description: string;
  instructions?: string;
  event?: AnalysisHookEvent;
  severity?: AnalysisHookSeverity;
  pattern?: string;
  pathPrefix?: string;
  role?: AgentRole;
}

export interface CreationPreview {
  schemaVersion: "psyclaw/creation-preview/v1";
  kind: CreationKind;
  id: string;
  path: string;
  contents: string;
  sha256: string;
  replacesExisting: false;
}

export interface CreationReceipt {
  schemaVersion: "psyclaw/tool-receipt/v1";
  runId: string;
  taskId: string;
  tool: "creation.apply";
  effect: "write";
  approval: "approved";
  idempotencyKey: string;
  ok: true;
  resultHash: string;
  startedAt: string;
  finishedAt: string;
  path: string;
  kind: CreationKind;
}
