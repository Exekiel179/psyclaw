import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { mkdir, readFile } from "node:fs/promises";
import { basename, extname, join } from "node:path";
import { createHash, randomUUID } from "node:crypto";
import { assertSafeProjectPath } from "../project/paths.js";
import { atomicWriteFile } from "../project/jsonl.js";
import { ARS_UPSTREAM_COMMIT, ARS_UPSTREAM_REF } from "./profile.js";
import { ARS_REVIEW_SEATS, type ArsPanelRequest, type ArsPanelResult, type ArsReviewSeat, type ArsSeatResult } from "./contracts.js";
import { arsReviewDispatchBatches } from "./panel-plan.js";
import { arsRoot, buildArsPanelProvenance, executeArsReviewSeat, executeArsSynthesis, type ArsExecutorOptions } from "./pi-panel-executor.js";
import { runArsReReview, type ArsReReviewAdapters } from "./re-review.js";

const execFileAsync = promisify(execFile);

function hash(bytes: Buffer | string): string { return createHash("sha256").update(bytes).digest("hex"); }
const SENSITIVE_INPUT = /(?:^|[\\/])(?:\.env(?:\..*)?|\.npmrc|\.netrc|credentials?|secrets?|tokens?|id_rsa|id_ed25519)(?:$|[\\/.])/i;
const ALLOWED_RESEARCH_EXTENSIONS = new Set([".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".tex"]);
async function safeInput(root: string, relative: string): Promise<{ path: string; bytes: Buffer; sha256: string }> {
  if (SENSITIVE_INPUT.test(relative) || !ALLOWED_RESEARCH_EXTENSIONS.has(extname(relative).toLowerCase())) throw new Error(`ARS input type or path is not approved: ${relative}`);
  const path = await assertSafeProjectPath(root, relative);
  const bytes = await readFile(path);
  if (bytes.length > 8 * 1024 * 1024) throw new Error(`ARS input is too large: ${relative}`);
  const sample = bytes.subarray(0, 256 * 1024).toString("utf8");
  if (/(?:api[_-]?key|access[_-]?token|client[_-]?secret|private[_-]?key)\s*[:=]\s*["']?[A-Za-z0-9_./+=-]{12,}/i.test(sample) || /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/.test(sample)) throw new Error(`ARS input appears to contain credentials: ${relative}`);
  return { path, bytes, sha256: hash(bytes) };
}
function metadataFor(text: string, request: ArsPanelRequest): Record<string, string | number> {
  return { title: request.title?.trim() || "Untitled manuscript", field: request.field?.trim() || "unspecified", word_count: text.trim().split(/\s+/u).filter(Boolean).length };
}

export type ArsSeatExecutor = (
  seat: ArsReviewSeat,
  contractPath: string,
  manuscriptPath: string,
  metadataPath: string,
  reviewerCards: string,
  options: ArsExecutorOptions,
) => Promise<ArsSeatResult>;

export interface ArsBridgeAdapters {
  executeSeat: ArsSeatExecutor;
  executeSynthesis: (
    seats: readonly ArsSeatResult[],
    contractPath: string,
    manuscriptPath: string,
    options: ArsExecutorOptions,
  ) => Promise<string>;
  buildProvenance: (
    seats: readonly ArsSeatResult[],
    contractSha256: string,
    panelId: string,
    runRoot: string,
  ) => Promise<string>;
  finalizeCarrier: (args: {
    provenancePath: string;
    runRoot: string;
    artifactRef: string;
  }) => Promise<string>;
}

async function defaultFinalizeCarrier(args: {
  provenancePath: string;
  runRoot: string;
  artifactRef: string;
}): Promise<string> {
  const provenanceCarrier = join(args.runRoot, "panel-provenance-carrier.json");
  await execFileAsync("python3", [join(arsRoot(), "scripts", "review_panel_provenance.py"), "build-carrier", args.provenancePath, "--artifact-ref", args.artifactRef, "--output", provenanceCarrier], { cwd: arsRoot(), timeout: 60_000 });
  await execFileAsync("python3", [join(arsRoot(), "scripts", "review_panel_provenance.py"), "validate-carrier", provenanceCarrier, "--artifact-root", args.runRoot], { cwd: arsRoot(), timeout: 60_000 });
  return provenanceCarrier;
}

export const defaultArsBridgeAdapters: ArsBridgeAdapters = {
  executeSeat: executeArsReviewSeat,
  executeSynthesis: executeArsSynthesis,
  buildProvenance: buildArsPanelProvenance,
  finalizeCarrier: defaultFinalizeCarrier,
};

export type ArsBridgeOptions = Omit<ArsExecutorOptions, "runRoot"> & {
  adapters?: Partial<ArsBridgeAdapters>;
  reReviewAdapters?: Partial<ArsReReviewAdapters>;
};

export async function runArsMultiAgentBridge(request: ArsPanelRequest, options: ArsBridgeOptions): Promise<ArsPanelResult> {
  if (request.mode === "reviewer_re_review") {
    const { adapters: _ignored, reReviewAdapters, ...rest } = options;
    return runArsReReview(request, reReviewAdapters === undefined ? rest : { ...rest, adapters: reReviewAdapters });
  }
  if (request.mode !== "reviewer_full" || !request.manuscriptPath || !request.reviewerCards?.trim()) throw new Error("reviewer_full requires manuscriptPath and confirmed reviewerCards");
  const adapters: ArsBridgeAdapters = { ...defaultArsBridgeAdapters, ...options.adapters };
  const { adapters: _drop, reReviewAdapters: _drop2, ...executorBase } = options;
  const manuscript = await safeInput(options.root, request.manuscriptPath);
  const contractPath = join(arsRoot(), "shared", "contracts", "reviewer", "full.json");
  const contractBytes = await readFile(contractPath);
  const contractSha256 = hash(contractBytes);
  if (contractSha256 !== "e9712090d2469fea15a37b8e22d4e137afbcb2bf38d5789939c5df56738ef7af") throw new Error("pinned ARS reviewer contract hash mismatch");
  const inputDigest = hash(JSON.stringify({ mode: request.mode, manuscript: manuscript.sha256, contract: contractSha256, cards: request.reviewerCards ?? "", passport: request.passportDigest ?? "", upstream: ARS_UPSTREAM_COMMIT }));
  const runId = request.resumeRunId ?? `ars_review_${Date.now()}_${randomUUID().slice(0, 8)}`;
  if (!/^ars_review_[A-Za-z0-9_-]+$/.test(runId)) throw new Error("invalid ARS resumeRunId");
  const outputRelative = `.psyclaw/ars-runs/${runId}`;
  const runRoot = await assertSafeProjectPath(options.root, outputRelative);
  await mkdir(runRoot, { recursive: true });
  const metadataPath = join(runRoot, "metadata.json");
  const requestPath = join(runRoot, "request.json");
  if (request.resumeRunId) {
    const prior = JSON.parse(await readFile(requestPath, "utf8")) as { inputDigest?: unknown; upstreamCommit?: unknown; contractSha256?: unknown };
    if (prior.inputDigest !== inputDigest || prior.upstreamCommit !== ARS_UPSTREAM_COMMIT || prior.contractSha256 !== contractSha256) throw new Error("ARS resume blocked: input, contract, cards, passport, or upstream ref drifted");
    try {
      const completed = JSON.parse(await readFile(join(runRoot, "result.json"), "utf8")) as ArsPanelResult;
      if (completed.status === "completed" && completed.inputDigest === inputDigest) return completed;
    } catch { /* resume a blocked/incomplete run */ }
  } else {
    await atomicWriteFile(metadataPath, `${JSON.stringify(metadataFor(manuscript.bytes.toString("utf8"), request), null, 2)}\n`);
    await atomicWriteFile(requestPath, `${JSON.stringify({ schemaVersion: "psyclaw/ars-panel-request/v1", ...request, manuscriptSha256: manuscript.sha256, contractSha256, inputDigest, upstreamRef: ARS_UPSTREAM_REF, upstreamCommit: ARS_UPSTREAM_COMMIT }, null, 2)}\n`);
  }
  const executorOptions: ArsExecutorOptions = { ...executorBase, runRoot };
  const results: ArsSeatResult[] = [];
  if (request.resumeRunId) {
    for (const seat of ARS_REVIEW_SEATS) {
      try {
        const saved = JSON.parse(await readFile(join(runRoot, `${seat}.result.json`), "utf8")) as ArsSeatResult;
        if (saved.seat !== seat || saved.phase1Sha256 !== hash(saved.phase1) || saved.phase2Sha256 !== hash(saved.phase2)) throw new Error("seat artifact hash mismatch");
        results.push(saved);
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw new Error(`ARS resume blocked for ${seat}: ${error instanceof Error ? error.message : String(error)}`);
      }
    }
  }
  try {
    for (const batch of arsReviewDispatchBatches()) {
      const pending = batch.filter((seat) => !results.some((result) => result.seat === seat));
      if (pending.length === 0) continue;
      const settled = await Promise.allSettled(pending.map((seat) => adapters.executeSeat(seat, contractPath, manuscript.path, metadataPath, request.reviewerCards ?? "", executorOptions)));
      const succeeded = settled.filter((item): item is PromiseFulfilledResult<ArsSeatResult> => item.status === "fulfilled").map((item) => item.value);
      results.push(...succeeded);
      await Promise.all(succeeded.map((result) => atomicWriteFile(join(runRoot, `${result.seat}.result.json`), `${JSON.stringify(result, null, 2)}\n`)));
      await atomicWriteFile(join(runRoot, "checkpoint.json"), `${JSON.stringify({ schemaVersion: "psyclaw/ars-bridge-checkpoint/v1", runId, mode: request.mode, inputDigest, completedSeats: results.map((seat) => seat.seat), expectedSeats: ARS_REVIEW_SEATS, updatedAt: new Date().toISOString() }, null, 2)}\n`);
      const failures = settled.filter((item): item is PromiseRejectedResult => item.status === "rejected");
      if (failures.length > 0) throw new Error(`[PANEL-SHRUNK]: ${failures.map((item) => item.reason instanceof Error ? item.reason.message : String(item.reason)).join("; ")}`);
    }
    if (results.length !== ARS_REVIEW_SEATS.length || ARS_REVIEW_SEATS.some((seat) => !results.some((result) => result.seat === seat))) throw new Error("[PANEL-SHRUNK]: fixed five-seat cardinality failed");
    const provenance = await adapters.buildProvenance(results, contractSha256, runId, runRoot);
    const provenanceCarrier = await adapters.finalizeCarrier({
      provenancePath: provenance,
      runRoot,
      artifactRef: basename(provenance),
    });
    const synthesis = await adapters.executeSynthesis(results, contractPath, manuscript.path, executorOptions);
    const result: ArsPanelResult = { schemaVersion: "psyclaw/ars-panel-result/v1", mode: request.mode, runId, status: "completed", inputDigest, upstreamRef: ARS_UPSTREAM_REF, upstreamCommit: ARS_UPSTREAM_COMMIT, contractSha256, manuscriptSha256: manuscript.sha256, seatResults: results, synthesis, synthesisSha256: hash(synthesis), provenancePath: `${outputRelative}/${basename(provenance)}`, provenanceCarrierPath: `${outputRelative}/${basename(provenanceCarrier)}`, outputRoot: outputRelative, diagnostics: [], independenceClaim: "process-separated-not-independent-errors" };
    await atomicWriteFile(join(runRoot, "result.json"), `${JSON.stringify(result, null, 2)}\n`);
    return result;
  } catch (error) {
    const result: ArsPanelResult = { schemaVersion: "psyclaw/ars-panel-result/v1", mode: request.mode, runId, status: "blocked", inputDigest, upstreamRef: ARS_UPSTREAM_REF, upstreamCommit: ARS_UPSTREAM_COMMIT, contractSha256, manuscriptSha256: manuscript.sha256, seatResults: results, outputRoot: outputRelative, diagnostics: [error instanceof Error ? error.message : String(error)], independenceClaim: "process-separated-not-independent-errors" };
    await atomicWriteFile(join(runRoot, "result.json"), `${JSON.stringify(result, null, 2)}\n`);
    return result;
  }
}
