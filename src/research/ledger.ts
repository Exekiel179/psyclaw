import { readFile } from "node:fs/promises";
import { appendJsonl, readJsonl } from "../project/jsonl.js";
import { projectPaths } from "../project/paths.js";
import { asClaim, asClaimEvidenceLink, asEvidence, asProject } from "../core/schemas.js";
import type { Claim, ClaimEvidenceLink, Evidence } from "../core/contracts.js";

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
  const project = asProject(JSON.parse(await readFile(projectPaths(root).project, "utf8")));
  return project.goal;
}

export async function readProject(root: string) {
  return asProject(JSON.parse(await readFile(projectPaths(root).project, "utf8")));
}
