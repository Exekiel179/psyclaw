export const RESEARCH_DECISION_SCHEMA = "psyclaw/research-decision/v1" as const;

export type ResearchDecisionImpact =
  | "research-question"
  | "sample-treatment"
  | "operationalization"
  | "estimand"
  | "analysis-method"
  | "interpretation";

export interface ResearchDecisionOption {
  id: string;
  label: string;
  rationale: string;
  consequences: string[];
  evidenceRefs: string[];
}

export interface ResearchDecisionRequest {
  schemaVersion: typeof RESEARCH_DECISION_SCHEMA;
  id: string;
  question: string;
  options: ResearchDecisionOption[];
  affectedAreas: ResearchDecisionImpact[];
  evidenceCannotResolve: boolean;
  evidenceReviewed: string[];
  methodsChecked: string[];
  unresolvedReason: string;
  recommendation: string;
}

export interface ResearchDecisionAssessment {
  eligible: boolean;
  reasons: string[];
}

export interface ResearchDecisionResolution {
  schemaVersion: "psyclaw/research-decision-resolution/v1";
  decisionId: string;
  selectedOption: string;
  rationale: string;
  actor: "human";
  resolvedAt: string;
}

const IMPACTS = new Set<ResearchDecisionImpact>([
  "research-question",
  "sample-treatment",
  "operationalization",
  "estimand",
  "analysis-method",
  "interpretation",
]);

/**
 * The only gateway into `awaiting-human`. Operational authorization, missing
 * evidence, technical repair, formatting, and reporting omissions cannot
 * satisfy this contract because they do not present competing research
 * choices that alter a substantive part of the study.
 */
export function assessResearchDecision(value: unknown): ResearchDecisionAssessment {
  const reasons: string[] = [];
  if (!value || typeof value !== "object" || Array.isArray(value)) return { eligible: false, reasons: ["research decision must be an object"] };
  const candidate = value as Partial<ResearchDecisionRequest>;
  if (candidate.schemaVersion !== RESEARCH_DECISION_SCHEMA) reasons.push("research decision schema is not recognized");
  if (typeof candidate.id !== "string" || !candidate.id.trim()) reasons.push("research decision id is required");
  if (typeof candidate.question !== "string" || !candidate.question.trim()) reasons.push("research decision question is required");
  if (!Array.isArray(candidate.options) || candidate.options.length < 2) reasons.push("at least two defensible research options are required");
  if (candidate.evidenceCannotResolve !== true) reasons.push("available evidence or established methods can still resolve the choice");
  if (!Array.isArray(candidate.evidenceReviewed) || candidate.evidenceReviewed.length === 0 || candidate.evidenceReviewed.some((item) => typeof item !== "string" || !item.trim())) {
    reasons.push("reviewed evidence must be listed before requesting a researcher decision");
  }
  if (!Array.isArray(candidate.methodsChecked) || candidate.methodsChecked.length === 0 || candidate.methodsChecked.some((item) => typeof item !== "string" || !item.trim())) {
    reasons.push("applicable established methods must be checked before requesting a researcher decision");
  }
  if (typeof candidate.unresolvedReason !== "string" || !candidate.unresolvedReason.trim()) {
    reasons.push("the unresolved substantive disagreement must be explained");
  }
  if (!Array.isArray(candidate.affectedAreas) || candidate.affectedAreas.length === 0 || candidate.affectedAreas.some((area) => !IMPACTS.has(area))) {
    reasons.push("the choice must alter a recognized substantive research area");
  }

  const optionIds = new Set<string>();
  for (const option of candidate.options ?? []) {
    if (!option || typeof option !== "object" || Array.isArray(option)) {
      reasons.push("every research decision option must be an object");
      continue;
    }
    if (typeof option.id !== "string" || !option.id.trim() || typeof option.label !== "string" || !option.label.trim() || typeof option.rationale !== "string" || !option.rationale.trim()) reasons.push("every option requires an id, label, and rationale");
    if (!Array.isArray(option.consequences) || option.consequences.length === 0 || !option.consequences.every((item) => typeof item === "string" && Boolean(item.trim()))) reasons.push("every option requires at least one concrete consequence");
    if (!Array.isArray(option.evidenceRefs) || option.evidenceRefs.length === 0 || !option.evidenceRefs.every((item) => typeof item === "string" && Boolean(item.trim()))) reasons.push("every option requires at least one evidence or method reference");
    if (optionIds.has(option.id)) reasons.push(`duplicate research decision option: ${option.id}`);
    optionIds.add(option.id);
  }
  if (typeof candidate.recommendation !== "string" || !optionIds.has(candidate.recommendation)) reasons.push("a recommendation naming one supplied option is required");
  return { eligible: reasons.length === 0, reasons: [...new Set(reasons)] };
}

export function assertResearchDecision(value: unknown): asserts value is ResearchDecisionRequest {
  const assessment = assessResearchDecision(value);
  if (!assessment.eligible) throw new Error(`Invalid researcher decision request: ${assessment.reasons.join("; ")}`);
}

export function resolveResearchDecision(
  request: ResearchDecisionRequest,
  input: { selectedOption: string; rationale: string; resolvedAt?: string },
): ResearchDecisionResolution {
  assertResearchDecision(request);
  const selectedOption = input.selectedOption.trim();
  const rationale = input.rationale.trim();
  if (!request.options.some((option) => option.id === selectedOption)) throw new Error("selected option is not part of the research decision");
  if (!rationale) throw new Error("researcher rationale is required");
  return {
    schemaVersion: "psyclaw/research-decision-resolution/v1",
    decisionId: request.id,
    selectedOption,
    rationale,
    actor: "human",
    resolvedAt: input.resolvedAt ?? new Date().toISOString(),
  };
}
