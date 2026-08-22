import { mkdir } from "node:fs/promises";
import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { checkEvidenceSufficiency } from "../core/evidence-policy.js";
import { projectPaths } from "../project/paths.js";
import { loadLedger, readProject } from "./ledger.js";
import type { GateResult, Handoff } from "../core/contracts.js";
import { writeHandoff } from "../project/bootstrap.js";
import { atomicWriteFile } from "../project/jsonl.js";
import { RunEventLog } from "../panel/events.js";

export interface BriefResult {
  runId: string;
  verdict: "pass" | "blocked";
  gates: GateResult[];
  briefPath?: string;
  manifestPath: string;
  verdictPath: string;
  handoff: Handoff;
}

export async function runOfflineBrief(root: string): Promise<BriefResult> {
  const paths = projectPaths(root);
  const runId = `run_${randomUUID().replaceAll("-", "")}`;
  const project = await readProject(root);
  const ledger = await loadLedger(root);
  const gates = checkEvidenceSufficiency({ ...ledger, paradigm: project.paradigm });
  const blocked = gates.filter((gate) => !gate.ok);
  const eventLog = new RunEventLog(root, runId);
  const eventAt = new Date().toISOString();
  await eventLog.append({ type: "planned", at: eventAt });
  for (const gate of gates) await eventLog.append({ type: "gate", at: eventAt, message: gate.reason });
  await eventLog.append({
    type: blocked.length === 0 ? "completed" : "blocked",
    at: eventAt,
    message: blocked.length === 0 ? "all evidence gates passed" : "evidence gates blocked",
  });
  const manifest = {
    schemaVersion: "psyclaw/brief-manifest/v1",
    runId,
    inputs: ledger.evidence.map((item) => ({ id: item.id, sha256: item.sha256, locator: item.source.locator })),
    claims: ledger.claims.map((claim) => ({ id: claim.id, status: claim.status, evidenceIds: claim.evidenceIds })),
    gates,
    generatedAt: new Date().toISOString(),
  };
  await mkdir(paths.manifests, { recursive: true });
  const manifestPath = join(paths.manifests, `${runId}.json`);
  await atomicWriteFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);

  let briefPath: string | undefined;
  if (blocked.length === 0) {
    const goal = project.goal;
    const lines = [
      "# Research Brief",
      "",
      `Research goal: ${goal}`,
      "",
      "## Audited Claims",
      "",
      ...ledger.claims.map((claim) => `- ${claim.text} [${claim.status}]`),
      "",
      "Evidence and limitations are recorded in the manifest and ledger.",
      "",
    ];
    briefPath = join(paths.outputs, "brief.md");
    await atomicWriteFile(briefPath, lines.join("\n"));
  }

  const verdictPath = join(paths.manifests, `${runId}.verdict.json`);
  const verdict = {
    schemaVersion: "psyclaw/verdict/v1",
    runId,
    verdict: blocked.length === 0 ? "pass" as const : "blocked" as const,
    manifestPath,
    ...(briefPath ? { briefPath } : {}),
    gateCount: gates.length,
    blockedGateCount: blocked.length,
    generatedAt: new Date().toISOString(),
  };
  await atomicWriteFile(verdictPath, `${JSON.stringify(verdict, null, 2)}\n`);

  const handoff = await writeHandoff(root, {
    projectId: project.id,
    runId,
    goal: project.goal,
    completed: ["evidence ledger loaded", "evidence sufficiency gates evaluated"],
    verified: blocked.length === 0 ? ["brief.md", "manifest", "verdict"] : ["manifest", "verdict"],
    blocked: blocked.map((gate) => gate.reason),
    nextSteps: blocked.length === 0 ? ["human review before external use"] : ["resolve blocked evidence gates"],
    verificationCommands: ["pnpm typecheck", "pnpm test"],
    generatedAt: new Date().toISOString(),
  });
  return { runId, verdict: blocked.length === 0 ? "pass" : "blocked", gates, ...(briefPath ? { briefPath } : {}), manifestPath, verdictPath, handoff };
}
