import { lstat, readFile, realpath } from "node:fs/promises";
import { isAbsolute, relative, resolve } from "node:path";
import { sha256Text } from "../core/hash.js";

export const ANALYSIS_HOOKS_VERSION = "psyclaw/analysis-hooks/v1" as const;

export type AnalysisHookSeverity = "block" | "warn";

export interface AnalysisHookFinding {
  rule: string;
  severity: AnalysisHookSeverity;
  message: string;
}

export interface AnalysisHookResult {
  schemaVersion: typeof ANALYSIS_HOOKS_VERSION;
  ok: boolean;
  findings: AnalysisHookFinding[];
}

export type AnalysisHookEvent = "before-analysis" | "before-write" | "after-analysis";

/** Project-local, declarative extension. It can add blocks/warnings, never remove built-in gates. */
export interface UserAnalysisHook {
  id: string;
  event: AnalysisHookEvent;
  enabled?: boolean;
  severity: AnalysisHookSeverity;
  message: string;
  pattern?: string;
  pathPrefix?: string;
}

export interface UserAnalysisHookFile {
  schemaVersion: "psyclaw/user-analysis-hooks/v1";
  hooks: UserAnalysisHook[];
}

export interface AnalysisInputContract {
  root: string;
  inputPaths: string[];
  originalDataPaths?: string[];
  declaredInputHashes?: Record<string, string>;
}

export interface AnalysisPlanContract {
  confirmatory: boolean;
  primaryOutcome?: string;
  primaryAnalysis?: string;
  exploratoryAnalyses?: string[];
  missingDataPlan?: string;
  multiplicityPlan?: string;
  exclusionCriteria?: string;
  stoppingRule?: string;
}

export interface AnalysisResultContract {
  schemaVersion: "psyclaw/analysis-result/v1";
  inputHashes: Record<string, string>;
  scriptPath: string;
  environment: Record<string, string>;
  sampleSize: number;
  missingData: { handled: boolean; method?: string; count?: number };
  effectSizes?: Array<{ name: string; value: number; interval?: [number, number] }>;
  pValues?: Array<{ name: string; value: number; adjusted?: boolean; adjustment?: string }>;
  exclusions?: { count: number; reason: string };
  claims?: string[];
}

const BLOCKED_RESULT_PHRASES = [
  /p\s*[<＝=]\s*\.0?5\b.*(?:caus|prove|therefore)/i,
  /statistically\s+significant.*(?:therefore|prove|caus)/i,
  /显著(?:性)?(?:因此|说明|证明)(?:导致|因果|影响)/i,
  /证明了?因果/i,
];

function result(findings: AnalysisHookFinding[]): AnalysisHookResult {
  return { schemaVersion: ANALYSIS_HOOKS_VERSION, ok: !findings.some((item) => item.severity === "block"), findings };
}

export async function loadUserAnalysisHooks(root: string): Promise<UserAnalysisHook[]> {
  const path = resolve(root, ".psyclaw", "analysis-hooks.json");
  try {
    const parsed = JSON.parse(await readFile(path, "utf8")) as Partial<UserAnalysisHookFile>;
    if (parsed.schemaVersion !== "psyclaw/user-analysis-hooks/v1" || !Array.isArray(parsed.hooks)) return [];
    return parsed.hooks.filter((hook): hook is UserAnalysisHook =>
      typeof hook?.id === "string" && /^[a-z0-9][a-z0-9._-]{0,63}$/i.test(hook.id) &&
      (hook.event === "before-analysis" || hook.event === "before-write" || hook.event === "after-analysis") &&
      (hook.severity === "block" || hook.severity === "warn") && typeof hook.message === "string" && hook.message.trim().length > 0,
    );
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    return [{ id: "config-invalid", event: "before-analysis", severity: "block", message: "user analysis hook configuration is invalid" }];
  }
}

function applyUserHooks(event: AnalysisHookEvent, hooks: readonly UserAnalysisHook[], values: readonly string[]): AnalysisHookFinding[] {
  const findings: AnalysisHookFinding[] = [];
  for (const hook of hooks) {
    if (hook.enabled === false || hook.event !== event) continue;
    if (hook.pathPrefix && !values.some((value) => value.replaceAll("\\", "/").startsWith(hook.pathPrefix!.replaceAll("\\", "/")))) continue;
    if (hook.pattern) {
      let matched = false;
      try { matched = values.some((value) => new RegExp(hook.pattern!, "i").test(value)); } catch { matched = false; }
      if (!matched) continue;
    }
    findings.push({ rule: `user:${hook.id}`, severity: hook.severity, message: hook.message });
  }
  return findings;
}

function isInside(root: string, candidate: string): boolean {
  const rel = relative(resolve(root), resolve(candidate)).replaceAll("\\", "/");
  return rel !== ".." && !rel.startsWith("../") && !isAbsolute(rel);
}

function projectPath(root: string, candidate: string): string {
  return isAbsolute(candidate) ? resolve(candidate) : resolve(root, candidate);
}

/** Before execution: original inputs may be read, but can never be an output target. */
export async function beforeAnalysis(contract: AnalysisInputContract, userHooks: readonly UserAnalysisHook[] = []): Promise<AnalysisHookResult> {
  const findings: AnalysisHookFinding[] = [];
  const originals = new Set((contract.originalDataPaths ?? contract.inputPaths).map((p) => projectPath(contract.root, p)));
  for (const input of contract.inputPaths) {
    const path = projectPath(contract.root, input);
    if (!isInside(contract.root, path)) {
      findings.push({ rule: "input-outside-project", severity: "block", message: `analysis input escapes project: ${input}` });
      continue;
    }
    try {
      const stat = await lstat(path);
      if (stat.isSymbolicLink()) findings.push({ rule: "input-symlink", severity: "block", message: `analysis input is a symlink: ${input}` });
      await realpath(path);
    } catch {
      findings.push({ rule: "input-unavailable", severity: "block", message: `analysis input is unavailable: ${input}` });
    }
  }
  for (const original of originals) {
    if (!isInside(contract.root, original)) findings.push({ rule: "original-outside-project", severity: "block", message: "original data path escapes project" });
  }
  for (const [path, hash] of Object.entries(contract.declaredInputHashes ?? {})) {
    if (!/^[a-f0-9]{64}$/i.test(hash)) findings.push({ rule: "input-hash-invalid", severity: "block", message: `invalid input hash: ${path}` });
  }
  return result([...findings, ...applyUserHooks("before-analysis", userHooks, contract.inputPaths)]);
}

/** Before any write: raw data and every declared original input are immutable. */
export function beforeWrite(root: string, targetPath: string, originalDataPaths: string[] = [], userHooks: readonly UserAnalysisHook[] = []): AnalysisHookResult {
  const target = projectPath(root, targetPath);
  const findings: AnalysisHookFinding[] = [];
  const rel = relative(resolve(root), target).replaceAll("\\", "/").toLowerCase();
  if (rel === "data/raw" || rel.startsWith("data/raw/")) findings.push({ rule: "raw-data-write", severity: "block", message: "data/raw is immutable; write a derived copy under data/clean or outputs" });
  if (originalDataPaths.some((path) => projectPath(root, path) === target)) findings.push({ rule: "original-data-overwrite", severity: "block", message: "original input is immutable and cannot be overwritten" });
  return result([...findings, ...applyUserHooks("before-write", userHooks, [targetPath, ...originalDataPaths])]);
}

/** Plan gate: force pre-specification and make undisclosed researcher degrees of freedom visible. */
export function validateAnalysisPlan(plan: AnalysisPlanContract): AnalysisHookResult {
  const findings: AnalysisHookFinding[] = [];
  if (!plan.primaryOutcome?.trim()) findings.push({ rule: "missing-primary-outcome", severity: "block", message: "declare a primary outcome before confirmatory analysis" });
  if (!plan.primaryAnalysis?.trim()) findings.push({ rule: "missing-primary-analysis", severity: "block", message: "declare the primary analysis method" });
  if (!plan.missingDataPlan?.trim()) findings.push({ rule: "missing-missing-data-plan", severity: "block", message: "declare missing-data handling" });
  if (!plan.multiplicityPlan?.trim()) findings.push({ rule: "missing-multiplicity-plan", severity: plan.confirmatory ? "block" : "warn", message: "declare multiplicity or explain why it is not applicable" });
  if (!plan.exclusionCriteria?.trim()) findings.push({ rule: "missing-exclusion-criteria", severity: "warn", message: "record exclusion criteria to prevent outcome-dependent filtering" });
  return result(findings);
}

/** Result gate: reject p-value-only and causal overclaims; require reproducibility metadata. */
export function afterAnalysis(report: AnalysisResultContract, userHooks: readonly UserAnalysisHook[] = []): AnalysisHookResult {
  const findings: AnalysisHookFinding[] = [];
  if (report.schemaVersion !== "psyclaw/analysis-result/v1") findings.push({ rule: "result-schema-invalid", severity: "block", message: "analysis result schema is not recognized" });
  if (!Number.isInteger(report.sampleSize) || report.sampleSize < 0) findings.push({ rule: "sample-size-invalid", severity: "block", message: "analysis result must report a non-negative integer sample size" });
  if (!report.scriptPath?.trim() || Object.keys(report.environment ?? {}).length === 0) findings.push({ rule: "reproducibility-metadata-missing", severity: "block", message: "record script path and execution environment" });
  if (!report.missingData?.handled || !report.missingData.method?.trim()) findings.push({ rule: "missing-data-undisclosed", severity: "block", message: "missing-data handling must be explicit" });
  if ((report.pValues?.length ?? 0) > 0 && (report.effectSizes?.length ?? 0) === 0) findings.push({ rule: "p-value-only-reporting", severity: "block", message: "p-values cannot be reported without effect sizes" });
  for (const claim of report.claims ?? []) if (BLOCKED_RESULT_PHRASES.some((pattern) => pattern.test(claim))) findings.push({ rule: "overclaim-language", severity: "block", message: "claim uses significance as proof of causality; rewrite with design-appropriate uncertainty" });
  for (const [path, hash] of Object.entries(report.inputHashes ?? {})) if (!/^[a-f0-9]{64}$/i.test(hash)) findings.push({ rule: "result-input-hash-invalid", severity: "block", message: `invalid result input hash: ${path}` });
  return result([...findings, ...applyUserHooks("after-analysis", userHooks, report.claims ?? [])]);
}

export function analysisHookDigest(): string {
  return sha256Text(JSON.stringify({ version: ANALYSIS_HOOKS_VERSION, rules: ["raw-data-write", "original-data-overwrite", "p-value-only-reporting", "overclaim-language", "reproducibility-metadata-missing"] }));
}
