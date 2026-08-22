import { checkEvidenceSufficiency } from "../core/evidence-policy.js";
import { loadLedger, readProject } from "../research/ledger.js";
import { allParadigms, finalizeWorkflow, type WorkflowResult, type WorkflowSpec } from "./spec.js";
import { ANALYSIS_HOOKS_VERSION, analysisHookDigest, loadUserAnalysisHooks } from "../analysis/hooks.js";
import { checkPreRegistration, readPreRegistration } from "../analysis/pre-registration.js";
import { allocateProjectVersion } from "../project/versions.js";

export const analysisDelegationSpec: WorkflowSpec = {
  id: "analysis-delegation",
  version: "1.0.0",
  description: "Plan an external statistical analysis without computing anything in core.",
  paradigms: allParadigms,
  steps: [
    { id: "select", role: "analyst", effect: "read", description: "select result claims to delegate" },
    { id: "contract", role: "analyst", effect: "read", description: "write input/output/environment contract" },
    { id: "write", role: "writer", effect: "write", description: "write the delegation plan" },
  ],
  requiredArtifacts: ["analysis-plan.md", "delegation.json"],
};

export async function runAnalysisDelegation(root: string): Promise<WorkflowResult> {
  const project = await readProject(root);
  const ledger = await loadLedger(root);
  const gates = checkEvidenceSufficiency({ ...ledger, paradigm: project.paradigm });
  // Confirmatory analysis is gated on a pre-registered plan.
  gates.push(...checkPreRegistration(await readPreRegistration(root), project.paradigm));
  const version = await allocateProjectVersion(root, "analysis-plan", `analysis-delegation:${Date.now()}`);
  const userHooks = await loadUserAnalysisHooks(root);
  const resultClaims = ledger.claims.filter((claim) => claim.kind === "result");
  if (resultClaims.length === 0) {
    gates.push({ gateId: "analysis:no-result-claims", ok: false, severity: "block", reason: "no result claims to delegate" });
  }

  const delegation = {
    schemaVersion: "psyclaw/delegation/v1",
    paradigm: project.paradigm,
    version,
    note: "psyclaw plans and verifies delegated analysis; it never computes statistics in core.",
    safety: {
      hooks: ANALYSIS_HOOKS_VERSION,
      hookDigest: analysisHookDigest(),
      userHooks: userHooks.map((hook) => ({ id: hook.id, event: hook.event, severity: hook.severity })),
      immutableInputs: ["data/raw", "declared input paths"],
      requiredChecks: ["beforeAnalysis", "validateAnalysisPlan", "beforeWrite", "afterAnalysis"],
      policy: ["never overwrite or recode data/raw", "never report p-values without effect sizes and uncertainty intervals", "never turn correlation or significance into causality", "record script, environment, input hashes, missing-data and multiplicity handling"],
    },
    tasks: resultClaims.map((claim) => ({
      claimId: claim.id,
      claim: claim.text,
      inputRefs: claim.evidenceIds,
      contract: {
        entrypoint: `analysis/scripts/run_${claim.id}.py`,
        script: `analysis/scripts/run_${claim.id}.py`,
        moduleLayout: {
          load: `analysis/scripts/${claim.id}/01_load.py`,
          prepare: `analysis/scripts/${claim.id}/02_prepare.py`,
          analyze: `analysis/scripts/${claim.id}/03_analyze.py`,
          validate: `analysis/scripts/${claim.id}/04_validate.py`,
          export: `analysis/scripts/${claim.id}/05_export.py`,
          reviewDocument: `analysis/scripts/${claim.id}/README.md`,
        },
        environment: { python: ">=3.12", execution: "external-and-approved" },
        inputDigestRefs: claim.evidenceIds,
        outputSchema: "psyclaw/analysis-result/v1",
        requiredArtifact: `analysis/results/${claim.id}.result.json`,
        moduleBoundary: "The entrypoint may orchestrate modules only; data loading, preparation, analysis, validation, and export stay separately reviewable.",
      },
    })),
  };

  const markdown = [
    `# Analysis Delegation Plan ${version}`,
    "",
    `Paradigm: ${project.paradigm}`,
    "",
    ...delegation.tasks.map((task) => [
      `## ${task.claimId}`,
      "",
      `Claim: ${task.claim}`,
      "",
      `- Entrypoint: \`${task.contract.entrypoint}\``,
      `- Modules: load → prepare → analyze → validate → export`,
      `- Review document: \`${task.contract.moduleLayout.reviewDocument}\``,
      `- Environment: \`${task.contract.environment.python}\``,
      `- Required artifact: \`${task.contract.requiredArtifact}\``,
      "",
    ]).flat(),
  ].join("\n");

  return finalizeWorkflow(root, analysisDelegationSpec, {
    gates,
    outputs: [
      { path: "analysis-plan.md", contents: markdown },
      { path: "delegation.json", contents: `${JSON.stringify(delegation, null, 2)}\n` },
      { path: `analysis-plan-${version}.md`, contents: markdown },
      { path: `delegation-${version}.json`, contents: `${JSON.stringify(delegation, null, 2)}\n` },
    ],
    completed: ["result claims selected", "delegation contracts written"],
  });
}
