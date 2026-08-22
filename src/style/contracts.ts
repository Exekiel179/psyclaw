export const STYLE_CONTRACT_VERSION = "psyclaw/style-contract/v1" as const;

export type ArtifactKind = "figure" | "table" | "manuscript";

export interface JournalProfile {
  id: string;
  name: string;
  source: string;
  ref: string;
  version: string;
  license: string;
  /** Profiles are descriptive until their rules have been independently verified. */
  status?: "verified" | "unverified" | "degraded";
  rules?: Readonly<Record<string, unknown>>;
}

export interface StyleCheckFinding {
  rule: string;
  severity: "block" | "warn";
  message: string;
}

export interface StyleCheckResult {
  schemaVersion: typeof STYLE_CONTRACT_VERSION;
  ok: boolean;
  findings: StyleCheckFinding[];
}

export interface ArtifactIdentity {
  kind: ArtifactKind;
  slug: string;
  version: string;
  extension: string;
}

export interface ReproducibilityCheck {
  scriptPath?: string;
  scriptSha256?: string;
  inputHashes?: Readonly<Record<string, string>>;
}
