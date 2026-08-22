import { Type, type Static } from "typebox";
import { Compile } from "typebox/compile";

/** The smallest independent panel used for a bounded manuscript review. */
export type ExpertReviewRole =
  | "methodologist"
  | "evidence-critic"
  | "writing-editor"
  | "devil-advocate"
  | "ethics-reviewer"
  | "reproducibility-reviewer";

export type ExpertReviewSeverity = "block" | "major" | "minor" | "note";
export type ExpertReviewDisposition = "accept" | "revise" | "reject" | "uncertain";

export interface ExpertReviewFinding {
  id: string;
  severity: ExpertReviewSeverity;
  rule: string;
  message: string;
  /** A finding must point to an input, claim, or artifact when one exists. */
  refs: string[];
  disposition: ExpertReviewDisposition;
}

export interface ExpertReviewOpinion {
  schemaVersion: "psyclaw/expert-review-opinion/v1";
  runId: string;
  taskId: string;
  dispatchId: string;
  expertId: string;
  role: ExpertReviewRole;
  outcome: "complete" | "blocked" | "uncertain";
  summary: string;
  findings: ExpertReviewFinding[];
  /** Empty is valid only when the expert explicitly reports no findings. */
  evidenceRefs: string[];
}

export interface ExpertReviewContract {
  schemaVersion: "psyclaw/expert-review/v1";
  runId: string;
  subject: { kind: "manuscript" | "artifact" | "workflow"; ref: string };
  inputRefs: string[];
  experts: { expertId: string; role: ExpertReviewRole; taskId: string }[];
  requiredRoles: ExpertReviewRole[];
  minOpinions: number;
  independent: true;
  output: { artifactPath: string; verdictPath: string };
}

export interface ExpertReviewResult {
  schemaVersion: "psyclaw/expert-review-result/v1";
  runId: string;
  verdict: "pass" | "blocked" | "uncertain";
  opinions: ExpertReviewOpinion[];
  findings: ExpertReviewFinding[];
  unresolvedRoles: ExpertReviewRole[];
  /** Aggregation is a report only; it never upgrades an unsupported finding. */
  blockReasons: string[];
}

const Role = Type.Union([
  Type.Literal("methodologist"),
  Type.Literal("evidence-critic"),
  Type.Literal("writing-editor"),
  Type.Literal("devil-advocate"),
  Type.Literal("ethics-reviewer"),
  Type.Literal("reproducibility-reviewer"),
]);
const Finding = Type.Object({
  id: Type.String({ minLength: 1 }),
  severity: Type.Union([Type.Literal("block"), Type.Literal("major"), Type.Literal("minor"), Type.Literal("note")]),
  rule: Type.String({ minLength: 1 }),
  message: Type.String({ minLength: 1 }),
  refs: Type.Array(Type.String()),
  disposition: Type.Union([Type.Literal("accept"), Type.Literal("revise"), Type.Literal("reject"), Type.Literal("uncertain")]),
}, { additionalProperties: false });

export const ExpertReviewOpinionSchema = Type.Object({
  schemaVersion: Type.Literal("psyclaw/expert-review-opinion/v1"),
  runId: Type.String({ minLength: 1 }), taskId: Type.String({ minLength: 1 }), dispatchId: Type.String({ minLength: 1 }),
  expertId: Type.String({ minLength: 1 }), role: Role,
  outcome: Type.Union([Type.Literal("complete"), Type.Literal("blocked"), Type.Literal("uncertain")]),
  summary: Type.String({ minLength: 1 }), findings: Type.Array(Finding), evidenceRefs: Type.Array(Type.String()),
}, { additionalProperties: false });

export const ExpertReviewContractSchema = Type.Object({
  schemaVersion: Type.Literal("psyclaw/expert-review/v1"), runId: Type.String({ minLength: 1 }),
  subject: Type.Object({ kind: Type.Union([Type.Literal("manuscript"), Type.Literal("artifact"), Type.Literal("workflow")]), ref: Type.String({ minLength: 1 }) }, { additionalProperties: false }),
  inputRefs: Type.Array(Type.String()),
  experts: Type.Array(Type.Object({ expertId: Type.String({ minLength: 1 }), role: Role, taskId: Type.String({ minLength: 1 }) }, { additionalProperties: false }), { minItems: 1 }),
  requiredRoles: Type.Array(Role, { minItems: 1 }), minOpinions: Type.Integer({ minimum: 1 }), independent: Type.Literal(true),
  output: Type.Object({ artifactPath: Type.String({ minLength: 1 }), verdictPath: Type.String({ minLength: 1 }) }, { additionalProperties: false }),
}, { additionalProperties: false });

export const ExpertReviewResultSchema = Type.Object({
  schemaVersion: Type.Literal("psyclaw/expert-review-result/v1"), runId: Type.String({ minLength: 1 }),
  verdict: Type.Union([Type.Literal("pass"), Type.Literal("blocked"), Type.Literal("uncertain")]),
  opinions: Type.Array(ExpertReviewOpinionSchema), findings: Type.Array(Finding), unresolvedRoles: Type.Array(Role), blockReasons: Type.Array(Type.String()),
}, { additionalProperties: false });

const contractValidator = Compile(ExpertReviewContractSchema);
const opinionValidator = Compile(ExpertReviewOpinionSchema);
const resultValidator = Compile(ExpertReviewResultSchema);

export function validateExpertReviewContract(value: unknown): ExpertReviewContract {
  if (!contractValidator.Check(value)) throw new Error("invalid psyclaw/expert-review/v1 contract");
  const contract = value as Static<typeof ExpertReviewContractSchema>;
  const expertRoles = new Set(contract.experts.map((expert) => expert.role));
  if (contract.minOpinions > contract.experts.length) throw new Error("minOpinions exceeds configured experts");
  if (contract.requiredRoles.some((role) => !expertRoles.has(role))) throw new Error("required role has no configured expert");
  if (new Set(contract.requiredRoles).size !== contract.requiredRoles.length) throw new Error("duplicate required role");
  if (new Set(contract.experts.map((expert) => expert.expertId)).size !== contract.experts.length) throw new Error("duplicate expertId");
  return contract as ExpertReviewContract;
}

export function validateExpertReviewOpinion(value: unknown): ExpertReviewOpinion {
  if (!opinionValidator.Check(value)) throw new Error("invalid psyclaw/expert-review-opinion/v1 opinion");
  return value as ExpertReviewOpinion;
}

export function validateExpertReviewResult(value: unknown): ExpertReviewResult {
  if (!resultValidator.Check(value)) throw new Error("invalid psyclaw/expert-review-result/v1 result");
  return value as ExpertReviewResult;
}

/**
 * Deterministically combines independent opinions. It does not infer a
 * finding from a vote and never upgrades an uncertain or blocked opinion.
 */
export function aggregateExpertReview(
  contractValue: unknown,
  opinionValues: readonly unknown[],
): ExpertReviewResult {
  const contract = validateExpertReviewContract(contractValue);
  const opinions = opinionValues.map(validateExpertReviewOpinion);
  const blockReasons: string[] = [];
  const configured = new Map(contract.experts.map((expert) => [expert.expertId, expert]));
  const seen = new Set<string>();

  for (const opinion of opinions) {
    if (opinion.runId !== contract.runId) blockReasons.push(`opinion ${opinion.expertId} belongs to another run`);
    const expert = configured.get(opinion.expertId);
    if (!expert) blockReasons.push(`unconfigured expert: ${opinion.expertId}`);
    else if (expert.role !== opinion.role || expert.taskId !== opinion.taskId) blockReasons.push(`opinion identity mismatch: ${opinion.expertId}`);
    if (seen.has(opinion.expertId)) blockReasons.push(`duplicate opinion: ${opinion.expertId}`);
    seen.add(opinion.expertId);
    if (opinion.outcome === "blocked") blockReasons.push(`expert blocked: ${opinion.expertId}`);
  }

  const roles = new Set(opinions.map((opinion) => opinion.role));
  const unresolvedRoles = contract.requiredRoles.filter((role) => !roles.has(role));
  if (opinions.length < contract.minOpinions) blockReasons.push("minimum opinion count not met");
  if (unresolvedRoles.length > 0) blockReasons.push(`missing required roles: ${unresolvedRoles.join(", ")}`);

  const findings = opinions.flatMap((opinion) => opinion.findings);
  if (findings.some((finding) => finding.severity === "block")) blockReasons.push("blocking finding reported");
  const uncertain = opinions.some((opinion) => opinion.outcome === "uncertain") || findings.some((finding) => finding.disposition === "uncertain");
  return {
    schemaVersion: "psyclaw/expert-review-result/v1",
    runId: contract.runId,
    verdict: blockReasons.length > 0 ? "blocked" : uncertain ? "uncertain" : "pass",
    opinions,
    findings,
    unresolvedRoles,
    blockReasons,
  };
}
