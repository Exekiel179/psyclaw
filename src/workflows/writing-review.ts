import { checkEvidenceSufficiency } from "../core/evidence-policy.js";
import { loadLedger, readProject } from "../research/ledger.js";
import { allParadigms, finalizeWorkflow, type WorkflowResult, type WorkflowSpec } from "./spec.js";
import { allocateProjectVersion } from "../project/versions.js";

export const writingReviewSpec: WorkflowSpec = {
  id: "writing-review",
  version: "1.0.0",
  description: "Audit drafted claims against evidence, honesty, and causal-language rules.",
  paradigms: allParadigms,
  steps: [
    { id: "read", role: "verifier", effect: "read", description: "load claims and evidence" },
    { id: "check", role: "critic", effect: "read", description: "honesty and causal-language heuristics" },
    { id: "write", role: "writer", effect: "write", description: "write findings report" },
  ],
  requiredArtifacts: ["writing-review.md", "review-findings.json", "review-suggestions.json"],
};

export interface ReviewFinding {
  severity: "block" | "warn";
  rule: string;
  claimId?: string;
  message: string;
}

export interface ReviewSuggestion { severity: "block" | "warn"; rule: string; claimId?: string; suggestion: string; }

const CAUSAL_PATTERN = /\b(?:causes?|leads? to|determines?|increases?|decreases?|drives?|improves?)\b/i;
const CONFIRMATORY_PATTERN = /\b(?:proves?|proven|established)\b/i;

export async function runWritingReview(root: string): Promise<WorkflowResult> {
  const project = await readProject(root);
  const ledger = await loadLedger(root);
  const gates = checkEvidenceSufficiency({ ...ledger, paradigm: project.paradigm });
  const version = await allocateProjectVersion(root, "manuscript-revision", `writing-review:${Date.now()}`);
  const gateByClaim = new Map(gates.map((gate) => [gate.claimIds?.[0], gate]));

  const findings: ReviewFinding[] = [];
  for (const claim of ledger.claims) {
    const gate = gateByClaim.get(claim.id);
    if (claim.status === "supported" && gate && !gate.ok) {
      findings.push({
        severity: "block",
        rule: "unsupported-claim-asserted-as-supported",
        claimId: claim.id,
        message: `claim ${claim.id} is marked supported but fails its evidence gate`,
      });
    }
    if (claim.kind !== "result" && CAUSAL_PATTERN.test(claim.text)) {
      findings.push({
        severity: "warn",
        rule: "causal-language-without-result-artifact",
        claimId: claim.id,
        message: `claim ${claim.id} uses causal language but is not backed by a result artifact`,
      });
    }
    if (claim.kind === "result" && CONFIRMATORY_PATTERN.test(claim.text)) {
      findings.push({
        severity: "warn",
        rule: "confirmatory-language",
        claimId: claim.id,
        message: `claim ${claim.id} asserts a proof or established fact; prefer uncertainty-qualified language`,
      });
    }
  }

  const report = {
    schemaVersion: "psyclaw/writing-review/v1",
    version,
    findings,
    blockCount: findings.filter((finding) => finding.severity === "block").length,
    suggestions: findings.map((finding): ReviewSuggestion => ({ severity: finding.severity, rule: finding.rule, ...(finding.claimId ? { claimId: finding.claimId } : {}), suggestion: finding.message })),
  };

  const markdown = [
    `# Writing Review ${version}`,
    "",
    `Research goal: ${project.goal}`,
    "",
    "## Findings",
    "",
    ...(findings.length ? findings.map((finding) => `- [${finding.severity}] ${finding.rule}: ${finding.message}`) : ["- None"]),
    "",
  ].join("\n");

  return finalizeWorkflow(root, writingReviewSpec, {
    gates,
    outputs: [
      { path: "writing-review.md", contents: markdown },
      { path: "review-findings.json", contents: `${JSON.stringify(report, null, 2)}\n` },
      { path: "review-suggestions.json", contents: `${JSON.stringify({ schemaVersion: "psyclaw/review-suggestions/v1", version, suggestions: report.suggestions }, null, 2)}\n` },
      { path: `writing-review-${version}.md`, contents: markdown },
      { path: `review-findings-${version}.json`, contents: `${JSON.stringify(report, null, 2)}\n` },
    ],
    completed: ["claims loaded", "honesty heuristics applied", "findings reported"],
  });
}
