/** The descriptor is the only object needed by a router during discovery. */
export const SKILL_DESCRIPTOR_VERSION = "psyclaw/skill-descriptor/v1" as const;

export type SkillLicenseStatus =
  | "verified"
  | "declared"
  | "missing"
  | "invalid"
  | "unknown";

export type SkillDependencyStatus =
  | "ready"
  | "declared"
  | "missing"
  | "blocked"
  | "unknown";

export type SkillTrustStatus = "trusted" | "untrusted" | "blocked" | "unknown";
export type SkillRiskLevel = "low" | "medium" | "high" | "critical" | "unknown";

/**
 * Host-side approval is deliberately separate from descriptor metadata.
 * A skill may describe itself as `trusted`, but only an approval supplied by
 * the host can move it out of discover-only mode.
 */
export type SkillApprovalStatus = "discover-only" | "approved" | "blocked" | "stale";

/**
 * Host-generated supply-chain evidence.  These fields deliberately live
 * outside SKILL.md frontmatter: a skill cannot certify its own license,
 * dependency audit, or SBOM.
 */
export interface SkillAdmissionEvidence {
  schemaVersion: "psyclaw/skill-admission/v1";
  contentSha256: string;
  licenseSpdx: string;
  licenseEvidenceRef: string;
  dependencyEvidenceRef: string;
  sbomSha256: string;
}

export interface SkillApproval {
  /** `false` is an explicit deny and takes precedence over every other field. */
  approved: boolean;
  /** Optional content pin. When present, it must match the discovered SHA. */
  sha256?: string;
  /** Optional logical path pin, resolved relative to the process cwd. */
  sourcePath?: string;
  /** Optional canonical path pin. Useful for lock/manifest based approvals. */
  resolvedPath?: string;
  /** Required host-side manifest/SBOM attestation for execution. */
  admission?: SkillAdmissionEvidence;
}

export type SkillApprovalEntry = boolean | SkillApproval;
export type SkillApprovalMap =
  | Readonly<Record<string, SkillApprovalEntry>>
  | ReadonlyMap<string, SkillApprovalEntry>;

export interface SkillDescriptor {
  schemaVersion: typeof SKILL_DESCRIPTOR_VERSION;
  /** Stable id used by routing and explicit load/enable operations. */
  id: string;
  name: string;
  description: string;
  /** Absolute path as discovered from the caller-provided root. */
  sourcePath: string;
  /** Canonical path used for reads; never a symlink. */
  resolvedPath: string;
  /** Canonical root under which the skill was discovered. */
  rootPath: string;
  /** SHA-256 of the complete SKILL.md file, including frontmatter. */
  sha256: string;
  licenseStatus: SkillLicenseStatus;
  dependencyStatus: SkillDependencyStatus;
  /** Metadata-derived trust; never sufficient for execution by itself. */
  trust: SkillTrustStatus;
  risk: SkillRiskLevel;
  /** Host approval state. `discover-only` is the secure default. */
  approvalStatus: SkillApprovalStatus;
  /** Runtime routing toggle; always false after discovery until explicitly enabled. */
  enabled: boolean;
  /** Duplicate ids are retained and marked instead of being overwritten. */
  conflicted: boolean;
  /** YAML frontmatter only. It never contains the Markdown body. */
  metadata: Readonly<Record<string, unknown>>;
}

export interface LoadedSkill extends SkillDescriptor {
  /** Markdown after the YAML frontmatter delimiter. */
  body: string;
}

export type SkillDiagnosticSeverity = "warning" | "error";

export type SkillDiagnosticCode =
  | "root-not-found"
  | "root-not-directory"
  | "root-symlink"
  | "path-traversal"
  | "symlink-path"
  | "invalid-frontmatter"
  | "invalid-metadata"
  | "read-error"
  | "hash-error"
  | "duplicate-id"
  | "not-found"
  | "ambiguous-id"
  | "blocked-skill"
  | "suspicious-body";

export interface SkillDiagnostic {
  code: SkillDiagnosticCode;
  severity: SkillDiagnosticSeverity;
  message: string;
  path?: string;
  skillId?: string;
  relatedPaths?: string[];
}

export interface SkillDiscoveryReport {
  skills: SkillDescriptor[];
  diagnostics: SkillDiagnostic[];
}

export interface SkillRegistryOptions {
  roots?: string[];
  /** Explicit id allowlist. This is shorthand for `{ [id]: true }`. */
  approvedIds?: readonly string[];
  /** Explicit host approvals, optionally pinned to content and paths. */
  approvals?: SkillApprovalMap;
  /** Descriptive alias for `approvals` when loading a trust manifest. */
  approvalMap?: SkillApprovalMap;
  /** Backwards-compatible singular alias for `approvals`. */
  approval?: SkillApprovalMap;
  /**
   * Deprecated compatibility option. Frontmatter `enabledByDefault` never
   * grants host approval and this option is intentionally ignored.
   */
  enableByDefault?: boolean;
}

export interface SkillSearchOptions {
  enabledOnly?: boolean;
  limit?: number;
}
