import { readFile } from "node:fs/promises";
import { appendJsonl, readJsonl } from "../project/jsonl.js";
import { projectPaths } from "../project/paths.js";
import { asClaim, asClaimEvidenceLink, asEvidence, asProject } from "../core/schemas.js";
import { CONTRACT_VERSION, type Claim, type ClaimEvidenceLink, type Evidence, type ResearchParadigm, type ResearchProject } from "../core/contracts.js";

const PARADIGM_ALIASES: Readonly<Record<string, ResearchParadigm>> = {
  survey: "survey-observational",
  observational: "survey-observational",
  quantitative: "survey-observational",
  qualitative: "qualitative-thematic",
  thematic: "qualitative-thematic",
  experiment: "experimental",
  quasi_experimental: "quasi-experimental",
  longitudinal: "longitudinal-panel",
  meta_analysis: "meta-analysis",
  ethnography: "ethnographic",
  historical: "historical-documentary",
  policy: "policy-legal",
  mixed: "mixed-methods",
};

function normalizeProjectRecord(value: unknown, root: string): unknown {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return value;
  const record = value as Record<string, unknown>;
  const rawParadigm = typeof record.paradigm === "string" ? record.paradigm.trim().toLowerCase() : "";
  const paradigm = PARADIGM_ALIASES[rawParadigm] ?? rawParadigm;
  return {
    id: record.id ?? record.projectId,
    root: record.root ?? root,
    paradigm,
    goal: record.goal ?? record.researchGoal ?? record.research_question,
    policyVersion: record.policyVersion ?? record.schemaVersion ?? CONTRACT_VERSION,
    createdAt: record.createdAt ?? record.created_at,
  };
}

export function asCompatibleProject(value: unknown, root: string): ResearchProject {
  try {
    return asProject(normalizeProjectRecord(value, root));
  } catch (error) {
    const paradigm = typeof value === "object" && value !== null && "paradigm" in value
      ? String((value as { paradigm?: unknown }).paradigm ?? "")
      : "";
    if (paradigm) {
      throw new Error(`无法识别旧项目的研究范式 '${paradigm}'。请在 .psyclaw/project.json 中改为 survey-observational、qualitative-thematic、experimental、quasi-experimental、longitudinal-panel、meta-analysis、ethnographic、historical-documentary、policy-legal 或 mixed-methods。`);
    }
    throw error;
  }
}

export interface LedgerSnapshot {
  evidence: Evidence[];
  claims: Claim[];
  links: ClaimEvidenceLink[];
}

export async function loadLedger(root: string): Promise<LedgerSnapshot> {
  const paths = projectPaths(root);
  const evidence = (await readJsonl<unknown>(paths.evidence)).map((value) => asEvidence(value));
  const claims: Claim[] = [];
  const links: ClaimEvidenceLink[] = [];
  for (const value of await readJsonl<unknown>(paths.claims)) {
    if (typeof value !== "object" || value === null) throw new Error("Invalid claims record");
    if ("relation" in value && "claimId" in value && "evidenceId" in value) {
      links.push(asClaimEvidenceLink(value));
    } else {
      claims.push(asClaim(value));
    }
  }
  return {
    evidence,
    claims,
    links,
  };
}

export async function appendEvidence(root: string, evidence: Evidence): Promise<void> {
  asEvidence(evidence);
  await appendJsonl(projectPaths(root).evidence, evidence);
}

export async function appendClaim(root: string, claim: Claim): Promise<void> {
  await appendJsonl(projectPaths(root).claims, asClaim({ ...claim, recordType: "claim" }));
}

export async function appendClaimEvidenceLink(root: string, link: ClaimEvidenceLink): Promise<void> {
  await appendJsonl(projectPaths(root).claims, asClaimEvidenceLink({ ...link, recordType: "claim-evidence-link" }));
}

export async function readProjectGoal(root: string): Promise<string> {
  const project = asCompatibleProject(JSON.parse(await readFile(projectPaths(root).project, "utf8")), root);
  return project.goal;
}

export async function readProject(root: string) {
  return asCompatibleProject(JSON.parse(await readFile(projectPaths(root).project, "utf8")), root);
}
