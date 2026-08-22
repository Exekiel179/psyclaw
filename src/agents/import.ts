import { constants } from "node:fs";
import {
  copyFile,
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  realpath,
  rm,
  writeFile,
} from "node:fs/promises";
import { createHash } from "node:crypto";
import { basename, dirname, extname, isAbsolute, join, relative, resolve, sep } from "node:path";
import type { ToolReceipt } from "../core/contracts.js";
import { redactSecrets } from "../core/redact.js";
import { sha256Text } from "../core/hash.js";
import type { AgentScan, DiscoveredSkill } from "./discover.js";

const IMPORT_SCHEMA_VERSION = "psyclaw/skill-import/v1" as const;
const IMPORT_RECEIPT_TOOL = "agents.import" as const;
const MAX_FILE_BYTES = 16 * 1024 * 1024;
const SHA256_RE = /^[a-f0-9]{64}$/i;
const ALLOWED_DIRECTORY_ROOTS = new Set(["references", "scripts", "assets"]);
const TEXT_EXTENSIONS = new Set([
  ".cjs", ".css", ".csv", ".html", ".js", ".json", ".md", ".mjs", ".py", ".r", ".rs", ".sh", ".sql",
  ".toml", ".ts", ".tsx", ".txt", ".xml", ".yaml", ".yml",
]);
const IMAGE_SIGNATURES: readonly ((bytes: Buffer) => boolean)[] = [
  (bytes) => bytes.length >= 8 && bytes.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])),
  (bytes) => bytes.length >= 3 && bytes.subarray(0, 3).equals(Buffer.from([0xff, 0xd8, 0xff])),
  (bytes) => bytes.length >= 6 && (bytes.subarray(0, 6).toString("ascii") === "GIF87a" || bytes.subarray(0, 6).toString("ascii") === "GIF89a"),
  (bytes) => bytes.length >= 12 && bytes.subarray(0, 4).toString("ascii") === "RIFF" && bytes.subarray(8, 12).toString("ascii") === "WEBP",
];

export interface ImportedFile {
  sourcePath: string;
  /** Canonical source path captured during the stable read. */
  resolvedSourcePath: string;
  destinationPath: string;
  /** Path relative to the imported skill root. */
  relativePath: string;
  sha256: string;
}

export interface ImportedSkill {
  name: string;
  kind: "dir" | "file";
  sourcePath: string;
  resolvedSourcePath: string;
  destinationPath: string;
  files: ImportedFile[];
}

export interface ImportDiagnostic {
  code: string;
  /** A path is included only after it has passed redaction and length bounds. */
  path?: string;
}

export interface SkillImportManifest {
  schemaVersion: typeof IMPORT_SCHEMA_VERSION;
  agentId: string;
  agentName: string;
  approval: { actor: string; reason: string };
  importedAt: string;
  skills: ImportedSkill[];
  diagnostics: ImportDiagnostic[];
  receipt: ToolReceipt;
}

export interface SkillImportResult {
  manifest: SkillImportManifest;
  manifestPath: string;
  importedCount: number;
  receipt: ToolReceipt;
}

export interface ImportAgentSkillsOptions {
  root: string;
  agent: AgentScan;
  approval: { approved: boolean; actor: string; reason: string };
  now?: () => string;
}

interface StatFingerprint {
  size: number;
  mtimeMs: number;
  ctimeMs: number;
  ino: number;
  dev: number;
  mode: number;
}

interface SourceFileSnapshot {
  sourcePath: string;
  resolvedSourcePath: string;
  relativePath: string;
  sha256: string;
  bytes: Buffer;
  stat: StatFingerprint;
}

interface SourceTreeSnapshot {
  rootPath: string;
  resolvedRootPath: string;
  files: SourceFileSnapshot[];
}

interface DestinationPlan {
  skill: DiscoveredSkill;
  destinationPath: string;
  source: SourceTreeSnapshot;
  status: "new" | "already-recorded";
}

/** Stable, non-sensitive import failure. Callers can inspect `code` without parsing prose. */
export class SkillImportError extends Error {
  public constructor(public readonly code: string, message = code) {
    super(message);
    this.name = "SkillImportError";
  }
}

function fail(code: string, message = code): never {
  throw new SkillImportError(code, message);
}

function samePath(left: string, right: string): boolean {
  const normalizedLeft = resolve(left).replaceAll("\\", "/");
  const normalizedRight = resolve(right).replaceAll("\\", "/");
  return process.platform === "win32"
    ? normalizedLeft.toLowerCase() === normalizedRight.toLowerCase()
    : normalizedLeft === normalizedRight;
}

function isWithin(base: string, candidate: string): boolean {
  const root = resolve(base).replaceAll("\\", "/");
  const target = resolve(candidate).replaceAll("\\", "/");
  const left = process.platform === "win32" ? root.toLowerCase() : root;
  const right = process.platform === "win32" ? target.toLowerCase() : target;
  return right !== left && right.startsWith(`${left}/`);
}

function isCrossPlatformAbsolute(value: string): boolean {
  const normalized = value.replaceAll("\\", "/");
  return normalized.startsWith("/") || /^\\\\/.test(value) || /^[A-Za-z]:/.test(value);
}

function isReservedDeviceName(value: string): boolean {
  const stem = value.split(".", 1)[0]?.toLowerCase() ?? value.toLowerCase();
  return /^(con|prn|aux|nul|com[1-9]|lpt[1-9])$/.test(stem);
}

function isSensitiveSegment(value: string): boolean {
  const lower = value.toLowerCase();
  return lower === ".env" || lower.startsWith(".env.") ||
    /(?:^|[._-])(credentials?|secrets?|tokens?|cookies?|auth|passwords?|passwd|pwd|api[-_]?key|access[-_]?key|private)(?:[._-]|$)/.test(lower) ||
    lower.endsWith(".pem") ||
    lower.endsWith(".key") || lower.endsWith(".p12") || lower.endsWith(".pfx") ||
    lower === ".npmrc" || lower === ".netrc" || lower === "id_rsa" || lower === "id_ed25519";
}

function isProtectedSegment(value: string): boolean {
  const lower = value.toLowerCase();
  return lower === ".git" || lower === "data" || lower === "raw";
}

function assertSafeSegment(value: string, label: string): void {
  if (
    value.length === 0 || value.length > 128 || value.trim() !== value || value === "." || value === ".." ||
    value.includes("/") || value.includes("\\") || value.includes(":") || /[\u0000-\u001f\u007f]/u.test(value) ||
    /[<>|?*\"]/.test(value) || /[. ]$/.test(value) || isReservedDeviceName(value) || isSensitiveSegment(value)
  ) {
    fail("import.path-invalid", `${label} is not an allowed path segment`);
  }
}

function boundedDisplay(value: string, fallback: string): string {
  const cleaned = redactSecrets(value).replace(/[\u0000-\u001f\u007f]/gu, " ").trim();
  if (cleaned.length === 0) return fallback;
  return cleaned.slice(0, 512);
}

function fingerprint(stat: { size: number; mtimeMs: number; ctimeMs: number; ino: number; dev: number; mode: number }): StatFingerprint {
  return { size: stat.size, mtimeMs: stat.mtimeMs, ctimeMs: stat.ctimeMs, ino: stat.ino, dev: stat.dev, mode: stat.mode };
}

function sameFingerprint(left: StatFingerprint, right: StatFingerprint): boolean {
  return left.size === right.size && left.mtimeMs === right.mtimeMs && left.ctimeMs === right.ctimeMs &&
    left.ino === right.ino && left.dev === right.dev && left.mode === right.mode;
}

function hashBytes(bytes: Buffer): string {
  return createHash("sha256").update(bytes).digest("hex");
}

async function assertNoSymlinkAncestors(path: string, boundary: string): Promise<void> {
  const absolute = resolve(path);
  const base = resolve(boundary);
  if (!samePath(base, absolute) && !isWithin(base, absolute)) fail("import.path-invalid", "path escapes its trusted boundary");
  const parts = relative(base, absolute).split(sep).filter(Boolean);
  let current = base;
  const candidates = [current, ...parts.map((part) => {
    current = join(current, part);
    return current;
  })];
  for (const candidate of candidates) {
    try {
      const stat = await lstat(candidate);
      if (stat.isSymbolicLink()) fail("import.symlink-path", "symbolic-link path is not importable");
    } catch (error) {
      if (error instanceof SkillImportError) throw error;
      if ((error as NodeJS.ErrnoException).code === "ENOENT") break;
      throw error;
    }
  }
}

async function assertProjectTarget(root: string, target: string): Promise<string> {
  const base = resolve(root);
  const absolute = resolve(target);
  if (!isWithin(base, absolute)) fail("import.target-containment");
  const rel = relative(base, absolute).replaceAll("\\", "/");
  const parts = rel.split("/").filter(Boolean);
  const lowerRel = parts.join("/").toLowerCase();
  if (parts.length === 0 || parts.some((part) => part === "." || part === ".." || isSensitiveSegment(part)) ||
      lowerRel === "data/raw" || lowerRel.startsWith("data/raw/")) {
    fail("import.target-protected");
  }
  if (parts.some((part) => isProtectedSegment(part))) {
    fail("import.target-protected");
  }
  await assertNoSymlinkAncestors(base, base);
  await assertNoSymlinkAncestors(absolute, base);
  return absolute;
}

async function ensureDirectoryChain(root: string, target: string, created: string[] = []): Promise<void> {
  const base = resolve(root);
  const absolute = resolve(target);
  if (!samePath(base, root) || !isWithin(base, absolute) && !samePath(base, absolute)) fail("import.target-containment");
  const parts = relative(base, absolute).split(sep).filter(Boolean);
  let current = base;
  for (const part of parts) {
    current = join(current, part);
    await assertNoSymlinkAncestors(current, base);
    try {
      const stat = await lstat(current);
      if (stat.isSymbolicLink()) fail("import.symlink-target");
      if (!stat.isDirectory()) fail("import.target-not-directory");
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      try {
        await mkdir(current, { recursive: false });
        created.push(current);
      } catch (mkdirError) {
        if ((mkdirError as NodeJS.ErrnoException).code !== "EEXIST") throw mkdirError;
        const stat = await lstat(current);
        if (stat.isSymbolicLink() || !stat.isDirectory()) fail("import.target-race");
      }
    }
  }
}

async function stableSourceFile(
  sourcePath: string,
  relativePath: string,
  boundaryPath: string,
  resolvedBoundaryPath: string,
): Promise<SourceFileSnapshot> {
  await assertNoSymlinkAncestors(sourcePath, boundaryPath);
  let before;
  try {
    before = await lstat(sourcePath);
  } catch {
    fail("import.source-unavailable");
  }
  if (before.isSymbolicLink() || !before.isFile()) fail("import.source-not-regular");
  if (before.size > MAX_FILE_BYTES) fail("import.source-too-large");
  const resolvedBefore = await realpath(sourcePath).catch(() => fail("import.source-unavailable"));
  const expectedResolved = resolve(resolvedBoundaryPath, relative(resolve(boundaryPath), resolve(sourcePath)));
  if (!samePath(resolvedBefore, expectedResolved)) fail("import.source-canonical");
  const bytes = await readFile(sourcePath).catch(() => fail("import.source-unavailable"));
  const digest = hashBytes(bytes);
  const after = await lstat(sourcePath).catch(() => fail("import.source-race"));
  const resolvedAfter = await realpath(sourcePath).catch(() => fail("import.source-race"));
  if (after.isSymbolicLink() || !after.isFile() || !samePath(resolvedBefore, resolvedAfter) ||
      !sameFingerprint(fingerprint(before), fingerprint(after)) || bytes.length !== after.size) {
    fail("import.source-race");
  }
  assertAllowedContent(relativePath, bytes);
  return {
    sourcePath: resolve(sourcePath),
    resolvedSourcePath: resolvedAfter,
    relativePath,
    sha256: digest,
    bytes,
    stat: fingerprint(after),
  };
}

function assertAllowedContent(relativePath: string, bytes: Buffer): void {
  const lower = relativePath.toLowerCase();
  const extension = extname(lower);
  if (bytes.length === 0) {
    if (TEXT_EXTENSIONS.has(extension)) return;
    fail("import.file-type-disallowed");
  }
  const header = bytes.subarray(0, 16);
  const executableMagic = header.subarray(0, 2).toString("ascii") === "MZ" ||
    header.subarray(0, 4).equals(Buffer.from([0x7f, 0x45, 0x4c, 0x46])) ||
    header.subarray(0, 4).equals(Buffer.from([0xfe, 0xed, 0xfa, 0xce])) ||
    header.subarray(0, 4).equals(Buffer.from([0xce, 0xfa, 0xed, 0xfe])) ||
    header.subarray(0, 4).equals(Buffer.from([0xca, 0xfe, 0xba, 0xbe]));
  const knownImage = [".gif", ".jpeg", ".jpg", ".png", ".webp"].includes(extension) &&
    IMAGE_SIGNATURES.some((check) => check(bytes));
  if (executableMagic || (!knownImage && bytes.includes(0))) fail("import.suspicious-binary");
  if (TEXT_EXTENSIONS.has(extension) || extension === "") {
    try {
      new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    } catch {
      fail("import.suspicious-binary");
    }
    // UTF-8 alone is not enough: arbitrary binary can be valid UTF-8. Reject
    // control bytes while retaining normal tabs/newlines in text scripts.
    for (const byte of bytes) {
      if (byte < 0x20 && byte !== 0x09 && byte !== 0x0a && byte !== 0x0d) fail("import.suspicious-binary");
    }
    return;
  }
  if (knownImage) return;
  fail("import.file-type-disallowed");
}

function assertAllowedRelativePath(parts: readonly string[], isDirectory: boolean): void {
  for (const part of parts) {
    assertSafeSegment(part, "source path");
    if (part.toLowerCase() === ".git") fail("import.file-not-allowlisted");
  }
  if (parts.length === 0) return;
  const first = parts[0]!.toLowerCase();
  if (parts.length === 1) {
    if (isDirectory) {
      if (!ALLOWED_DIRECTORY_ROOTS.has(first)) fail("import.file-not-allowlisted");
    } else if (parts[0] !== "SKILL.md" && !parts[0]!.toLowerCase().endsWith(".md")) {
      fail("import.file-not-allowlisted");
    }
    return;
  }
  if (!ALLOWED_DIRECTORY_ROOTS.has(first)) fail("import.file-not-allowlisted");
}

async function collectSourceTree(skill: DiscoveredSkill, boundaryPath: string): Promise<SourceTreeSnapshot> {
  const sourcePath = resolve(skill.path);
  const sourceBoundary = resolve(boundaryPath);
  if (isCrossPlatformAbsolute(skill.path.replaceAll("\\", "/")) === false) fail("import.source-path-invalid");
  if (!samePath(sourceBoundary, sourcePath) && !isWithin(sourceBoundary, sourcePath)) fail("import.source-root-mismatch");
  await assertNoSymlinkAncestors(sourcePath, sourceBoundary);
  const rootStat = await lstat(sourcePath).catch(() => fail("import.source-unavailable"));
  if (rootStat.isSymbolicLink()) fail("import.source-symlink");
  const rootKind = skill.kind === "dir" ? rootStat.isDirectory() : rootStat.isFile();
  if (!rootKind) fail("import.source-kind-mismatch");
  const resolvedBoundaryPath = await realpath(sourceBoundary).catch(() => fail("import.source-unavailable"));
  const resolvedRootPath = await realpath(sourcePath).catch(() => fail("import.source-unavailable"));
  const expectedRootPath = resolve(resolvedBoundaryPath, relative(sourceBoundary, sourcePath));
  if (!samePath(resolvedRootPath, expectedRootPath)) fail("import.source-canonical");

  const files: SourceFileSnapshot[] = [];
  if (skill.kind === "file") {
    const sourceName = basename(sourcePath);
    if (!sourceName.toLowerCase().endsWith(".md")) fail("import.file-not-allowlisted");
    assertAllowedRelativePath([sourceName], false);
    files.push(await stableSourceFile(sourcePath, sourceName, sourceBoundary, resolvedBoundaryPath));
  } else {
    let skillFileFound = false;
    const walk = async (directory: string, parts: string[]): Promise<void> => {
      await assertNoSymlinkAncestors(directory, sourceBoundary);
      const directoryStat = await lstat(directory).catch(() => fail("import.source-race"));
      if (directoryStat.isSymbolicLink() || !directoryStat.isDirectory()) fail("import.source-not-directory");
      const entries = await readdir(directory, { withFileTypes: true }).catch(() => fail("import.source-unavailable"));
      entries.sort((left, right) => left.name.localeCompare(right.name));
      for (const entry of entries) {
        assertSafeSegment(entry.name, "source path");
        const childParts = [...parts, entry.name];
        const child = join(directory, entry.name);
        if (entry.isSymbolicLink()) fail("import.source-symlink");
        if (entry.isDirectory()) {
          assertAllowedRelativePath(childParts, true);
          await walk(child, childParts);
        } else if (entry.isFile()) {
          assertAllowedRelativePath(childParts, false);
          if (childParts.length === 1 && entry.name === "SKILL.md") skillFileFound = true;
          files.push(await stableSourceFile(child, childParts.join("/"), sourceBoundary, resolvedBoundaryPath));
        } else {
          fail("import.source-not-regular");
        }
      }
    };
    await walk(sourcePath, []);
    if (!skillFileFound) fail("import.skill-entrypoint-missing");
  }

  const afterRoot = await lstat(sourcePath).catch(() => fail("import.source-race"));
  const afterResolved = await realpath(sourcePath).catch(() => fail("import.source-race"));
  if (afterRoot.isSymbolicLink() || !samePath(resolvedRootPath, afterResolved) || !sameFingerprint(fingerprint(rootStat), fingerprint(afterRoot))) {
    fail("import.source-race");
  }
  files.sort((left, right) => left.relativePath.localeCompare(right.relativePath));
  return { rootPath: sourcePath, resolvedRootPath, files };
}

async function verifySourceStable(before: SourceTreeSnapshot, skill: DiscoveredSkill): Promise<void> {
  const after = await collectSourceTree(skill, before.rootPath);
  if (!samePath(before.resolvedRootPath, after.resolvedRootPath) || before.files.length !== after.files.length) fail("import.source-race");
  for (let index = 0; index < before.files.length; index += 1) {
    const left = before.files[index]!;
    const right = after.files[index]!;
    if (left.relativePath !== right.relativePath || left.sha256 !== right.sha256 || !sameFingerprint(left.stat, right.stat) ||
      !samePath(left.resolvedSourcePath, right.resolvedSourcePath)) fail("import.source-race");
  }
}

async function declaredSourceRoot(agent: AgentScan, sourcePath: string): Promise<string> {
  if (agent.skillDirs.length === 0) fail("import.source-root-missing");
  const sourceResolved = await realpath(sourcePath).catch(() => fail("import.source-unavailable"));
  let matched: string | undefined;
  for (const candidate of agent.skillDirs) {
    if (!isAbsolute(candidate) || isCrossPlatformAbsolute(candidate.replaceAll("\\", "/")) === false) continue;
    await assertNoSymlinkAncestors(candidate, candidate);
    const stat = await lstat(candidate).catch(() => undefined);
    if (stat === undefined || stat.isSymbolicLink() || !stat.isDirectory()) continue;
    const resolved = await realpath(candidate).catch(() => undefined);
    if (resolved !== undefined && (samePath(resolved, sourceResolved) || isWithin(resolved, sourceResolved))) matched = resolve(candidate);
  }
  if (matched === undefined) fail("import.source-root-mismatch");
  return matched;
}

function sourceNameMatches(skill: DiscoveredSkill): void {
  if (typeof skill !== "object" || skill === null || typeof skill.name !== "string" || typeof skill.path !== "string") {
    fail("import.agent-scan-invalid");
  }
  if (skill.kind !== "dir" && skill.kind !== "file") fail("import.agent-scan-invalid");
  assertSafeSegment(skill.name, "skill name");
  const sourceName = basename(resolve(skill.path));
  const expected = skill.kind === "file" ? sourceName.replace(/\.md$/i, "") : sourceName;
  if (expected !== skill.name) fail("import.skill-name-mismatch");
}

function validateAgentScan(agent: AgentScan): void {
  if (typeof agent !== "object" || agent === null || typeof agent.id !== "string" || typeof agent.name !== "string" ||
      !Array.isArray(agent.skills) || !Array.isArray(agent.skillDirs)) fail("import.agent-scan-invalid");
  for (const skillDir of agent.skillDirs) {
    if (typeof skillDir !== "string") fail("import.agent-scan-invalid");
  }
}

async function inspectDestination(destinationPath: string, source: SourceTreeSnapshot, kind: "dir" | "file"): Promise<"new" | "already-recorded"> {
  let target;
  try {
    target = await lstat(destinationPath);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return "new";
    throw error;
  }
  if (target.isSymbolicLink()) fail("import.target-symlink");
  if (kind === "file") {
    if (!target.isFile()) fail("import.target-kind-conflict");
    const digest = await hashRegularFile(destinationPath);
    return digest === source.files[0]?.sha256 ? "already-recorded" : fail("import.target-conflict");
  }
  if (!target.isDirectory()) fail("import.target-kind-conflict");
  const actual = await collectDestinationFiles(destinationPath);
  if (actual.length !== source.files.length) fail("import.target-conflict");
  for (let index = 0; index < source.files.length; index += 1) {
    const expected = source.files[index]!;
    const found = actual[index]!;
    if (expected.relativePath !== found.relativePath || expected.sha256 !== found.sha256) fail("import.target-conflict");
  }
  return "already-recorded";
}

async function hashRegularFile(path: string): Promise<string> {
  const stat = await lstat(path).catch(() => fail("import.target-unavailable"));
  if (stat.isSymbolicLink() || !stat.isFile()) fail("import.target-not-regular");
  const resolvedBefore = await realpath(path).catch(() => fail("import.target-unavailable"));
  const bytes = await readFile(path).catch(() => fail("import.target-unavailable"));
  const digest = hashBytes(bytes);
  const after = await lstat(path).catch(() => fail("import.target-race"));
  const resolvedAfter = await realpath(path).catch(() => fail("import.target-race"));
  if (after.isSymbolicLink() || !after.isFile() || !samePath(resolvedBefore, resolvedAfter) ||
      !sameFingerprint(fingerprint(stat), fingerprint(after)) || after.size !== bytes.length) fail("import.target-race");
  return digest;
}

async function collectDestinationFiles(root: string): Promise<Array<{ relativePath: string; sha256: string }>> {
  const files: Array<{ relativePath: string; sha256: string }> = [];
  const walk = async (directory: string, parts: string[]): Promise<void> => {
    await assertNoSymlinkAncestors(directory, root);
    const entries = await readdir(directory, { withFileTypes: true }).catch(() => fail("import.target-unavailable"));
    entries.sort((left, right) => left.name.localeCompare(right.name));
    for (const entry of entries) {
      assertSafeSegment(entry.name, "target path");
      if (entry.isSymbolicLink()) fail("import.target-symlink");
      const child = join(directory, entry.name);
      const childParts = [...parts, entry.name];
      if (entry.isDirectory()) await walk(child, childParts);
      else if (entry.isFile()) files.push({ relativePath: childParts.join("/"), sha256: await hashRegularFile(child) });
      else fail("import.target-not-regular");
    }
  };
  await walk(root, []);
  return files;
}

function stableIdentity(agentId: string, plans: readonly DestinationPlan[]): string {
  const identity = plans.map((plan) => ({
    name: plan.skill.name,
    kind: plan.skill.kind,
    destinationPath: plan.destinationPath,
    sourcePath: plan.source.resolvedRootPath,
    files: plan.source.files.map((file) => [file.relativePath, file.sha256]),
  }));
  return sha256Text(JSON.stringify([agentId, identity]));
}

function importReceipt(agentId: string, idempotencyKey: string, startedAt: string, finishedAt: string, resultHash: string, alreadyRecorded = false): ToolReceipt {
  return {
    schemaVersion: "psyclaw/tool-receipt/v1",
    runId: `import:${agentId}`,
    taskId: agentId,
    tool: IMPORT_RECEIPT_TOOL,
    effect: "write",
    approval: "approved",
    idempotencyKey,
    ok: true,
    ...(alreadyRecorded ? { reasonCode: "import.already-recorded" } : {}),
    resultHash,
    startedAt,
    finishedAt,
  };
}

function manifestText(manifest: SkillImportManifest): string {
  return `${JSON.stringify(manifest, null, 2)}\n`;
}

async function writeNoClobber(path: string, contents: string): Promise<boolean> {
  try {
    await writeFile(path, contents, { encoding: "utf8", flag: "wx" });
    return true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
    const existing = await readFile(path, "utf8").catch(() => fail("import.manifest-unavailable"));
    if (existing !== contents) fail("import.manifest-conflict");
    return false;
  }
}

async function readExistingManifest(path: string, agent: AgentScan): Promise<SkillImportManifest | undefined> {
  const manifestStat = await lstat(path).catch((error) => {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return undefined;
    throw error;
  });
  if (manifestStat === undefined) return undefined;
  if (manifestStat.isSymbolicLink() || !manifestStat.isFile()) fail("import.manifest-invalid");
  let text;
  try {
    text = await readFile(path, "utf8");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return undefined;
    throw error;
  }
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    fail("import.manifest-invalid");
  }
  if (typeof value !== "object" || value === null) fail("import.manifest-invalid");
  const manifest = value as Partial<SkillImportManifest>;
  if (manifest.schemaVersion !== IMPORT_SCHEMA_VERSION || manifest.agentId !== agent.id || typeof manifest.agentName !== "string" ||
      typeof manifest.importedAt !== "string" || Number.isNaN(new Date(manifest.importedAt).getTime()) ||
      typeof manifest.approval !== "object" || manifest.approval === null ||
      typeof manifest.approval.actor !== "string" || typeof manifest.approval.reason !== "string" ||
      !Array.isArray(manifest.skills) || !manifest.skills.every(isImportedSkill) ||
      !Array.isArray(manifest.diagnostics) || !manifest.diagnostics.every(isImportDiagnostic) || !isToolReceipt(manifest.receipt)) {
    fail("import.manifest-conflict");
  }
  return manifest as SkillImportManifest;
}

function isRelativeManifestPath(value: unknown): value is string {
  if (typeof value !== "string" || value.length === 0 || isCrossPlatformAbsolute(value)) return false;
  const parts = value.replaceAll("\\", "/").split("/");
  return parts.every((part) => part.length > 0 && part !== "." && part !== ".." && !isSensitiveSegment(part) && !part.includes(":"));
}

function isImportedFile(value: unknown): value is ImportedFile {
  if (typeof value !== "object" || value === null) return false;
  const file = value as Partial<ImportedFile>;
  return typeof file.sourcePath === "string" && isCrossPlatformAbsolute(file.sourcePath) &&
    typeof file.resolvedSourcePath === "string" && isCrossPlatformAbsolute(file.resolvedSourcePath) &&
    typeof file.destinationPath === "string" && isCrossPlatformAbsolute(file.destinationPath) &&
    isRelativeManifestPath(file.relativePath) && typeof file.sha256 === "string" && SHA256_RE.test(file.sha256);
}

function isImportedSkill(value: unknown): value is ImportedSkill {
  if (typeof value !== "object" || value === null) return false;
  const skill = value as Partial<ImportedSkill>;
  return typeof skill.name === "string" && typeof skill.sourcePath === "string" && isCrossPlatformAbsolute(skill.sourcePath) &&
    typeof skill.resolvedSourcePath === "string" && isCrossPlatformAbsolute(skill.resolvedSourcePath) &&
    typeof skill.destinationPath === "string" && isCrossPlatformAbsolute(skill.destinationPath) &&
    (skill.kind === "dir" || skill.kind === "file") && Array.isArray(skill.files) && skill.files.every(isImportedFile);
}

function isImportDiagnostic(value: unknown): value is ImportDiagnostic {
  if (typeof value !== "object" || value === null) return false;
  const diagnostic = value as Partial<ImportDiagnostic>;
  return typeof diagnostic.code === "string" && /^[a-z0-9][a-z0-9._-]{0,127}$/.test(diagnostic.code) &&
    (diagnostic.path === undefined || (typeof diagnostic.path === "string" && diagnostic.path.length <= 512));
}

function isToolReceipt(value: unknown): value is ToolReceipt {
  if (typeof value !== "object" || value === null) return false;
  const receipt = value as Partial<ToolReceipt>;
  return receipt.schemaVersion === "psyclaw/tool-receipt/v1" &&
    typeof receipt.runId === "string" && receipt.runId.length > 0 &&
    typeof receipt.taskId === "string" && receipt.taskId.length > 0 &&
    receipt.tool === IMPORT_RECEIPT_TOOL && receipt.effect === "write" && receipt.approval === "approved" &&
    receipt.ok === true && typeof receipt.idempotencyKey === "string" && receipt.idempotencyKey.length > 0 &&
    typeof receipt.resultHash === "string" && SHA256_RE.test(receipt.resultHash) &&
    typeof receipt.startedAt === "string" && !Number.isNaN(new Date(receipt.startedAt).getTime()) &&
    typeof receipt.finishedAt === "string" && !Number.isNaN(new Date(receipt.finishedAt).getTime()) &&
    (receipt.reasonCode === undefined || /^[a-z0-9][a-z0-9._-]{0,63}$/.test(receipt.reasonCode));
}

async function manifestMatchesPlans(
  manifest: SkillImportManifest,
  plans: readonly DestinationPlan[],
  idempotencyKey: string,
  agentId: string,
  resultHash: string,
): Promise<boolean> {
  if (manifest.receipt.idempotencyKey !== idempotencyKey || manifest.receipt.runId !== `import:${agentId}` ||
      manifest.receipt.taskId !== agentId || manifest.receipt.resultHash !== resultHash ||
      new Date(manifest.receipt.finishedAt).getTime() < new Date(manifest.receipt.startedAt).getTime()) return false;
  if (manifest.skills.length !== plans.length) return false;
  for (const plan of plans) {
    const existing = manifest.skills.find((skill) => skill.name === plan.skill.name && skill.kind === plan.skill.kind);
    if (existing === undefined || !samePath(existing.destinationPath, plan.destinationPath) ||
        !samePath(existing.resolvedSourcePath, plan.source.resolvedRootPath) || existing.files.length !== plan.source.files.length) return false;
    for (const file of plan.source.files) {
      const found = existing.files.find((candidate) => candidate.relativePath === file.relativePath);
      if (found === undefined || found.sha256 !== file.sha256 || !samePath(found.resolvedSourcePath, file.resolvedSourcePath) ||
          !samePath(found.destinationPath, join(plan.destinationPath, file.relativePath))) return false;
    }
  }
  return true;
}

async function activatePlan(plan: DestinationPlan, stagingRoot: string, targetRoot: string, created: string[]): Promise<boolean> {
  if (plan.status === "already-recorded") return false;
  const source = plan.source;
  const destination = plan.destinationPath;
  await assertNoSymlinkAncestors(dirname(destination), targetRoot);
  if (plan.skill.kind === "file") {
    await ensureDirectoryChain(stagingRoot, dirname(join(stagingRoot, "__placeholder__")), []);
    try {
      await copyFile(join(stagingRoot, plan.skill.name + ".md"), destination, constants.COPYFILE_EXCL);
      created.push(destination);
      return true;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
      const current = await inspectDestination(destination, source, "file");
      if (current === "already-recorded") return false;
      fail("import.target-conflict");
    }
  }

  let targetCreated = false;
  try {
    await mkdir(destination, { recursive: false });
    targetCreated = true;
    created.push(destination);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
    const current = await inspectDestination(destination, source, "dir");
    if (current === "already-recorded") return false;
    fail("import.target-conflict");
  }
  try {
    for (const file of source.files) {
      const staged = join(stagingRoot, plan.skill.name, file.relativePath);
      const target = join(destination, file.relativePath);
      const targetParent = dirname(target);
      await ensureDirectoryChain(destination, targetParent, created);
      try {
        await copyFile(staged, target, constants.COPYFILE_EXCL);
        created.push(target);
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
        const digest = await hashRegularFile(target);
        if (digest !== file.sha256) fail("import.target-conflict");
      }
    }
    const finalStatus = await inspectDestination(destination, source, "dir");
    if (finalStatus !== "already-recorded") fail("import.activation-unverified");
    return targetCreated || source.files.length > 0;
  } catch (error) {
    throw error;
  }
}

async function rollbackCreated(paths: readonly string[]): Promise<void> {
  for (const path of [...paths].reverse()) {
    try {
      const stat = await lstat(path);
      if (stat.isSymbolicLink()) continue;
      await rm(path, { recursive: stat.isDirectory(), force: true });
    } catch {
      // Rollback is best-effort; never replace the original deterministic failure.
    }
  }
}

/**
 * Import only a discovered agent's allowlisted, stable Skill files. The source
 * tree is copied to a private staging directory first; activation uses
 * no-clobber primitives and every manifest is itself no-clobber/idempotent.
 * Importing never enables a Skill.
 */
export async function importAgentSkills(options: ImportAgentSkillsOptions): Promise<SkillImportResult> {
  if (typeof options !== "object" || options === null || typeof options.root !== "string" ||
      typeof options.approval !== "object" || options.approval === null ||
      typeof options.approval.actor !== "string" || typeof options.approval.reason !== "string" ||
      (options.now !== undefined && typeof options.now !== "function")) {
    fail("import.options-invalid");
  }
  validateAgentScan(options.agent);
  if (options.approval.approved !== true) throw new SkillImportError("import.approval-required", "Skill import requires explicit approval");
  const clock = options.now ?? (() => new Date().toISOString());
  const startedAt = clock();
  if (Number.isNaN(new Date(startedAt).getTime())) fail("import.invalid-clock");
  const agentId = options.agent.id;
  assertSafeSegment(agentId, "agent id");
  const actor = boundedDisplay(options.approval.actor, "unknown");
  const reason = boundedDisplay(options.approval.reason, "explicit approval");
  const agentName = boundedDisplay(options.agent.name, agentId);
  const root = resolve(options.root);
  const rootStat = await lstat(root).catch(() => fail("import.project-unavailable"));
  if (rootStat.isSymbolicLink() || !rootStat.isDirectory()) fail("import.project-invalid");
  await assertNoSymlinkAncestors(root, root);
  const importsRoot = await assertProjectTarget(root, join(root, ".psyclaw", "imports"));
  const destinationRoot = await assertProjectTarget(root, join(importsRoot, agentId));
  await ensureDirectoryChain(root, importsRoot);
  await ensureDirectoryChain(root, destinationRoot);

  const plans: DestinationPlan[] = [];
  for (const skill of options.agent.skills) {
    sourceNameMatches(skill);
    const sourceBoundary = await declaredSourceRoot(options.agent, skill.path);
    const source = await collectSourceTree(skill, sourceBoundary);
    const destinationPath = await assertProjectTarget(
      root,
      skill.kind === "dir" ? join(destinationRoot, skill.name) : join(destinationRoot, `${skill.name}.md`),
    );
    const status = await inspectDestination(destinationPath, source, skill.kind);
    plans.push({ skill, destinationPath, source, status });
  }
  plans.sort((left, right) => left.skill.name.localeCompare(right.skill.name));
  const idHash = stableIdentity(agentId, plans);
  const idempotencyKey = `import:skills:${agentId}:${idHash.slice(0, 32)}`;
  const manifestPath = join(destinationRoot, "import-manifest.json");
  await assertProjectTarget(root, manifestPath);
  const existingManifest = await readExistingManifest(manifestPath, options.agent);
  if (existingManifest !== undefined) {
    if (!await manifestMatchesPlans(existingManifest, plans, idempotencyKey, agentId, idHash)) fail("import.manifest-conflict");
    // A prior manifest is a durable idempotency record. Destination and source
    // snapshots above were still checked, so a changed source cannot silently
    // masquerade as an already-recorded import.
    const receipt = importReceipt(agentId, idempotencyKey, startedAt, startedAt, idHash, true);
    return { manifest: existingManifest, manifestPath, importedCount: 0, receipt };
  }

  const stagingPrefix = join(importsRoot, `.staging-${agentId}-`);
  const stagingRoot = await mkdtemp(stagingPrefix);
  const activated: string[] = [];
  try {
    for (const plan of plans) {
      if (plan.status === "already-recorded") continue;
      const skillStage = join(stagingRoot, plan.skill.name);
      if (plan.skill.kind === "dir") await ensureDirectoryChain(stagingRoot, skillStage);
      for (const file of plan.source.files) {
        const stagedPath = join(stagingRoot, plan.skill.kind === "dir" ? plan.skill.name : "", file.relativePath);
        await ensureDirectoryChain(stagingRoot, dirname(stagedPath));
        await writeFile(stagedPath, file.bytes, { flag: "wx" });
      }
      await verifySourceStable(plan.source, plan.skill);
    }
    for (const plan of plans) await activatePlan(plan, stagingRoot, root, activated);
    const finishedAt = clock();
    if (Number.isNaN(new Date(finishedAt).getTime()) || new Date(finishedAt).getTime() < new Date(startedAt).getTime()) {
      fail("import.invalid-clock");
    }
    const importedSkills: ImportedSkill[] = plans.map((plan) => ({
      name: plan.skill.name,
      kind: plan.skill.kind,
      sourcePath: plan.source.rootPath,
      resolvedSourcePath: plan.source.resolvedRootPath,
      destinationPath: plan.destinationPath,
      files: plan.source.files.map((file) => ({
        sourcePath: file.sourcePath,
        resolvedSourcePath: file.resolvedSourcePath,
        destinationPath: join(plan.destinationPath, file.relativePath),
        relativePath: file.relativePath,
        sha256: file.sha256,
      })),
    }));
    const receipt = importReceipt(agentId, idempotencyKey, startedAt, finishedAt, idHash);
    const manifest: SkillImportManifest = {
      schemaVersion: IMPORT_SCHEMA_VERSION,
      agentId,
      agentName,
      approval: { actor, reason },
      importedAt: startedAt,
      skills: importedSkills,
      diagnostics: [
        { code: "source.canonical-and-hash-verified" },
        { code: "content.allowlist-enforced" },
        { code: "target.no-clobber-enforced" },
        { code: "import.does-not-enable-skill" },
      ],
      receipt,
    };
    await writeNoClobber(manifestPath, manifestText(manifest));
    const importedCount = plans.filter((plan) => plan.status === "new").length;
    return { manifest, manifestPath, importedCount, receipt };
  } catch (error) {
    await rollbackCreated(activated);
    throw error;
  } finally {
    await rm(stagingRoot, { recursive: true, force: true }).catch(() => undefined);
  }
}
