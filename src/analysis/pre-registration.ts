import { readFile } from "node:fs/promises";
import { join } from "node:path";
import type { GateResult, ResearchParadigm } from "../core/contracts.js";
import { validateAnalysisPlan, type AnalysisPlanContract } from "./hooks.js";

/**
 * A recorded analysis plan preserves the exploratory/confirmatory boundary.
 * Exploratory work may proceed without a preregistration record. For an
 * explicitly confirmatory study, missing pre-specification is disclosed as a
 * limitation and repaired prospectively where possible; a public registry URL
 * is not required by PsyClaw.
 */
export interface PreRegistration extends AnalysisPlanContract {
  schemaVersion: "psyclaw/pre-registration/v1";
  registeredAt?: string;
  hypotheses?: string[];
}

export const PRE_REGISTRATION_VERSION = "psyclaw/pre-registration/v1" as const;

export function preRegistrationPath(root: string): string {
  return join(root, ".psyclaw", "pre-registration.json");
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

export async function readPreRegistration(root: string): Promise<PreRegistration | undefined> {
  try {
    const value = JSON.parse(await readFile(preRegistrationPath(root), "utf8")) as unknown;
    if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
    const plan = value as Partial<PreRegistration>;
    if (plan.schemaVersion !== PRE_REGISTRATION_VERSION) return undefined;
    const hypotheses = Array.isArray(plan.hypotheses)
      ? plan.hypotheses.filter((item): item is string => typeof item === "string")
      : [];
    const exploratory = Array.isArray(plan.exploratoryAnalyses)
      ? plan.exploratoryAnalyses.filter((item): item is string => typeof item === "string")
      : [];
    const result: PreRegistration = {
      schemaVersion: PRE_REGISTRATION_VERSION,
      confirmatory: plan.confirmatory === true,
      exploratoryAnalyses: exploratory,
    };
    const primaryOutcome = asString(plan.primaryOutcome);
    if (primaryOutcome !== undefined) result.primaryOutcome = primaryOutcome;
    const primaryAnalysis = asString(plan.primaryAnalysis);
    if (primaryAnalysis !== undefined) result.primaryAnalysis = primaryAnalysis;
    const missingDataPlan = asString(plan.missingDataPlan);
    if (missingDataPlan !== undefined) result.missingDataPlan = missingDataPlan;
    const multiplicityPlan = asString(plan.multiplicityPlan);
    if (multiplicityPlan !== undefined) result.multiplicityPlan = multiplicityPlan;
    const exclusionCriteria = asString(plan.exclusionCriteria);
    if (exclusionCriteria !== undefined) result.exclusionCriteria = exclusionCriteria;
    const stoppingRule = asString(plan.stoppingRule);
    if (stoppingRule !== undefined) result.stoppingRule = stoppingRule;
    const registeredAt = asString(plan.registeredAt);
    if (registeredAt !== undefined) result.registeredAt = registeredAt;
    if (hypotheses.length > 0) result.hypotheses = hypotheses;
    return result;
  } catch {
    return undefined;
  }
}

/** Pre-registration of numeric outcomes does not apply to these paradigms. */
const LENIENT_PARADIGMS = new Set<ResearchParadigm>([
  "qualitative-thematic",
  "ethnographic",
  "historical-documentary",
  "policy-legal",
]);

/** Convert the pre-registration check into evidence-style gates. */
export function checkPreRegistration(plan: PreRegistration | undefined, paradigm?: ResearchParadigm): GateResult[] {
  if (paradigm !== undefined && LENIENT_PARADIGMS.has(paradigm)) return [];
  if (plan === undefined) {
    return [{
      gateId: "analysis:pre-registration",
      ok: true,
      severity: "warn",
      reason: "尚无事前分析方案记录。若本次工作是在查看数据后形成问题，请按探索性分析继续并如实说明；只有明确的确证性研究才需核对事先确定的主要指标、分析方法、缺失值处理、多重比较和排除标准，无需提供公开链接。",
    }];
  }
  const result = validateAnalysisPlan(plan);
  return result.findings.map((finding) => ({
    gateId: `analysis:pre-registration:${finding.rule}`,
    ok: finding.severity !== "block",
    severity: finding.severity,
    reason: finding.message,
  }));
}
