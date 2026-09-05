export const ARS_REVIEW_SEATS = ["EIC", "R1", "R2", "R3", "DA"] as const;
export type ArsReviewSeat = typeof ARS_REVIEW_SEATS[number];
export type ArsBridgeMode = "reviewer_full" | "reviewer_re_review";

export interface ArsPanelRequest {
  mode: ArsBridgeMode;
  manuscriptPath?: string;
  originalManuscriptPath?: string;
  roadmapPath?: string;
  authorAdjudicationPath?: string;
  revisionEvidenceBundlePath?: string;
  responseLetterPath?: string;
  editorialDecisionPath?: string;
  round1FindingsPath?: string;
  reviewerCardsPath?: string;
  revisionPatchPaths?: string[];
  applyReportPaths?: string[];
  resumeRunId?: string;
  title?: string;
  field?: string;
  reviewerCards?: string;
  passportDigest?: string;
}

export interface ArsSeatResult {
  schemaVersion: "psyclaw/ars-seat-result/v1";
  seat: ArsReviewSeat;
  role: string;
  contextId: string;
  provider: string | null;
  modelFamily: string | null;
  peerOutputsVisible: false;
  phase1: string;
  phase1Sha256: string;
  phase2: string;
  phase2Sha256: string;
  outcome: "succeeded";
}

export interface ArsPanelResult {
  schemaVersion: "psyclaw/ars-panel-result/v1";
  mode: ArsBridgeMode;
  runId: string;
  status: "completed" | "blocked";
  inputDigest: string;
  upstreamRef: string;
  upstreamCommit: string;
  contractSha256?: string;
  manuscriptSha256: string;
  seatResults?: ArsSeatResult[];
  synthesis?: string;
  synthesisSha256?: string;
  provenancePath?: string;
  provenanceCarrierPath?: string;
  outputRoot: string;
  diagnostics: string[];
  independenceClaim: "process-separated-not-independent-errors";
}
