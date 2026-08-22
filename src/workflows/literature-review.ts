import { checkEvidenceSufficiency } from "../core/evidence-policy.js";
import { loadLedger, readProject } from "../research/ledger.js";
import { buildKnowledgeMap } from "../knowledge-map/index.js";
import { allParadigms, finalizeWorkflow, type WorkflowResult, type WorkflowSpec } from "./spec.js";

export const literatureReviewSpec: WorkflowSpec = {
  id: "literature-review",
  version: "1.0.0",
  description: "Aggregate the evidence ledger into a review matrix with conflicts and gaps.",
  paradigms: allParadigms,
  steps: [
    { id: "capture", role: "researcher", effect: "read", description: "load sources and claims" },
    { id: "audit", role: "critic", effect: "read", description: "evidence sufficiency and conflict disclosure" },
    { id: "write", role: "writer", effect: "write", description: "write review matrix and markdown" },
  ],
  requiredArtifacts: ["literature-review.md", "review-matrix.json", "knowledge-map.json"],
};

export async function runLiteratureReview(root: string): Promise<WorkflowResult> {
  const project = await readProject(root);
  const ledger = await loadLedger(root);
  const gates = checkEvidenceSufficiency({ ...ledger, paradigm: project.paradigm });
  if (ledger.evidence.length === 0) {
    gates.push({ gateId: "review:sources", ok: false, severity: "block", reason: "no sources recorded" });
  }

  const matrix = {
    schemaVersion: "psyclaw/review-matrix/v1",
    sources: ledger.evidence.map((item) => ({
      id: item.id,
      locator: item.source.locator,
      level: item.level,
      accessStatus: item.accessStatus,
    })),
    claims: ledger.claims.map((item) => ({
      id: item.id,
      kind: item.kind,
      status: item.status,
      evidenceIds: item.evidenceIds,
    })),
    conflicts: ledger.links
      .filter((link) => link.relation === "contradicts")
      .map((link) => ({ claimId: link.claimId, evidenceId: link.evidenceId })),
    gaps: gates.filter((gate) => !gate.ok).map((gate) => gate.reason),
  };
  const knowledgeMap = buildKnowledgeMap(ledger.evidence, ledger.claims);

  const markdown = [
    "# Literature Review",
    "",
    `Research goal: ${project.goal}`,
    "",
    "## Sources",
    "",
    ...(matrix.sources.length ? matrix.sources.map((item) => `- [${item.level}] ${item.locator}`) : ["- None"]),
    "",
    "## Claims",
    "",
    ...(matrix.claims.length ? matrix.claims.map((item) => `- (${item.kind}) ${item.status}: ${item.id}`) : ["- None"]),
    "",
    "## Conflicts",
    "",
    ...(matrix.conflicts.length ? matrix.conflicts.map((item) => `- ${item.claimId} vs ${item.evidenceId}`) : ["- None"]),
    "",
    "## Gaps",
    "",
    ...(matrix.gaps.length ? matrix.gaps.map((item) => `- ${item}`) : ["- None"]),
    "",
  ].join("\n");

  return finalizeWorkflow(root, literatureReviewSpec, {
    gates,
    outputs: [
      { path: "literature-review.md", contents: markdown },
      { path: "review-matrix.json", contents: `${JSON.stringify(matrix, null, 2)}\n` },
      { path: "knowledge-map.json", contents: `${JSON.stringify(knowledgeMap, null, 2)}\n` },
    ],
    completed: ["sources loaded", "claims aggregated", "conflicts and gaps disclosed"],
  });
}
