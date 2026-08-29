import { createHash, randomUUID } from "node:crypto";
import { execFile } from "node:child_process";
import {
  copyFile,
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  realpath,
  rename,
  rm,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join, relative, resolve } from "node:path";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";
import { parse as parseYaml } from "yaml";
import { atomicWriteFile } from "../project/jsonl.js";

const execFileAsync = promisify(execFile);
const INSTALL_MANIFEST = "psyclaw-install.json";
const SHA256_RE = /^[a-f0-9]{40}$/i;
const CONTENT_SHA256_RE = /^[a-f0-9]{64}$/i;
const CORE_SKILLS = new Set(["research-intake", "evidence-capture", "citation-audit", "research-brief"]);

export const RECOMMENDED_SKILL_ALIASES: Readonly<Record<string, string>> = Object.freeze({
  "markitdown-pro": "markitdown-bilibili",
});

export interface RecommendationState {
  schemaVersion: "psyclaw/recommendation-state/v1";
  skills: string[];
  mcp: string[];
  skillSources?: Record<string, string>;
}

export interface RecommendedCatalogItem {
  id: string;
  name: string;
  kind: string;
  sourceRef?: string;
  [key: string]: unknown;
}

export interface RecommendedInstallPlan {
  id: string;
  sourceKind: string;
  sourceUrl?: string;
  ref: string | null;
  skillPath?: string;
  skillName?: string;
  license: string;
  dependencies: string[];
  status: string;
  blockedReason?: string;
  [key: string]: unknown;
}

export interface RecommendedCatalog {
  schemaVersion: "psyclaw/recommended-skills/v1";
  documentVersion: string;
  items: RecommendedCatalogItem[];
  installPrep: RecommendedInstallPlan[];
}

export interface RecommendedInstallManifest {
  schemaVersion: "psyclaw/recommended-skill-install/v1";
  id: string;
  skillName: string;
  source: { kind: "git"; url: string; ref: string; path: string };
  license: { spdx: string; evidence: string; sha256: string };
  skillSha256: string;
  dependencies: string[];
  installedAt: string;
}

export interface RecommendedInstallResult {
  id: string;
  skillName: string;
  path: string;
  manifestPath: string;
  installed: boolean;
}

export interface EnabledSkillPaths {
  paths: string[];
  warnings: string[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hash(bytes: Buffer | string): string {
  return createHash("sha256").update(bytes).digest("hex");
}

function normalizedId(id: string): string {
  const value = id.trim();
  return RECOMMENDED_SKILL_ALIASES[value] ?? value;
}

export function normalizeRecommendedSkillId(id: string): string {
  return normalizedId(id);
}

function recommendationStatePath(root: string): string {
  return join(resolve(root), ".psyclaw", "recommendations.json");
}

export async function readRecommendationState(root: string): Promise<RecommendationState> {
  try {
    const value = JSON.parse(await readFile(recommendationStatePath(root), "utf8")) as unknown;
    if (!isRecord(value)) throw new Error("invalid state");
    const skills = Array.isArray(value.skills)
      ? value.skills.filter((id): id is string => typeof id === "string").map(normalizedId)
      : [];
    const mcp = Array.isArray(value.mcp) ? value.mcp.filter((id): id is string => typeof id === "string") : [];
    const skillSources = isRecord(value.skillSources)
      ? Object.fromEntries(Object.entries(value.skillSources).filter((entry): entry is [string, string] => typeof entry[1] === "string"))
      : undefined;
    return {
      schemaVersion: "psyclaw/recommendation-state/v1",
      skills: [...new Set(skills)].sort(),
      mcp: [...new Set(mcp)].sort(),
      ...(skillSources === undefined ? {} : { skillSources }),
    };
  } catch {
    return { schemaVersion: "psyclaw/recommendation-state/v1", skills: [], mcp: [] };
  }
}

export async function saveRecommendationState(root: string, state: RecommendationState): Promise<void> {
  const path = recommendationStatePath(root);
  await mkdir(dirname(path), { recursive: true });
  await atomicWriteFile(path, `${JSON.stringify({
    schemaVersion: "psyclaw/recommendation-state/v1",
    skills: [...new Set(state.skills.map(normalizedId))].sort(),
    mcp: [...new Set(state.mcp)].sort(),
    ...(state.skillSources === undefined ? {} : { skillSources: state.skillSources }),
  }, null, 2)}\n`);
}

function catalogCandidates(): string[] {
  const moduleDir = dirname(fileURLToPath(import.meta.url));
  return [
    join(moduleDir, "..", "..", "..", "skills", "recommended", "catalog.json"),
    join(moduleDir, "..", "..", "skills", "recommended", "catalog.json"),
    join(process.cwd(), "skills", "recommended", "catalog.json"),
  ];
}

export async function readRecommendedCatalog(): Promise<RecommendedCatalog> {
  for (const path of catalogCandidates()) {
    try {
      const value = JSON.parse(await readFile(path, "utf8")) as unknown;
      if (!isRecord(value) || value.schemaVersion !== "psyclaw/recommended-skills/v1" ||
          !Array.isArray(value.items) || !Array.isArray(value.installPrep)) continue;
      return value as unknown as RecommendedCatalog;
    } catch { /* try the next package/source layout */ }
  }
  throw new Error("Recommended Skill catalog is unavailable");
}

function parseSkillName(text: string): string {
  const match = text.replace(/^\uFEFF/, "").match(/^---[ \t]*\r?\n([\s\S]*?)\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|$)/);
  if (!match?.[1]) throw new Error("SKILL.md must start with YAML frontmatter");
  const metadata = parseYaml(match[1]) as unknown;
  if (!isRecord(metadata) || typeof metadata.name !== "string" || !metadata.name.trim()) {
    throw new Error("SKILL.md frontmatter requires a name");
  }
  return metadata.name.trim();
}

function assertContained(root: string, target: string): void {
  const rel = relative(root, target).replaceAll("\\", "/");
  if (rel === ".." || rel.startsWith("../") || rel.startsWith("/")) throw new Error("Skill path escapes its source root");
}

function safeSegment(value: string): boolean {
  return value.length > 0 && value.length <= 128 && !value.includes("/") && !value.includes("\\") &&
    value !== "." && value !== ".." && /^[A-Za-z0-9._-]+$/.test(value);
}

function isSensitiveName(name: string): boolean {
  const lower = name.toLowerCase();
  return lower === ".git" || lower === ".env" || lower.startsWith(".env.") ||
    /(?:credential|secret|token|cookie|password|private[-_]?key)/i.test(lower) ||
    lower.endsWith(".pem") || lower.endsWith(".key");
}

async function copySkillTree(source: string, target: string): Promise<void> {
  await mkdir(target, { recursive: false });
  for (const entry of await readdir(source, { withFileTypes: true })) {
    if (isSensitiveName(entry.name)) continue;
    const from = join(source, entry.name);
    const to = join(target, entry.name);
    if (entry.isSymbolicLink()) throw new Error(`Symlink is not allowed in recommended Skill: ${entry.name}`);
    if (entry.isDirectory()) await copySkillTree(from, to);
    else if (entry.isFile()) {
      const stat = await lstat(from);
      if (stat.size > 16 * 1024 * 1024) throw new Error(`Skill file exceeds 16 MiB: ${entry.name}`);
      await copyFile(from, to);
    }
  }
}

async function findLicense(repoRoot: string): Promise<string> {
  const entry = (await readdir(repoRoot, { withFileTypes: true }))
    .find((candidate) => candidate.isFile() && /^(license|copying)(?:\.|$)/i.test(candidate.name));
  if (!entry) throw new Error("Repository license file is missing");
  return join(repoRoot, entry.name);
}

async function runGit(args: string[]): Promise<void> {
  await execFileAsync("git", args, { maxBuffer: 4 * 1024 * 1024 });
}

function installPlan(catalog: RecommendedCatalog, requestedId: string): { item: RecommendedCatalogItem; plan: RecommendedInstallPlan } {
  const id = normalizedId(requestedId);
  const item = catalog.items.find((candidate) => normalizedId(candidate.id) === id);
  const plan = catalog.installPrep.find((candidate) => normalizedId(candidate.id) === id);
  if (!item || !plan) throw new Error(`Recommended Skill not found: ${requestedId}`);
  if (item.kind !== "skill") throw new Error(`Recommended item is not an installable Skill: ${requestedId}`);
  if (plan.sourceKind !== "github" || typeof plan.sourceUrl !== "string" || !plan.sourceUrl.startsWith("https://github.com/")) {
    throw new Error(`Recommended Skill has no approved GitHub source: ${id}`);
  }
  if (typeof plan.ref !== "string" || !SHA256_RE.test(plan.ref)) throw new Error(`Recommended Skill source is not pinned: ${id}`);
  if (typeof plan.skillPath !== "string" || typeof plan.skillName !== "string" || !safeSegment(plan.skillName)) {
    throw new Error(`Recommended Skill entrypoint is not declared: ${id}`);
  }
  if (!plan.license || ["unknown", "NOASSERTION"].includes(plan.license)) throw new Error(`Recommended Skill license is not approved: ${id}`);
  return { item, plan };
}

function importsRoot(root: string): string {
  return join(resolve(root), ".psyclaw", "imports", "recommended");
}

async function readInstallManifest(path: string): Promise<RecommendedInstallManifest> {
  const value = JSON.parse(await readFile(path, "utf8")) as unknown;
  if (!isRecord(value) || value.schemaVersion !== "psyclaw/recommended-skill-install/v1" ||
      typeof value.id !== "string" || typeof value.skillName !== "string" ||
      !isRecord(value.source) || typeof value.source.url !== "string" || typeof value.source.ref !== "string" || typeof value.source.path !== "string" ||
      !isRecord(value.license) || typeof value.license.spdx !== "string" || typeof value.license.evidence !== "string" || typeof value.license.sha256 !== "string" ||
      typeof value.skillSha256 !== "string" || !Array.isArray(value.dependencies) || typeof value.installedAt !== "string") {
    throw new Error("Recommended Skill install manifest is invalid");
  }
  return value as unknown as RecommendedInstallManifest;
}

export async function validateInstalledRecommendedSkill(root: string, requestedId: string): Promise<{ id: string; skillName: string; path: string }> {
  const catalog = await readRecommendedCatalog();
  const { plan } = installPlan(catalog, requestedId);
  const id = normalizedId(requestedId);
  const target = join(importsRoot(root), plan.skillName!);
  const stat = await lstat(target).catch(() => undefined);
  if (!stat?.isDirectory() || stat.isSymbolicLink()) throw new Error(`Recommended Skill is not installed: ${id}; run /install skill ${id}`);
  const manifest = await readInstallManifest(join(target, INSTALL_MANIFEST));
  if (manifest.id !== id || manifest.skillName !== plan.skillName || manifest.source.ref !== plan.ref || manifest.source.url !== plan.sourceUrl) {
    throw new Error(`Recommended Skill install manifest does not match the catalog: ${id}`);
  }
  const skillPath = join(target, "SKILL.md");
  const skillBytes = await readFile(skillPath);
  const skillName = parseSkillName(skillBytes.toString("utf8"));
  if (skillName !== plan.skillName || manifest.skillSha256 !== hash(skillBytes)) throw new Error(`Recommended Skill content changed after installation: ${id}`);
  if (!CONTENT_SHA256_RE.test(manifest.license.sha256) || manifest.license.spdx !== plan.license) throw new Error(`Recommended Skill license record is invalid: ${id}`);
  const licenseBytes = await readFile(join(target, manifest.license.evidence));
  if (hash(licenseBytes) !== manifest.license.sha256) throw new Error(`Recommended Skill license evidence changed: ${id}`);
  try {
    await lstat(join(target, ".git"));
    throw new Error(`Recommended Skill contains nested Git metadata: ${id}`);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
  return { id, skillName, path: target };
}

export async function installRecommendedSkill(root: string, requestedId: string, now = () => new Date().toISOString()): Promise<RecommendedInstallResult> {
  const catalog = await readRecommendedCatalog();
  const { plan } = installPlan(catalog, requestedId);
  const id = normalizedId(requestedId);
  const destinationRoot = importsRoot(root);
  const target = join(destinationRoot, plan.skillName!);
  await mkdir(destinationRoot, { recursive: true });
  try {
    const installed = await validateInstalledRecommendedSkill(root, id);
    return { ...installed, manifestPath: join(installed.path, INSTALL_MANIFEST), installed: false };
  } catch (error) {
    const stat = await lstat(target).catch(() => undefined);
    if (stat !== undefined) throw new Error(`Recommended Skill target already exists but is not a valid managed install: ${target}; remove or rename it before retrying`, { cause: error });
  }

  const temporary = await mkdtemp(join(tmpdir(), "psyclaw-skill-install-"));
  const repo = join(temporary, "repo");
  const staging = join(destinationRoot, `.staging-${plan.skillName}-${randomUUID()}`);
  try {
    await runGit(["clone", "--quiet", "--filter=blob:none", "--no-checkout", plan.sourceUrl!, repo]);
    await runGit(["-C", repo, "checkout", "--quiet", plan.ref!]);
    const source = resolve(repo, plan.skillPath!);
    assertContained(repo, source);
    const sourceReal = await realpath(source);
    assertContained(await realpath(repo), sourceReal);
    const skillBytes = await readFile(join(sourceReal, "SKILL.md"));
    const skillName = parseSkillName(skillBytes.toString("utf8"));
    if (skillName !== plan.skillName) throw new Error(`Catalog Skill name '${plan.skillName}' does not match '${skillName}'`);
    await copySkillTree(sourceReal, staging);
    const licenseSource = await findLicense(repo);
    const licenseName = basename(licenseSource);
    if (resolve(licenseSource) !== resolve(join(sourceReal, licenseName))) await copyFile(licenseSource, join(staging, licenseName));
    const licenseBytes = await readFile(join(staging, licenseName));
    const manifest: RecommendedInstallManifest = {
      schemaVersion: "psyclaw/recommended-skill-install/v1",
      id,
      skillName,
      source: { kind: "git", url: plan.sourceUrl!, ref: plan.ref!, path: plan.skillPath! },
      license: { spdx: plan.license, evidence: licenseName, sha256: hash(licenseBytes) },
      skillSha256: hash(skillBytes),
      dependencies: Array.isArray(plan.dependencies) ? plan.dependencies.filter((value): value is string => typeof value === "string") : [],
      installedAt: now(),
    };
    await atomicWriteFile(join(staging, INSTALL_MANIFEST), `${JSON.stringify(manifest, null, 2)}\n`);
    await rename(staging, target);
    return { id, skillName, path: target, manifestPath: join(target, INSTALL_MANIFEST), installed: true };
  } finally {
    await rm(staging, { recursive: true, force: true }).catch(() => undefined);
    await rm(temporary, { recursive: true, force: true }).catch(() => undefined);
  }
}

export async function enabledRecommendedSkillPaths(root: string): Promise<EnabledSkillPaths> {
  const state = await readRecommendationState(root);
  const paths: string[] = [];
  const warnings: string[] = [];
  const seenNames = new Set<string>();
  for (const requestedId of state.skills) {
    try {
      const installed = await validateInstalledRecommendedSkill(root, requestedId);
      if (CORE_SKILLS.has(installed.skillName) && state.skillSources?.[installed.skillName] !== `recommended:${installed.id}`) {
        warnings.push(`Skill '${installed.skillName}' conflicts with a PsyClaw core Skill; core remains active. Rename it or explicitly select recommended:${installed.id}.`);
        continue;
      }
      if (seenNames.has(installed.skillName)) {
        warnings.push(`Skill '${installed.skillName}' has multiple enabled sources; only the first verified source is loaded.`);
        continue;
      }
      seenNames.add(installed.skillName);
      paths.push(installed.path);
    } catch (error) {
      warnings.push(error instanceof Error ? error.message : String(error));
    }
  }
  return { paths, warnings };
}

export function coreSkillNames(): string[] {
  return [...CORE_SKILLS].sort();
}
