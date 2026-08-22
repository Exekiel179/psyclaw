import { createHash } from "node:crypto";
import { lstat, readdir, readFile, realpath } from "node:fs/promises";
import { isAbsolute, join, relative, resolve, sep } from "node:path";
import { parse as parseYaml } from "yaml";
import {
  type LoadedSkill,
  type SkillApproval,
  type SkillAdmissionEvidence,
  type SkillApprovalEntry,
  type SkillApprovalMap,
  type SkillApprovalStatus,
  type SkillDependencyStatus,
  type SkillDescriptor,
  type SkillDiagnostic,
  type SkillDiscoveryReport,
  type SkillLicenseStatus,
  type SkillRegistryOptions,
  type SkillRiskLevel,
  type SkillSearchOptions,
  type SkillTrustStatus,
  SKILL_DESCRIPTOR_VERSION,
} from "./contracts.js";
import { preflightSkillBody } from "./preflight.js";

type Metadata = Record<string, unknown>;

const LICENSE_STATUSES = new Set<SkillLicenseStatus>([
  "verified",
  "declared",
  "missing",
  "invalid",
  "unknown",
]);
const DEPENDENCY_STATUSES = new Set<SkillDependencyStatus>([
  "ready",
  "declared",
  "missing",
  "blocked",
  "unknown",
]);
const TRUST_STATUSES = new Set<SkillTrustStatus>(["trusted", "untrusted", "blocked", "unknown"]);
const RISK_LEVELS = new Set<SkillRiskLevel>(["low", "medium", "high", "critical", "unknown"]);

function diagnostic(
  code: SkillDiagnostic["code"],
  message: string,
  path?: string,
  extra: Partial<Pick<SkillDiagnostic, "skillId" | "relatedPaths" | "severity">> = {},
): SkillDiagnostic {
  return {
    code,
    message,
    ...(path === undefined ? {} : { path }),
    severity: extra.severity ?? (code === "duplicate-id" || code === "path-traversal" || code === "symlink-path" ? "error" : "warning"),
    ...(extra.skillId === undefined ? {} : { skillId: extra.skillId }),
    ...(extra.relatedPaths === undefined ? {} : { relatedPaths: extra.relatedPaths }),
  };
}

function nonEmptyString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : undefined;
}

function metadataString(metadata: Metadata, ...keys: string[]): string | undefined {
  for (const key of keys) {
    const value = nonEmptyString(metadata[key]);
    if (value !== undefined) return value;
  }
  return undefined;
}

function statusFromMetadata<T extends string>(
  metadata: Metadata,
  keys: string[],
  allowed: ReadonlySet<T>,
  fallback: T,
): T {
  const value = metadataString(metadata, ...keys) as T | undefined;
  return value !== undefined && allowed.has(value) ? value : fallback;
}

function deriveLicenseStatus(metadata: Metadata): SkillLicenseStatus {
  // A skill cannot self-certify "verified": the frontmatter alone can only
  // declare a license or report it missing. Verification comes from a host
  // manifest/preflight, never from the skill's own claim.
  const license = nonEmptyString(metadata.license);
  return license === undefined ? "missing" : "declared";
}

function hasDependencies(metadata: Metadata): boolean {
  const dependencies = metadata.dependencies;
  if (Array.isArray(dependencies)) return dependencies.length > 0;
  if (dependencies !== null && typeof dependencies === "object") return Object.keys(dependencies as object).length > 0;
  return nonEmptyString(dependencies) !== undefined;
}

function deriveDependencyStatus(metadata: Metadata): SkillDependencyStatus {
  // "ready" is a host determination that declared dependencies are
  // satisfiable; the frontmatter can only declare or omit dependencies.
  return hasDependencies(metadata) ? "declared" : "ready";
}

function deriveTrust(metadata: Metadata): SkillTrustStatus {
  // Trust is host-decided. A self-declared "blocked" is honored as explicit
  // self-exclusion; self-declared "trusted"/"untrusted" are not taken at face
  // value and remain "unknown" until the host approves.
  const value = metadataString(metadata, "trust", "trustStatus", "trust_status");
  return value === "blocked" ? "blocked" : "unknown";
}

function deriveRisk(metadata: Metadata): SkillRiskLevel {
  return statusFromMetadata(metadata, ["risk", "riskLevel", "risk_level"], RISK_LEVELS, "unknown");
}

function isPlainRecord(value: unknown): value is Metadata {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function rejectTraversal(input: string): void {
  const normalized = input.replaceAll("\\", "/");
  const withoutDrive = normalized.replace(/^[A-Za-z]:\/?/, "");
  if (withoutDrive.split("/").some((segment) => segment === "..")) {
    throw new Error(`Path traversal is not allowed: ${input}`);
  }
}

function assertContained(root: string, target: string): void {
  const rel = relative(root, target).replaceAll("\\", "/");
  if (rel === ".." || rel.startsWith("../") || isAbsolute(rel) || rel.startsWith("/")) {
    throw new Error(`Path escapes skill root: ${target}`);
  }
}

interface ParsedSkill {
  metadata: Metadata;
  body: string;
}

/** Parse only the leading YAML document and return the Markdown body separately. */
function parseSkillDocument(text: string, path: string): ParsedSkill {
  const normalized = text.replace(/^\uFEFF/, "");
  const opening = normalized.match(/^---[ \t]*\r?\n/);
  if (opening === null) throw new Error(`SKILL.md must start with YAML frontmatter: ${path}`);
  const start = opening[0].length;
  const closing = /^(---|\.\.\.)[ \t]*(?:\r?\n|$)/m.exec(normalized.slice(start));
  if (closing === null) throw new Error(`YAML frontmatter is not terminated: ${path}`);
  const yamlText = normalized.slice(start, start + closing.index);
  let parsed: unknown;
  try {
    parsed = parseYaml(yamlText);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`Invalid YAML frontmatter: ${message}`);
  }
  if (parsed === null || parsed === undefined) parsed = {};
  if (!isPlainRecord(parsed)) throw new Error(`YAML frontmatter must be a mapping: ${path}`);
  const body = normalized.slice(start + closing.index + closing[0].length);
  return { metadata: parsed, body };
}

function skillIdentity(metadata: Metadata, filePath: string): { id: string; name: string; description: string } {
  const name = nonEmptyString(metadata.name);
  const description = nonEmptyString(metadata.description);
  if (name === undefined || description === undefined) {
    throw new Error("Frontmatter requires non-empty name and description");
  }
  const id = nonEmptyString(metadata.id) ?? name;
  // IDs are lookup keys, never paths. Refuse separators and traversal markers.
  if (id.includes("/") || id.includes("\\") || id === "." || id === ".." || id.trim() !== id) {
    throw new Error(`Invalid skill id: ${id}`);
  }
  if (id.length > 128) throw new Error(`Skill id is too long: ${id}`);
  void filePath;
  return { id, name, description };
}

async function assertRoot(rootInput: string): Promise<{ source: string; resolved: string }> {
  rejectTraversal(rootInput);
  const source = resolve(rootInput);
  const stat = await lstat(source);
  if (stat.isSymbolicLink()) throw new Error(`Skill root is a symlink: ${source}`);
  if (!stat.isDirectory()) throw new Error(`Skill root is not a directory: ${source}`);
  return { source, resolved: await realpath(source) };
}

async function walkSkillFiles(root: { source: string; resolved: string }, diagnostics: SkillDiagnostic[]): Promise<string[]> {
  const files: string[] = [];
  const visit = async (directory: string): Promise<void> => {
    let entries;
    try {
      entries = await readdir(directory, { withFileTypes: true });
    } catch (error) {
      diagnostics.push(diagnostic("read-error", `Unable to read skill directory: ${String(error)}`, directory));
      return;
    }
    for (const entry of entries) {
      const candidate = resolve(directory, entry.name);
      try {
        assertContained(root.resolved, await realpath(directory));
      } catch (error) {
        diagnostics.push(diagnostic("path-traversal", String(error), candidate));
        continue;
      }
      if (entry.isSymbolicLink()) {
        diagnostics.push(diagnostic("symlink-path", "Symlinked skill paths are not allowed", candidate));
        continue;
      }
      if (entry.isDirectory()) {
        await visit(candidate);
      } else if (entry.isFile() && entry.name === "SKILL.md") {
        files.push(candidate);
      }
    }
  };
  await visit(root.source);
  return files;
}

async function verifyFilePath(sourcePath: string, rootPath: string): Promise<string> {
  const sourceRoot = resolve(rootPath);
  const source = resolve(sourcePath);
  assertContained(sourceRoot, source);
  const rootStat = await lstat(sourceRoot);
  if (rootStat.isSymbolicLink()) throw new Error(`Skill root is a symlink: ${sourceRoot}`);
  if (!rootStat.isDirectory()) throw new Error(`Skill root is not a directory: ${sourceRoot}`);
  const resolvedRoot = await realpath(sourceRoot);
  let cursor = sourceRoot;
  for (const part of relative(sourceRoot, source).split(sep).filter(Boolean)) {
    cursor = join(cursor, part);
    const stat = await lstat(cursor);
    if (stat.isSymbolicLink()) throw new Error(`Skill path contains a symlink: ${sourcePath}`);
  }
  const sourceStat = await lstat(source);
  if (sourceStat.isSymbolicLink()) throw new Error(`Skill file is a symlink: ${sourcePath}`);
  if (!sourceStat.isFile()) throw new Error(`Skill path is not a file: ${sourcePath}`);
  const resolved = await realpath(source);
  assertContained(resolvedRoot, resolved);
  const expectedResolved = resolve(resolvedRoot, relative(sourceRoot, source));
  // Compare paths relative to the controlled root. Ancestors above that root
  // may legitimately be OS-managed aliases such as macOS /var -> /private/var.
  if (!samePath(expectedResolved, resolved)) {
    throw new Error(`Skill path contains a symlink or changed while reading: ${sourcePath}`);
  }
  return resolved;
}

function samePath(left: string, right: string): boolean {
  const normalize = process.platform === "win32"
    ? (value: string) => value.replace(/[\\/]+/g, "\\").replace(/\\$/, "").toLocaleLowerCase()
    : (value: string) => value;
  const normalizedLeft = normalize(left);
  const normalizedRight = normalize(right);
  return normalizedLeft === normalizedRight;
}

function pathKey(value: string): string {
  return process.platform === "win32" ? value.toLocaleLowerCase() : value;
}

interface StableSkillRead {
  text: string;
  sha256: string;
  resolvedPath: string;
}

/**
 * Read a skill twice with canonical-path checks around the reads.  This is a
 * small, fail-closed TOCTOU guard: if a path is swapped, symlinked, or
 * modified while it is being inspected, discovery/load refuses the file.
 */
async function readSkillFileStable(sourcePath: string, rootPath: string): Promise<StableSkillRead> {
  const before = await verifyFilePath(sourcePath, rootPath);
  const firstBytes = await readFile(before);
  const firstText = firstBytes.toString("utf8");
  const firstHash = createHash("sha256").update(firstBytes).digest("hex");
  const after = await verifyFilePath(sourcePath, rootPath);
  if (!samePath(before, after)) {
    throw new Error(`Skill path changed while reading: ${sourcePath}`);
  }
  const secondBytes = await readFile(after);
  const secondText = secondBytes.toString("utf8");
  const secondHash = createHash("sha256").update(secondBytes).digest("hex");
  if (firstHash !== secondHash || !firstBytes.equals(secondBytes)) {
    throw new Error(`Skill changed while reading: ${sourcePath}`);
  }
  const finalPath = await verifyFilePath(sourcePath, rootPath);
  if (!samePath(after, finalPath)) {
    throw new Error(`Skill path changed after reading: ${sourcePath}`);
  }
  return { text: firstText, sha256: firstHash, resolvedPath: finalPath };
}

function approvalEntry(approvals: SkillApprovalMap, id: string): SkillApprovalEntry | undefined {
  if (approvals instanceof Map) return approvals.get(id);
  const record = approvals as Readonly<Record<string, SkillApprovalEntry>>;
  return Object.prototype.hasOwnProperty.call(record, id) ? record[id] : undefined;
}

function isValidApproval(value: unknown): value is SkillApproval {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const candidate = value as Record<string, unknown>;
  if (typeof candidate.approved !== "boolean") return false;
  if (candidate.sha256 !== undefined &&
      (typeof candidate.sha256 !== "string" || !/^[a-f0-9]{64}$/i.test(candidate.sha256))) return false;
  if (candidate.sourcePath !== undefined && typeof candidate.sourcePath !== "string") return false;
  if (candidate.resolvedPath !== undefined && typeof candidate.resolvedPath !== "string") return false;
  if (candidate.admission !== undefined && !isValidAdmissionEvidence(candidate.admission)) return false;
  return true;
}

function isValidAdmissionEvidence(value: unknown): value is SkillAdmissionEvidence {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const candidate = value as Record<string, unknown>;
  return candidate.schemaVersion === "psyclaw/skill-admission/v1" &&
    typeof candidate.contentSha256 === "string" && /^[a-f0-9]{64}$/i.test(candidate.contentSha256) &&
    typeof candidate.licenseSpdx === "string" && candidate.licenseSpdx.trim() !== "" &&
    candidate.licenseSpdx.toLocaleLowerCase() !== "unknown" &&
    typeof candidate.licenseEvidenceRef === "string" && candidate.licenseEvidenceRef.trim() !== "" &&
    typeof candidate.dependencyEvidenceRef === "string" && candidate.dependencyEvidenceRef.trim() !== "" &&
    typeof candidate.sbomSha256 === "string" && /^[a-f0-9]{64}$/i.test(candidate.sbomSha256);
}

function copyApproval(entry: SkillApprovalEntry): SkillApprovalEntry {
  if (typeof entry === "boolean") return entry;
  if (!isValidApproval(entry)) return false;
  return Object.freeze({
    approved: entry.approved,
    ...(entry.sha256 === undefined ? {} : { sha256: entry.sha256.toLocaleLowerCase() }),
    ...(entry.sourcePath === undefined ? {} : { sourcePath: entry.sourcePath }),
    ...(entry.resolvedPath === undefined ? {} : { resolvedPath: entry.resolvedPath }),
    ...(entry.admission === undefined ? {} : {
      admission: Object.freeze({
        schemaVersion: entry.admission.schemaVersion,
        contentSha256: entry.admission.contentSha256.toLocaleLowerCase(),
        licenseSpdx: entry.admission.licenseSpdx,
        licenseEvidenceRef: entry.admission.licenseEvidenceRef,
        dependencyEvidenceRef: entry.admission.dependencyEvidenceRef,
        sbomSha256: entry.admission.sbomSha256.toLocaleLowerCase(),
      }),
    }),
  });
}

function pathMatchesPin(
  pin: string | undefined,
  descriptor: Pick<SkillDescriptor, "sourcePath" | "resolvedPath" | "rootPath">,
): boolean {
  if (pin === undefined) return true;
  const normalizedPin = pin.replaceAll("\\", "/");
  if (normalizedPin.split("/").some((segment) => segment === "..")) return false;
  const resolvedPin = resolve(pin);
  const rootRelativePin = resolve(descriptor.rootPath, pin);
  return samePath(resolvedPin, descriptor.sourcePath) ||
    samePath(resolvedPin, descriptor.resolvedPath) ||
    samePath(rootRelativePin, descriptor.sourcePath) ||
    samePath(rootRelativePin, descriptor.resolvedPath);
}

function approvalFor(
  descriptor: Pick<SkillDescriptor, "id" | "sha256" | "sourcePath" | "resolvedPath" | "rootPath" | "trust">,
  approvals: SkillApprovalMap,
): SkillApprovalStatus {
  if (descriptor.trust === "blocked") return "blocked";
  const entry = approvalEntry(approvals, descriptor.id);
  if (entry === undefined) return "discover-only";
  const approval: SkillApproval = typeof entry === "boolean"
    ? { approved: entry }
    : isValidApproval(entry)
      ? entry
      : { approved: false };
  if (!approval.approved) return "blocked";
  // A path/content pin is not a license or dependency audit.  Require a
  // host-generated admission record before allowing executable content.
  // Frontmatter-derived license/dependency values never upgrade this record;
  // a verified external manifest may cover a skill whose frontmatter is terse.
  if (!approval.admission || !isValidAdmissionEvidence(approval.admission)) return "discover-only";
  if (approval.admission.contentSha256.toLocaleLowerCase() !== descriptor.sha256) return "stale";
  // A no-pin approval (e.g. the `approvedIds` id shorthand) cannot grant
  // execution; a content SHA or path pin must bind the approval to the
  // discovered skill.
  const hasPin = approval.sha256 !== undefined ||
    approval.sourcePath !== undefined ||
    approval.resolvedPath !== undefined;
  if (!hasPin) return "discover-only";
  if (approval.sha256 !== undefined && approval.sha256.toLocaleLowerCase() !== descriptor.sha256) return "stale";
  if (!pathMatchesPin(approval.sourcePath, descriptor) || !pathMatchesPin(approval.resolvedPath, descriptor)) return "stale";
  return "approved";
}

export class SkillRegistry {
  private readonly roots: string[];
  private readonly approvals: ReadonlyMap<string, SkillApprovalEntry>;
  private readonly entries = new Map<string, SkillDescriptor[]>();
  private readonly diagnosticLog: SkillDiagnostic[] = [];

  constructor(roots?: string[]);
  constructor(options?: SkillRegistryOptions);
  constructor(rootsOrOptions: string[] | SkillRegistryOptions = []) {
    if (Array.isArray(rootsOrOptions)) {
      this.roots = [...rootsOrOptions];
      this.approvals = new Map();
    } else {
      this.roots = [...(rootsOrOptions.roots ?? [])];
      // `enableByDefault` is retained in the public options only so existing
      // callers fail safely after upgrade; frontmatter can never approve a
      // skill. Explicit approvals always come from the host options.
      const merged = new Map<string, SkillApprovalEntry>();
      const configured = rootsOrOptions.approvals ?? rootsOrOptions.approvalMap ?? rootsOrOptions.approval;
      if (configured !== undefined) {
        if (configured instanceof Map) {
          for (const [id, entry] of configured.entries()) merged.set(id, copyApproval(entry));
        } else {
          for (const [id, entry] of Object.entries(configured)) merged.set(id, copyApproval(entry));
        }
      }
      for (const id of rootsOrOptions.approvedIds ?? []) {
        // An explicit deny in the richer map wins over the shorthand list.
        if (!merged.has(id)) merged.set(id, true);
      }
      this.approvals = merged;
      void rootsOrOptions.enableByDefault;
    }
  }

  async discover(roots: string[] = this.roots): Promise<SkillDiscoveryReport> {
    this.entries.clear();
    this.diagnosticLog.length = 0;
    const seenPaths = new Set<string>();
    for (const rootInput of roots) {
      let root: { source: string; resolved: string };
      try {
        root = await assertRoot(rootInput);
      } catch (error) {
        const code = /symlink/i.test(String(error))
          ? "root-symlink"
          : /not a directory/i.test(String(error))
            ? "root-not-directory"
            : /ENOENT|not found/i.test(String(error))
              ? "root-not-found"
              : /traversal/i.test(String(error))
                ? "path-traversal"
                : "read-error";
        this.diagnosticLog.push(diagnostic(code, String(error), resolve(rootInput)));
        continue;
      }
      const files = await walkSkillFiles(root, this.diagnosticLog);
      for (const sourcePath of files) {
        let descriptor: SkillDescriptor;
        try {
          const stable = await readSkillFileStable(sourcePath, root.source);
          const resolvedPath = stable.resolvedPath;
          const text = stable.text;
          const parsed = parseSkillDocument(text, sourcePath);
          const identity = skillIdentity(parsed.metadata, sourcePath);
          const preflight = preflightSkillBody(parsed.body);
          const resolvedKey = pathKey(resolvedPath);
          if (seenPaths.has(resolvedKey)) continue;
          seenPaths.add(resolvedKey);
          if (preflight.suspicious) {
            this.diagnosticLog.push(diagnostic(
              "suspicious-body",
              `Skill body contains suspicious instructions: ${preflight.findings.join(", ")}`,
              sourcePath,
              { severity: "error", skillId: identity.id },
            ));
          }
          const baseDescriptor: Omit<SkillDescriptor, "approvalStatus"> = {
            schemaVersion: SKILL_DESCRIPTOR_VERSION,
            id: identity.id,
            name: identity.name,
            description: identity.description,
            sourcePath,
            resolvedPath,
            rootPath: root.source,
            sha256: stable.sha256,
            licenseStatus: deriveLicenseStatus(parsed.metadata),
            dependencyStatus: deriveDependencyStatus(parsed.metadata),
            trust: preflight.suspicious ? "blocked" : deriveTrust(parsed.metadata),
            risk: preflight.suspicious ? "critical" : deriveRisk(parsed.metadata),
            enabled: false,
            conflicted: false,
            metadata: Object.freeze({ ...parsed.metadata }),
          };
          descriptor = Object.freeze({
            ...baseDescriptor,
            approvalStatus: approvalFor(baseDescriptor, this.approvals),
          });
        } catch (error) {
          const message = String(error);
          const code: SkillDiagnostic["code"] = /frontmatter|YAML/i.test(message)
            ? "invalid-frontmatter"
            : /id|name and description/i.test(message)
              ? "invalid-metadata"
              : /hash/i.test(message)
                ? "hash-error"
                : /symlink/i.test(message)
                  ? "symlink-path"
                  : "read-error";
          this.diagnosticLog.push(diagnostic(code, message, sourcePath));
          continue;
        }
        const candidates = this.entries.get(descriptor.id) ?? [];
        if (candidates.length > 0 && candidates.every((item) => item.resolvedPath !== descriptor.resolvedPath)) {
          descriptor = { ...descriptor, conflicted: true };
          const marked = candidates.map((item) => ({ ...item, conflicted: true }));
          this.entries.set(descriptor.id, [...marked, descriptor]);
          this.diagnosticLog.push(diagnostic(
            "duplicate-id",
            `Skill id '${descriptor.id}' is provided by multiple paths`,
            descriptor.sourcePath,
            { severity: "error", skillId: descriptor.id, relatedPaths: [...marked.map((item) => item.sourcePath), descriptor.sourcePath] },
          ));
        } else if (!candidates.some((item) => item.resolvedPath === descriptor.resolvedPath)) {
          this.entries.set(descriptor.id, [...candidates, descriptor]);
        }
      }
    }
    return { skills: this.list(), diagnostics: this.diagnostics() };
  }

  list(options: { enabledOnly?: boolean } = {}): SkillDescriptor[] {
    const skills = [...this.entries.values()].flat();
    return (options.enabledOnly ? skills.filter((skill) => skill.enabled) : skills)
      .sort((left, right) => left.id.localeCompare(right.id) || left.sourcePath.localeCompare(right.sourcePath));
  }

  diagnostics(): SkillDiagnostic[] {
    return this.diagnosticLog.map((item) => ({
      ...item,
      ...(item.relatedPaths === undefined ? {} : { relatedPaths: [...item.relatedPaths] }),
    }));
  }

  search(query: string, options: SkillSearchOptions = {}): SkillDescriptor[] {
    const needle = query.trim().toLocaleLowerCase();
    const candidates = options.enabledOnly === undefined
      ? this.list()
      : this.list({ enabledOnly: options.enabledOnly });
    if (needle.length === 0) return options.limit === undefined ? candidates : candidates.slice(0, options.limit);
    const ranked = candidates
      .map((skill) => {
        const id = skill.id.toLocaleLowerCase();
        const name = skill.name.toLocaleLowerCase();
        const description = skill.description.toLocaleLowerCase();
        const keywords = JSON.stringify(skill.metadata.keywords ?? skill.metadata.tags ?? "").toLocaleLowerCase();
        const score = id === needle ? 0 : id.includes(needle) ? 1 : name.includes(needle) ? 2 : description.includes(needle) ? 3 : keywords.includes(needle) ? 4 : 5;
        return { skill, score };
      })
      .filter((item) => item.score < 5)
      .sort((left, right) => left.score - right.score || left.skill.id.localeCompare(right.skill.id) || left.skill.sourcePath.localeCompare(right.skill.sourcePath))
      .map((item) => item.skill);
    return options.limit === undefined ? ranked : ranked.slice(0, Math.max(0, options.limit));
  }

  enable(id: string): SkillDescriptor {
    return this.setEnabled(id, true);
  }

  disable(id: string): SkillDescriptor {
    return this.setEnabled(id, false);
  }

  async load(id: string): Promise<LoadedSkill> {
    const descriptor = this.unique(id);
    if (!descriptor.enabled) throw new Error(`Skill is not enabled: ${id}`);
    if (descriptor.approvalStatus !== "approved") {
      throw new Error(`Skill requires explicit approval: ${id}`);
    }
    const stable = await readSkillFileStable(descriptor.sourcePath, descriptor.rootPath);
    if (!samePath(stable.resolvedPath, descriptor.resolvedPath) || stable.sha256 !== descriptor.sha256) {
      throw new Error(`Skill changed since discovery: ${id}`);
    }
    const text = stable.text;
    const parsed = parseSkillDocument(text, descriptor.sourcePath);
    return { ...descriptor, body: parsed.body };
  }

  private unique(id: string): SkillDescriptor {
    const candidates = this.entries.get(id) ?? [];
    if (candidates.length === 0) {
      throw new Error(`Skill not found: ${id}`);
    }
    if (candidates.length > 1) {
      throw new Error(`Skill id is ambiguous: ${id}`);
    }
    return candidates[0]!;
  }

  private setEnabled(id: string, enabled: boolean): SkillDescriptor {
    const current = this.unique(id);
    if (enabled && current.trust === "blocked") throw new Error(`Skill is blocked by trust policy: ${id}`);
    if (enabled && current.approvalStatus !== "approved") {
      throw new Error(`Skill requires explicit approval: ${id}`);
    }
    const updated = Object.freeze({ ...current, enabled });
    this.entries.set(id, [updated]);
    return updated;
  }
}

export { parseSkillDocument };
