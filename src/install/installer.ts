import { createHash } from "node:crypto";
import { lstat, mkdir, open, readFile, rename, rm, unlink } from "node:fs/promises";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";
import { sha256File, sha256Text } from "../core/hash.js";
import type { Effect, ToolReceipt } from "../core/contracts.js";
import type { AgentInstallSpec } from "../agents/catalog.js";
import { appendJsonlIfMissing, readJsonl } from "../project/jsonl.js";
import { projectPaths } from "../project/paths.js";

export type InstallKind = "agent" | "skill" | "package";

export interface InstallDependency {
  name: string;
  version: string;
  license?: string;
  sha256?: string;
  status?: "ready" | "missing" | "blocked";
}

export interface InstallSbom {
  format: "CycloneDX";
  specVersion: "1.5";
  /** Relative path inside the staging directory. */
  path: string;
  sha256: string;
}

export interface InstallPlan {
  schemaVersion: "psyclaw/install-plan/v1";
  id: string;
  kind: InstallKind;
  targetId: string;
  sourceRef: string;
  /** Pinned version/ref. `unpinned` is never a verified install. */
  ref: string;
  command: string;
  effect: Effect;
  /** Activation target path. Required for skill/package installs. */
  target?: string;
  /** Controlled staging directory the runner must download into. */
  stagingDir?: string;
  /** File inside `stagingDir` whose SHA-256 is the content pin. */
  contentFile?: string;
  expectedSha256?: string;
  license?: string;
  /** Optional license evidence file inside staging. */
  licenseFile?: string;
  licenseSha256?: string;
  /** Exact dependency pins audited before activation. */
  dependencies?: readonly InstallDependency[];
  /** Optional CycloneDX 1.5 SBOM descriptor for the staged package. */
  sbom?: InstallSbom;
  /** Optional project root used to enforce containment and symlink checks. */
  projectRoot?: string;
}

export interface InstallApproval {
  approved: boolean;
  actor: string;
  reason: string;
}

export interface InstallRunner {
  (command: string, context?: { plan: InstallPlan; stagingDir?: string; target?: string }): Promise<{ exitCode: number }>;
}

/** Idempotency ledger: a given install identity must execute at most once. */
export interface InstallLedger {
  alreadyRecorded(key: string): Promise<boolean>;
  record(key: string): Promise<void>;
  /** Atomically reserve a key before an external command is started. */
  reserve?(key: string): Promise<boolean>;
  /** Release a reservation when the command fails before it is recorded. */
  release?(key: string): Promise<void>;
}

export class InMemoryInstallLedger implements InstallLedger {
  private readonly keys = new Set<string>();
  private readonly reservations = new Set<string>();

  public async alreadyRecorded(key: string): Promise<boolean> {
    return this.keys.has(key);
  }

  public async reserve(key: string): Promise<boolean> {
    if (this.keys.has(key) || this.reservations.has(key)) return false;
    this.reservations.add(key);
    return true;
  }

  public async record(key: string): Promise<void> {
    this.keys.add(key);
    this.reservations.delete(key);
  }

  public async release(key: string): Promise<void> {
    this.reservations.delete(key);
  }
}

/** Project-local append-only install ledger (`.psyclaw/installs.jsonl`). */
export class FileInstallLedger implements InstallLedger {
  public constructor(private readonly root: string) {}

  private path(): string {
    return join(projectPaths(this.root).root, ".psyclaw", "installs.jsonl");
  }

  private lockPath(key: string): string {
    const digest = createHash("sha256").update(key, "utf8").digest("hex");
    return join(projectPaths(this.root).root, ".psyclaw", "install-locks", `${digest}.lock`);
  }

  public async alreadyRecorded(key: string): Promise<boolean> {
    const rows = await readJsonl<unknown>(this.path());
    return rows.some((row) => row === key || (
      typeof row === "object" && row !== null && "key" in row && row.key === key
    ));
  }

  public async reserve(key: string): Promise<boolean> {
    if (await this.alreadyRecorded(key)) return false;
    const path = this.lockPath(key);
    await mkdir(dirname(path), { recursive: true });
    try {
      const handle = await open(path, "wx");
      try {
        await handle.writeFile(JSON.stringify({ key, reservedAt: new Date().toISOString() }), "utf8");
      } finally {
        await handle.close();
      }
      return true;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "EEXIST") return false;
      throw error;
    }
  }

  public async record(key: string): Promise<void> {
    // The key-specific lock makes reservation cross-process; this append is
    // additionally serialized per path within one process.
    await appendJsonlIfMissing(this.path(), key, (value) => typeof value === "string" ? value : JSON.stringify(value));
  }

  public async release(key: string): Promise<void> {
    await unlink(this.lockPath(key)).catch(() => undefined);
  }
}

export interface SkillInstallPlanOptions {
  targetId: string;
  sourceRef: string;
  /** A commit/tag/package version. Omitted only for the deprecated legacy path. */
  ref?: string;
  command: string;
  target?: string;
  stagingDir?: string;
  contentFile?: string;
  expectedSha256?: string;
  license?: string;
  licenseFile?: string;
  licenseSha256?: string;
  dependencies?: readonly InstallDependency[];
  sbom?: InstallSbom;
  projectRoot?: string;
}

export function planAgentInstall(
  agent: { id: string; name: string; install?: AgentInstallSpec },
  options: { projectRoot?: string } = {},
): InstallPlan {
  const install = agent.install;
  return {
    schemaVersion: "psyclaw/install-plan/v1",
    id: `install:agent:${agent.id}`,
    kind: "agent",
    targetId: agent.id,
    sourceRef: install?.sourceRef ?? "unknown",
    ref: install?.ref ?? "unpinned",
    command: install?.installCommand ?? "",
    effect: "write",
    ...(options.projectRoot === undefined ? {} : { projectRoot: options.projectRoot }),
  };
}

export function planSkillInstall(options: SkillInstallPlanOptions): InstallPlan {
  return {
    schemaVersion: "psyclaw/install-plan/v1",
    id: `install:skill:${options.targetId}`,
    kind: "skill",
    targetId: options.targetId,
    sourceRef: options.sourceRef,
    ref: options.ref ?? "legacy",
    command: options.command,
    effect: "write",
    ...(options.target === undefined ? {} : { target: options.target }),
    ...(options.stagingDir === undefined ? {} : { stagingDir: options.stagingDir }),
    contentFile: options.contentFile ?? "SKILL.md",
    ...(options.expectedSha256 === undefined ? {} : { expectedSha256: options.expectedSha256 }),
    ...(options.license === undefined ? {} : { license: options.license }),
    ...(options.licenseFile === undefined ? {} : { licenseFile: options.licenseFile }),
    ...(options.licenseSha256 === undefined ? {} : { licenseSha256: options.licenseSha256 }),
    ...(options.dependencies === undefined ? {} : { dependencies: options.dependencies }),
    ...(options.sbom === undefined ? {} : { sbom: options.sbom }),
    ...(options.projectRoot === undefined ? {} : { projectRoot: options.projectRoot }),
  };
}

const SHA256_RE = /^[a-f0-9]{64}$/i;
const UNPINNED_REFS = new Set(["", "unpinned", "latest", "head", "main", "master", "*", "unknown"]);
const PROTECTED_SEGMENTS = new Set([".git", "data/raw"]);
const fallbackReservations = new WeakMap<object, Set<string>>();

function installKey(plan: InstallPlan): string {
  // Keep the identity bound to the exact tuple required by the D1 contract.
  return JSON.stringify({
    planId: plan.id,
    contentSha256: plan.expectedSha256 ?? "",
    target: plan.target ?? "",
  });
}

function installResultHash(plan: InstallPlan, contentSha256 = plan.expectedSha256 ?? ""): string {
  return sha256Text(JSON.stringify({
    kind: plan.kind,
    targetId: plan.targetId,
    sourceRef: plan.sourceRef,
    ref: plan.ref,
    contentSha256,
    target: plan.target ?? "",
    license: plan.license ?? "",
    licenseSha256: plan.licenseSha256 ?? "",
    dependencies: plan.dependencies ?? [],
    sbom: plan.sbom ?? null,
  }));
}

function receipt(
  plan: InstallPlan,
  now: string,
  fields: {
    approval: ToolReceipt["approval"];
    ok: boolean;
    reasonCode?: string;
    resultHash?: string;
    finishedAt?: string;
  },
): ToolReceipt {
  return {
    schemaVersion: "psyclaw/tool-receipt/v1",
    runId: plan.id,
    taskId: plan.targetId,
    tool: `install:${plan.kind}`,
    effect: plan.effect,
    approval: fields.approval,
    idempotencyKey: plan.id,
    ok: fields.ok,
    ...(fields.reasonCode === undefined ? {} : { reasonCode: fields.reasonCode }),
    ...(fields.resultHash === undefined ? {} : { resultHash: fields.resultHash }),
    startedAt: now,
    finishedAt: fields.finishedAt ?? now,
  };
}

function deny(plan: InstallPlan, now: string, reasonCode: string, reason: string): ToolReceipt {
  return receipt(plan, now, {
    approval: "denied",
    ok: false,
    reasonCode,
    resultHash: sha256Text(reason),
  });
}

function fail(plan: InstallPlan, startedAt: string, reasonCode: string, result = reasonCode, finishedAt?: string): ToolReceipt {
  return receipt(plan, startedAt, {
    approval: "approved",
    ok: false,
    reasonCode,
    resultHash: sha256Text(result),
    ...(finishedAt === undefined ? {} : { finishedAt }),
  });
}

function already(plan: InstallPlan, now: string): ToolReceipt {
  return receipt(plan, now, {
    approval: "approved",
    ok: true,
    reasonCode: "install.already-recorded",
    resultHash: sha256Text("already-recorded"),
  });
}

function sourceAndRefFailure(plan: InstallPlan, allowLegacyRef: boolean): { code: string; reason: string } | undefined {
  if (plan.sourceRef.trim() === "" || plan.sourceRef.trim().toLowerCase() === "unknown") {
    return { code: "install.source-missing", reason: "source reference is required" };
  }
  if (!allowLegacyRef && UNPINNED_REFS.has(plan.ref.trim().toLowerCase())) {
    return { code: "install.ref-unpinned", reason: "a pinned version/ref is required" };
  }
  if (plan.command.trim() === "") {
    return { code: "install.native-manual", reason: "no automated install command" };
  }
  return undefined;
}

async function reserveLedger(ledger: InstallLedger | undefined, key: string): Promise<boolean> {
  if (ledger === undefined) return true;
  if (ledger.reserve !== undefined) return ledger.reserve(key);
  const reservations = fallbackReservations.get(ledger) ?? new Set<string>();
  if (reservations.has(key)) return false;
  if (await ledger.alreadyRecorded(key)) return false;
  reservations.add(key);
  fallbackReservations.set(ledger, reservations);
  return true;
}

async function releaseLedger(ledger: InstallLedger | undefined, key: string): Promise<void> {
  if (ledger !== undefined && ledger.reserve === undefined) fallbackReservations.get(ledger)?.delete(key);
  if (ledger?.release !== undefined) await ledger.release(key).catch(() => undefined);
}

async function recordLedger(ledger: InstallLedger | undefined, key: string): Promise<void> {
  await ledger?.record(key);
  if (ledger !== undefined && ledger.reserve === undefined) fallbackReservations.get(ledger)?.delete(key);
}

function protectedPath(path: string): boolean {
  const pieces = path.replaceAll("\\", "/").split("/").filter(Boolean).map((part) => part.toLowerCase());
  for (let index = 0; index < pieces.length; index += 1) {
    const piece = pieces[index]!;
    const joined = pieces.slice(Math.max(0, index - 1), index + 1).join("/");
    if (PROTECTED_SEGMENTS.has(piece) || PROTECTED_SEGMENTS.has(joined)) return true;
    if (piece.includes("credential") || piece.includes("secret") || piece.includes("token") || piece.includes("cookie")) return true;
  }
  return false;
}

function assertContained(root: string, target: string, label: string): string {
  const base = resolve(root);
  const candidate = resolve(target);
  const rel = relative(base, candidate).replaceAll("\\", "/");
  if (rel === "" || rel === ".." || rel.startsWith("../") || isAbsolute(rel) || protectedPath(rel)) {
    throw new Error(`${label} escapes the project boundary`);
  }
  return candidate;
}

function commonPathAncestor(left: string, right: string): string {
  let cursor = resolve(left);
  const target = resolve(right);
  while (true) {
    const rel = relative(cursor, target).replaceAll("\\", "/");
    if (rel === "" || rel !== ".." && !rel.startsWith("../") && !isAbsolute(rel)) return cursor;
    const parent = dirname(cursor);
    if (parent === cursor) return cursor;
    cursor = parent;
  }
}

async function assertNoSymlinkAncestors(path: string, label: string, boundary: string): Promise<void> {
  const target = resolve(path);
  const base = resolve(boundary);
  const rel = relative(base, target).replaceAll("\\", "/");
  if (rel === ".." || rel.startsWith("../") || isAbsolute(rel)) throw new Error(`${label} escapes its trusted boundary`);
  let cursor = base;
  const candidates = [cursor, ...rel.split("/").filter(Boolean).map((part) => {
    cursor = join(cursor, part);
    return cursor;
  })];
  for (const candidate of candidates) {
    try {
      const stat = await lstat(candidate);
      if (stat.isSymbolicLink()) throw new Error(`${label} symlink is not allowed`);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      break;
    }
  }
}

async function validateInstallPaths(plan: InstallPlan): Promise<{
  staging: string;
  target: string;
  contentPath: string;
  sbomPath?: string;
  licensePath?: string;
}> {
  if (plan.stagingDir === undefined || plan.target === undefined) throw new Error("staging and target paths are required");
  const staging = plan.projectRoot === undefined
    ? resolve(plan.stagingDir)
    : assertContained(plan.projectRoot, plan.stagingDir, "staging path");
  const target = plan.projectRoot === undefined
    ? resolve(plan.target)
    : assertContained(plan.projectRoot, plan.target, "target path");
  const stagingRel = relative(staging, target).replaceAll("\\", "/");
  const targetRel = relative(target, staging).replaceAll("\\", "/");
  if (staging === target || !stagingRel.startsWith("..") || !targetRel.startsWith("..")) {
    throw new Error("staging and target paths must be separate");
  }
  if (plan.projectRoot === undefined && (protectedPath(staging) || protectedPath(target))) {
    throw new Error("protected install path");
  }
  const trustedBoundary = plan.projectRoot === undefined
    ? commonPathAncestor(staging, target)
    : resolve(plan.projectRoot);
  await assertNoSymlinkAncestors(staging, "staging path", trustedBoundary);
  await assertNoSymlinkAncestors(target, "target path", trustedBoundary);

  const contentFile = plan.contentFile ?? "SKILL.md";
  if (contentFile.includes("\u0000") || contentFile.trim() === "" || isAbsolute(contentFile) || contentFile.replaceAll("\\", "/").split("/").includes("..")) {
    throw new Error("content path must stay inside staging");
  }
  const contentPath = resolve(staging, contentFile);
  assertContained(staging, contentPath, "content path");
  const sbomPath = plan.sbom === undefined ? undefined : resolve(staging, plan.sbom.path);
  if (sbomPath !== undefined) {
    assertContained(staging, sbomPath, "SBOM path");
    if (plan.sbom!.path.includes("\u0000") || isAbsolute(plan.sbom!.path) || plan.sbom!.path.replaceAll("\\", "/").split("/").includes("..")) {
      throw new Error("SBOM path must stay inside staging");
    }
  }
  const licenseFile = plan.licenseFile;
  const licensePath = licenseFile === undefined ? undefined : resolve(staging, licenseFile);
  if (licensePath !== undefined) {
    assertContained(staging, licensePath, "license path");
    if (licenseFile!.includes("\u0000") || isAbsolute(licenseFile!) || licenseFile!.replaceAll("\\", "/").split("/").includes("..")) {
      throw new Error("license path must stay inside staging");
    }
  }
  return {
    staging,
    target,
    contentPath,
    ...(sbomPath === undefined ? {} : { sbomPath }),
    ...(licensePath === undefined ? {} : { licensePath }),
  };
}

interface Fingerprint {
  size: number;
  mtimeMs: number;
  ctimeMs: number;
  ino: number;
  dev: number;
}

function sameFingerprint(left: Fingerprint, right: Fingerprint): boolean {
  return left.size === right.size && left.mtimeMs === right.mtimeMs && left.ctimeMs === right.ctimeMs &&
    (left.ino === 0 || right.ino === 0 || left.ino === right.ino) &&
    (left.dev === 0 || right.dev === 0 || left.dev === right.dev);
}

async function fingerprint(path: string): Promise<Fingerprint> {
  const stat = await lstat(path);
  if (!stat.isFile() || stat.isSymbolicLink()) throw new Error("content is not a regular file");
  return { size: stat.size, mtimeMs: stat.mtimeMs, ctimeMs: stat.ctimeMs, ino: stat.ino, dev: stat.dev };
}

async function stableHash(path: string): Promise<{ ok: boolean; actual?: string; reason?: string }> {
  let lastActual = "";
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      const before = await fingerprint(path);
      const first = await sha256File(path);
      const middle = await fingerprint(path);
      if (!sameFingerprint(before, middle)) continue;
      const second = await sha256File(path);
      const after = await fingerprint(path);
      if (!sameFingerprint(middle, after) || first !== second) continue;
      lastActual = second;
      return { ok: true, actual: second };
    } catch {
      return { ok: false, reason: "could not hash a stable regular file" };
    }
  }
  return lastActual === ""
    ? { ok: false, reason: "file changed during verification" }
    : { ok: false, actual: lastActual, reason: "file changed during verification" };
}

/** Verify a downloaded file against an expected SHA-256 before trusting it. */
export async function verifyFileSha256(path: string, expected: string): Promise<{ ok: boolean; reason?: string }> {
  if (!SHA256_RE.test(expected)) return { ok: false, reason: "invalid expected sha256" };
  const result = await stableHash(path);
  if (!result.ok) return { ok: false, reason: result.reason ?? "could not hash file" };
  return result.actual?.toLowerCase() === expected.toLowerCase()
    ? { ok: true }
    : { ok: false, reason: "sha256 mismatch" };
}

async function verifyMetadata(plan: InstallPlan, paths: { staging: string; sbomPath?: string; licensePath?: string }): Promise<{ ok: boolean; code?: string; reason?: string; sbomSha256?: string }> {
  if (plan.kind === "agent") return { ok: true };
  const license = plan.license?.trim().toLowerCase();
  if (license === undefined || license === "" || license === "unknown" || license === "noassertion") {
    return { ok: false, code: "install.license-missing", reason: "license is missing or unknown" };
  }
  if (plan.licenseFile !== undefined) {
    if (paths.licensePath === undefined || plan.licenseSha256 === undefined || !SHA256_RE.test(plan.licenseSha256)) {
      return { ok: false, code: "install.license-evidence-missing", reason: "license evidence pin is missing" };
    }
    const licenseVerification = await stableHash(paths.licensePath);
    if (!licenseVerification.ok || licenseVerification.actual?.toLowerCase() !== plan.licenseSha256.toLowerCase()) {
      return { ok: false, code: "install.license-evidence-mismatch", reason: "license evidence hash mismatch" };
    }
  } else if (plan.licenseSha256 !== undefined) {
    return { ok: false, code: "install.license-evidence-missing", reason: "license evidence path is missing" };
  }
  if (plan.dependencies === undefined) return { ok: false, code: "install.dependency-audit-missing", reason: "dependency audit is missing" };
  for (const dependency of plan.dependencies) {
    const version = dependency.version.trim().toLowerCase();
    if (dependency.name.trim() === "" || version === "" || version === "latest" || version === "unknown" || version === "*" || version.startsWith("^") || version.startsWith("~")) {
      return { ok: false, code: "install.dependency-unpinned", reason: "dependency version is not pinned" };
    }
    if (dependency.status === "missing" || dependency.status === "blocked") return { ok: false, code: "install.dependency-blocked", reason: "dependency audit is blocked" };
    const dependencyLicense = dependency.license?.trim().toLowerCase();
    if (dependencyLicense === undefined || dependencyLicense === "" || dependencyLicense === "unknown" || dependencyLicense === "noassertion") {
      return { ok: false, code: "install.dependency-license-missing", reason: "dependency license is missing" };
    }
    if (dependency.sha256 !== undefined && !SHA256_RE.test(dependency.sha256)) return { ok: false, code: "install.dependency-hash-invalid", reason: "dependency hash is malformed" };
  }
  if (plan.sbom === undefined || paths.sbomPath === undefined) return { ok: false, code: "install.sbom-missing", reason: "CycloneDX SBOM is missing" };
  if (plan.sbom.format !== "CycloneDX" || plan.sbom.specVersion !== "1.5" || !SHA256_RE.test(plan.sbom.sha256)) {
    return { ok: false, code: "install.sbom-invalid", reason: "CycloneDX SBOM metadata is invalid" };
  }
  const sbomVerification = await stableHash(paths.sbomPath);
  if (!sbomVerification.ok || sbomVerification.actual?.toLowerCase() !== plan.sbom.sha256.toLowerCase()) {
    return { ok: false, code: "install.sbom-hash-mismatch", reason: "CycloneDX SBOM hash mismatch" };
  }
  try {
    const parsed = JSON.parse(await readFile(paths.sbomPath, "utf8")) as {
      bomFormat?: unknown;
      specVersion?: unknown;
      components?: unknown;
    };
    if (parsed.bomFormat !== "CycloneDX" || parsed.specVersion !== "1.5" || !Array.isArray(parsed.components)) {
      return { ok: false, code: "install.sbom-invalid", reason: "CycloneDX SBOM schema is invalid" };
    }
    const actualComponents = new Set<string>();
    for (const component of parsed.components) {
      if (typeof component !== "object" || component === null) return { ok: false, code: "install.sbom-invalid", reason: "CycloneDX SBOM component is invalid" };
      const item = component as { name?: unknown; version?: unknown };
      if (typeof item.name !== "string" || typeof item.version !== "string") return { ok: false, code: "install.sbom-invalid", reason: "CycloneDX SBOM component is invalid" };
      actualComponents.add(`${item.name}\u0000${item.version}`);
    }
    for (const dependency of plan.dependencies) {
      if (!actualComponents.has(`${dependency.name}\u0000${dependency.version}`)) return { ok: false, code: "install.sbom-incomplete", reason: "CycloneDX SBOM dependency set is incomplete" };
    }
    if (actualComponents.size !== plan.dependencies.length) return { ok: false, code: "install.sbom-extra-components", reason: "CycloneDX SBOM contains unreviewed components" };
  } catch {
    return { ok: false, code: "install.sbom-invalid", reason: "CycloneDX SBOM cannot be parsed" };
  }
  const stableAfterParse = await stableHash(paths.sbomPath);
  if (!stableAfterParse.ok || stableAfterParse.actual?.toLowerCase() !== plan.sbom.sha256.toLowerCase()) {
    return { ok: false, code: "install.sbom-hash-mismatch", reason: "CycloneDX SBOM changed during verification" };
  }
  return { ok: true, sbomSha256: sbomVerification.actual };
}

export interface InstallRecord {
  schemaVersion: "psyclaw/install-record/v1";
  status: "installed" | "already-recorded" | "blocked" | "failed";
  plan: InstallPlan;
  receipt: ToolReceipt;
  verified: boolean;
  verificationReason?: string;
  recordedAt: string;
  contentSha256?: string;
  sbomSha256?: string;
}

function recordResult(
  plan: InstallPlan,
  recordedAt: string,
  status: InstallRecord["status"],
  toolReceipt: ToolReceipt,
  verified: boolean,
  reason?: string,
  contentSha256?: string,
  sbomSha256?: string,
): InstallRecord {
  return {
    schemaVersion: "psyclaw/install-record/v1",
    status,
    plan,
    receipt: toolReceipt,
    verified,
    ...(reason === undefined ? {} : { verificationReason: reason }),
    recordedAt,
    ...(contentSha256 === undefined ? {} : { contentSha256 }),
    ...(sbomSha256 === undefined ? {} : { sbomSha256 }),
  };
}

/**
 * Execute an approved agent install through an injectable runner. Reservation
 * happens before the runner starts; an unknown runner exception keeps the
 * reservation so a retry cannot repeat an unobserved side effect.
 */
export async function runInstall(
  plan: InstallPlan,
  approval: InstallApproval,
  runner: InstallRunner,
  options: { now?: () => string; ledger?: InstallLedger } = {},
): Promise<ToolReceipt> {
  const clock = options.now ?? (() => new Date().toISOString());
  const startedAt = clock();
  if (approval.approved !== true || approval.actor.trim() === "" || approval.reason.trim() === "") {
    return deny(plan, startedAt, "install.approval-required", "Install requires explicit approval");
  }
  const basicFailure = sourceAndRefFailure(plan, false);
  if (basicFailure !== undefined) return deny(plan, startedAt, basicFailure.code, basicFailure.reason);
  // A command that has no verifiable artifact pin is discover-only. This also
  // prevents catalog entries from silently becoming "latest" global installs.
  if (plan.expectedSha256 === undefined) return deny(plan, startedAt, "install.missing-pin", "content pin is required before execution");
  if (!SHA256_RE.test(plan.expectedSha256)) return deny(plan, startedAt, "install.malformed-pin", "content pin is malformed");
  // An agent plan currently represents a global npm/pipx command, not a
  // staged artifact whose bytes this module can verify. A caller-supplied
  // 64-character string is therefore not enough evidence to execute it.
  // Keep the catalog discover-only until an artifact-backed activation path is
  // implemented; `installSkillPackage` is the verified staging path.
  if (plan.kind === "agent") {
    return deny(plan, startedAt, "install.agent-staging-required", "agent installs require a verified staged artifact");
  }
  if ((plan.kind === "skill" || plan.kind === "package") && (plan.stagingDir === undefined || plan.target === undefined)) {
    return deny(plan, startedAt, "install.missing-target", "staging and target paths are required before execution");
  }

  const ledger = options.ledger ?? (plan.projectRoot === undefined ? undefined : new FileInstallLedger(plan.projectRoot));
  const key = installKey(plan);
  let reserved = false;
  try {
    reserved = await reserveLedger(ledger, key);
  } catch {
    return fail(plan, startedAt, "install.ledger-error");
  }
  if (!reserved) return already(plan, startedAt);

  let exitCode: number;
  try {
    exitCode = (await runner(plan.command, {
      plan,
      ...(plan.stagingDir === undefined ? {} : { stagingDir: plan.stagingDir }),
      ...(plan.target === undefined ? {} : { target: plan.target }),
    })).exitCode;
  } catch {
    // Keep the reservation: the command may have changed external state before throwing.
    return fail(plan, startedAt, "install.runner-error", "runner threw", clock());
  }
  const finishedAt = clock();
  if (!Number.isInteger(exitCode) || exitCode !== 0) {
    await releaseLedger(ledger, key);
    return fail(plan, startedAt, "install.failed", `exit ${String(exitCode)}`, finishedAt);
  }
  try {
    await ledger?.record(key);
  } catch {
    // Do not release a reservation after a successful external side effect.
    return fail(plan, startedAt, "install.ledger-error", "install ledger write failed", finishedAt);
  }
  return receipt(plan, startedAt, {
    approval: "approved",
    ok: true,
    resultHash: installResultHash(plan),
    finishedAt,
  });
}

async function pathExists(path: string): Promise<boolean> {
  try {
    const stat = await lstat(path);
    return true && !stat.isSymbolicLink();
  } catch {
    return false;
  }
}

function blockedRecord(plan: InstallPlan, at: string, code: string, reason: string): InstallRecord {
  return recordResult(plan, at, "blocked", deny(plan, at, code, reason), false, reason);
}

async function legacyDownload(
  plan: InstallPlan,
  approval: InstallApproval,
  runner: InstallRunner,
  downloadPath: string,
  options: { now: () => string; ledger?: InstallLedger },
): Promise<InstallRecord> {
  const at = options.now();
  if (approval.approved !== true) return blockedRecord(plan, at, "install.approval-required", "not approved");
  if (plan.expectedSha256 === undefined) return blockedRecord(plan, at, "install.missing-pin", "no content pin provided");
  if (!SHA256_RE.test(plan.expectedSha256)) return blockedRecord(plan, at, "install.malformed-pin", "content pin is malformed");
  const sourceFailure = sourceAndRefFailure(plan, true);
  if (sourceFailure !== undefined) return blockedRecord(plan, at, sourceFailure.code, sourceFailure.reason);
  try {
    if (plan.projectRoot !== undefined) {
      assertContained(plan.projectRoot, downloadPath, "download path");
    } else if (protectedPath(downloadPath)) {
      return blockedRecord(plan, at, "install.path-invalid", "protected download path");
    }
    await assertNoSymlinkAncestors(
      downloadPath,
      "download path",
      plan.projectRoot === undefined ? dirname(resolve(downloadPath)) : resolve(plan.projectRoot),
    );
  } catch {
    return blockedRecord(plan, at, "install.path-invalid", "download path is unsafe");
  }
  const key = installKey(plan);
  let reserved = false;
  try { reserved = await reserveLedger(options.ledger, key); } catch { return blockedRecord(plan, at, "install.ledger-error", "install ledger unavailable"); }
  if (!reserved) return recordResult(plan, at, "already-recorded", already(plan, at), true, undefined, plan.expectedSha256);
  const before = await verifyFileSha256(downloadPath, plan.expectedSha256);
  if (!before.ok) {
    await releaseLedger(options.ledger, key);
    return blockedRecord(plan, at, "install.hash-mismatch", before.reason ?? "download hash mismatch");
  }
  try {
    const outcome = await runner(plan.command, { plan });
    if (!Number.isInteger(outcome.exitCode) || outcome.exitCode !== 0) {
      await releaseLedger(options.ledger, key);
      return recordResult(plan, at, "failed", fail(plan, at, "install.failed", `exit ${String(outcome.exitCode)}`, options.now()), false);
    }
  } catch {
    return recordResult(plan, at, "failed", fail(plan, at, "install.runner-error", "runner threw", options.now()), false);
  }
  const after = await verifyFileSha256(downloadPath, plan.expectedSha256);
  if (!after.ok) {
    await releaseLedger(options.ledger, key);
    return blockedRecord(plan, at, "install.hash-mismatch", after.reason ?? "download changed during install");
  }
  try { await options.ledger?.record(key); } catch { return recordResult(plan, at, "failed", fail(plan, at, "install.ledger-error", "install ledger write failed", options.now()), false); }
  return recordResult(plan, at, "installed", receipt(plan, at, { approval: "approved", ok: true, resultHash: installResultHash(plan), finishedAt: options.now() }), true, undefined, plan.expectedSha256);
}

/**
 * Download a skill/package into a fresh controlled staging directory, verify
 * hash, license, exact dependencies and CycloneDX SBOM, then atomically
 * activate it. Verification failures never activate or overwrite a target.
 */
export async function installSkillPackage(
  plan: InstallPlan,
  approval: InstallApproval,
  runner: InstallRunner,
  options: { now?: () => string; ledger?: InstallLedger; downloadPath?: string },
): Promise<InstallRecord> {
  const clock = options.now ?? (() => new Date().toISOString());
  // Kept solely for callers of the original pre-staging API. It never
  // activates a target and still verifies the hash before and after the runner.
  if (options.downloadPath !== undefined && (plan.stagingDir === undefined || plan.target === undefined)) {
    return legacyDownload(plan, approval, runner, options.downloadPath, {
      now: clock,
      ...(options.ledger === undefined ? {} : { ledger: options.ledger }),
    });
  }

  const at = clock();
  if (approval.approved !== true || approval.actor.trim() === "" || approval.reason.trim() === "") return blockedRecord(plan, at, "install.approval-required", "not approved");
  if (plan.expectedSha256 === undefined) return blockedRecord(plan, at, "install.missing-pin", "no content pin provided");
  if (!SHA256_RE.test(plan.expectedSha256)) return blockedRecord(plan, at, "install.malformed-pin", "content pin is malformed");
  const basicFailure = sourceAndRefFailure(plan, false);
  if (basicFailure !== undefined) return blockedRecord(plan, at, basicFailure.code, basicFailure.reason);

  let paths: Awaited<ReturnType<typeof validateInstallPaths>>;
  try { paths = await validateInstallPaths(plan); } catch { return blockedRecord(plan, at, "install.path-invalid", "staging or target path is unsafe"); }
  const ledger = options.ledger ?? (plan.projectRoot === undefined ? undefined : new FileInstallLedger(plan.projectRoot));
  const key = installKey(plan);
  let reserved = false;
  try { reserved = await reserveLedger(ledger, key); } catch { return blockedRecord(plan, at, "install.ledger-error", "install ledger unavailable"); }
  if (!reserved) return recordResult(plan, at, "already-recorded", already(plan, at), true, undefined, plan.expectedSha256);

  if (await pathExists(paths.staging)) {
    await releaseLedger(ledger, key);
    return blockedRecord(plan, at, "install.staging-exists", "staging directory already exists");
  }
  let stagingCreated = false;
  try {
    await mkdir(dirname(paths.staging), { recursive: true });
    await mkdir(paths.staging, { recursive: false });
    stagingCreated = true;
  } catch {
    await releaseLedger(ledger, key);
    return blockedRecord(plan, at, "install.staging-create-failed", "could not create a fresh staging directory");
  }

  const cleanup = async (): Promise<void> => {
    if (stagingCreated) await rm(paths.staging, { recursive: true, force: true }).catch(() => undefined);
  };
  let exitCode: number;
  try {
    exitCode = (await runner(plan.command, { plan, stagingDir: paths.staging, target: paths.target })).exitCode;
  } catch {
    await cleanup();
    // Unknown side effects: retain reservation and fail closed.
    return recordResult(plan, at, "failed", fail(plan, at, "install.runner-error", "runner threw", clock()), false);
  }
  if (!Number.isInteger(exitCode) || exitCode !== 0) {
    await cleanup();
    await releaseLedger(ledger, key);
    return recordResult(plan, at, "failed", fail(plan, at, "install.failed", `exit ${String(exitCode)}`, clock()), false);
  }

  const contentVerification = await verifyFileSha256(paths.contentPath, plan.expectedSha256);
  if (!contentVerification.ok) {
    await cleanup();
    await releaseLedger(ledger, key);
    return blockedRecord(plan, at, "install.hash-mismatch", contentVerification.reason ?? "content hash mismatch");
  }
  const metadata = await verifyMetadata(plan, paths);
  if (!metadata.ok) {
    await cleanup();
    await releaseLedger(ledger, key);
    return blockedRecord(plan, at, metadata.code ?? "install.preflight-failed", metadata.reason ?? "install preflight failed");
  }

  try {
    const targetStat = await lstat(paths.target);
    if (targetStat.isSymbolicLink()) {
      await cleanup();
      await releaseLedger(ledger, key);
      return blockedRecord(plan, at, "install.target-symlink", "target symlink is not writable");
    }
    if (targetStat.isDirectory()) {
      const existing = await verifyFileSha256(join(paths.target, plan.contentFile ?? "SKILL.md"), plan.expectedSha256);
      await cleanup();
      if (existing.ok) {
        try {
          await ledger?.record(key);
        } catch {
          return recordResult(plan, at, "failed", fail(plan, at, "install.ledger-error", "install ledger write failed", clock()), false);
        }
        return recordResult(plan, at, "already-recorded", already(plan, at), true, undefined, plan.expectedSha256, metadata.sbomSha256);
      }
      await releaseLedger(ledger, key);
      return blockedRecord(plan, at, "install.target-conflict", "target exists with different content");
    }
    await cleanup();
    await releaseLedger(ledger, key);
    return blockedRecord(plan, at, "install.target-conflict", "target exists and is not a directory");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
      await cleanup();
      await releaseLedger(ledger, key);
      return blockedRecord(plan, at, "install.target-conflict", "target became unavailable");
    }
  }

  try {
    await mkdir(dirname(paths.target), { recursive: true });
    await rename(paths.staging, paths.target);
    stagingCreated = false;
  } catch (error) {
    await cleanup();
    await releaseLedger(ledger, key);
    const code = (error as NodeJS.ErrnoException).code === "EEXIST" ? "install.target-conflict" : "install.activate-failed";
    return blockedRecord(plan, at, code, "could not atomically activate staged install");
  }

  try {
    await ledger?.record(key);
  } catch {
    // Leave the activated result and reservation in place; retry must report
    // already-recorded rather than execute another external command.
    return recordResult(plan, at, "failed", fail(plan, at, "install.ledger-error", "install ledger write failed", clock()), false);
  }
  return recordResult(
    plan,
    at,
    "installed",
    receipt(plan, at, { approval: "approved", ok: true, resultHash: installResultHash(plan, plan.expectedSha256), finishedAt: clock() }),
    true,
    undefined,
    plan.expectedSha256,
    metadata.sbomSha256,
  );
}
