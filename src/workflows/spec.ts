import { randomUUID } from "node:crypto";
import { mkdir } from "node:fs/promises";
import { join } from "node:path";
import type { GateResult, Handoff, ResearchParadigm } from "../core/contracts.js";
import { sha256Text } from "../core/hash.js";
import { assertSafeProjectPath, projectPaths } from "../project/paths.js";
import { writeHandoff } from "../project/bootstrap.js";
import { atomicWriteFile } from "../project/jsonl.js";
import { readProject } from "../research/ledger.js";
import { RunEventLog } from "../panel/events.js";

export const WORKFLOW_SCHEMA = "psyclaw/workflow/v1" as const;

export type WorkflowRole = "researcher" | "analyst" | "critic" | "writer" | "verifier";
export type WorkflowEffect = "read" | "write";

export interface WorkflowStep {
  id: string;
  role: WorkflowRole;
  effect: WorkflowEffect;
  description: string;
}

export interface WorkflowSpec {
  id: string;
  version: string;
  description: string;
  paradigms: readonly ResearchParadigm[];
  steps: readonly WorkflowStep[];
  requiredArtifacts: readonly string[];
}

export interface WorkflowOutputRecord {
  path: string;
  sha256: string;
  artifactVersion: string;
  format: "json" | "markdown" | "text" | "unknown";
  status: "verified" | "draft-blocked";
}

export interface WorkflowResult {
  runId: string;
  workflowId: string;
  verdict: "pass" | "blocked";
  gates: GateResult[];
  outputPaths: string[];
  manifestPath: string;
  verdictPath: string;
  outputIndexPath: string;
  handoff: Handoff;
}

const ALL_PARADIGMS: readonly ResearchParadigm[] = [
  "survey-observational",
  "qualitative-thematic",
  "experimental",
  "quasi-experimental",
  "longitudinal-panel",
  "meta-analysis",
  "ethnographic",
  "historical-documentary",
  "policy-legal",
  "mixed-methods",
];

export const allParadigms = ALL_PARADIGMS;

/**
 * Reject a workflow output path before it is resolved, so a `..` segment or
 * drive/ADS form cannot be collapsed away before the containment check.
 */
async function safeOutputPath(root: string, outputPath: string): Promise<string> {
  const normalized = outputPath.trim().replaceAll("\\", "/");
  if (
    normalized.length === 0 ||
    normalized.startsWith("/") ||
    /^[a-z]:/.test(normalized) ||
    normalized.includes("\0") ||
    normalized.split("/").some((segment) => segment === ".." || segment === "")
  ) {
    throw new Error(`unsafe output path: ${outputPath}`);
  }
  return assertSafeProjectPath(root, join("outputs", normalized));
}

/**
 * Shared tail for every workflow pack. Outputs are written to safe project
 * paths, the spec's required artifacts are actually checked, every output is
 * SHA-pinned with a workflow version and input fingerprint, and `completed`
 * is emitted only after outputs, manifest, and verdict are all on disk.
 */
export async function finalizeWorkflow(
  root: string,
  workflow: WorkflowSpec,
  options: {
    gates: GateResult[];
    outputs: { path: string; contents: string }[];
    completed: string[];
  },
): Promise<WorkflowResult> {
  const paths = projectPaths(root);
  const project = await readProject(root);
  const runId = `run_${randomUUID().replaceAll("-", "")}`;
  const gates: GateResult[] = [...options.gates];
  const eventLog = new RunEventLog(root, runId);
  const eventAt = new Date().toISOString();

  // planned first; any later failure only ever emits blocked/unknown.
  await eventLog.append({ type: "planned", at: eventAt });

  await mkdir(paths.manifests, { recursive: true });
  await mkdir(paths.outputs, { recursive: true });

  const outputPaths: string[] = [];
  const outputRecords: WorkflowOutputRecord[] = [];
  const artifactVersion = workflow.version;
  const formatOf = (path: string): WorkflowOutputRecord["format"] => {
    const lower = path.toLowerCase();
    if (lower.endsWith(".json")) return "json";
    if (lower.endsWith(".md") || lower.endsWith(".markdown")) return "markdown";
    if (lower.endsWith(".txt")) return "text";
    return "unknown";
  };
  for (const output of options.outputs) {
    const target = await safeOutputPath(paths.root, output.path);
    await atomicWriteFile(target, output.contents);
    outputPaths.push(target);
    outputRecords.push({ path: output.path, sha256: sha256Text(output.contents), artifactVersion, format: formatOf(output.path), status: "draft-blocked" });
  }

  // The spec's required artifacts must actually be produced.
  for (const required of workflow.requiredArtifacts) {
    if (!outputRecords.some((record) => record.path === required)) {
      gates.push({
        gateId: "workflow:missing-artifact",
        ok: false,
        severity: "block",
        reason: `required artifact not produced: ${required}`,
      });
    }
  }

  const blocked = gates.filter((gate) => !gate.ok);
  for (const gate of gates) await eventLog.append({ type: "gate", at: eventAt, message: gate.reason });

  const verifiedRecords: WorkflowOutputRecord[] = outputRecords.map((record) => ({
    ...record,
    status: blocked.length === 0 ? "verified" : "draft-blocked",
  }));

  const manifestPath = join(paths.manifests, `${runId}.json`);
  const manifest = {
    schemaVersion: "psyclaw/workflow-manifest/v1",
    workflow: workflow.id,
    workflowVersion: workflow.version,
    runId,
    inputDigest: sha256Text(`${project.goal}\u0000${project.paradigm}`),
    outputs: verifiedRecords,
    gates,
    generatedAt: new Date().toISOString(),
  };
  await atomicWriteFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);

  const verdictPath = join(paths.manifests, `${runId}.verdict.json`);
  const verdict = {
    schemaVersion: "psyclaw/verdict/v1",
    runId,
    verdict: blocked.length === 0 ? "pass" as const : "blocked" as const,
    workflow: workflow.id,
    manifestPath,
    gateCount: gates.length,
    blockedGateCount: blocked.length,
    generatedAt: new Date().toISOString(),
  };
  await atomicWriteFile(verdictPath, `${JSON.stringify(verdict, null, 2)}\n`);
  const outputIndexPath = await assertSafeProjectPath(root, "outputs/index.json");
  await atomicWriteFile(outputIndexPath, `${JSON.stringify({
    schemaVersion: "psyclaw/output-index/v1",
    runId,
    workflow: workflow.id,
    workflowVersion: workflow.version,
    artifacts: verifiedRecords,
    generatedAt: new Date().toISOString(),
  }, null, 2)}\n`);

  const handoff = await writeHandoff(root, {
    projectId: project.id,
    runId,
    goal: project.goal,
    completed: options.completed,
    verified: blocked.length === 0
      ? ["outputs", "output index", "manifest", "verdict"]
      : ["manifest", "verdict"],
    blocked: blocked.map((gate) => gate.reason),
    nextSteps: blocked.length === 0 ? ["human review before external use"] : ["resolve blocked workflow gates"],
    verificationCommands: ["pnpm typecheck", "pnpm test"],
    generatedAt: new Date().toISOString(),
  });

  // completed/blocked is emitted last, only after every artifact is on disk.
  await eventLog.append({
    type: blocked.length === 0 ? "completed" : "blocked",
    at: eventAt,
    message: blocked.length === 0 ? `${workflow.id} completed` : `${workflow.id} blocked`,
  });

  return {
    runId,
    workflowId: workflow.id,
    verdict: blocked.length === 0 ? "pass" : "blocked",
    gates,
    outputPaths,
    manifestPath,
    verdictPath,
    outputIndexPath,
    handoff,
  };
}
