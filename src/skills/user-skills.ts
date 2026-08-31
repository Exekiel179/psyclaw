import { cp, lstat, mkdir, readFile, readdir, realpath, rm } from "node:fs/promises";
import { homedir } from "node:os";
import { basename, delimiter, isAbsolute, join, relative, resolve, sep } from "node:path";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import { parse as parseYaml } from "yaml";
import { atomicWriteFile } from "../project/jsonl.js";

/**
 * User-installed (non-catalog) skills live in a broader set of host agent
 * directories than the original hardcoded list.  These roots are used both by
 * the Pi `resources_discover` handler (which skill directories get loaded) and
 * by the `/skill` management page (which skill rows are shown and can be
 * toggled on/off individually).
 */

export interface LocalSkillInfo {
  /** Stable key for the management page, derived from the SKILL.md name. */
  id: string;
  name: string;
  description: string;
  /** Directory that directly contains SKILL.md. */
  path: string;
  /** The discovery root this skill was found under. */
  root: string;
  scope: "user" | "project";
  duplicatePaths: string[];
}

export interface UserSkillState {
  schemaVersion: "psyclaw/user-skill-state/v1";
  /** Skill ids the user explicitly turned off. Absent list means "all enabled". */
  disabled: string[];
}

const USER_SKILL_STATE = "psyclaw/user-skill-state/v1" as const;
const INSTALL_MANIFEST = "psyclaw-install.json";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function expandConfiguredPath(value: string, cwd: string, home: string): string {
  const expanded = value === "~"
    ? home
    : value.startsWith("~/") || value.startsWith("~\\")
      ? join(home, value.slice(2))
      : value;
  return isAbsolute(expanded) ? resolve(expanded) : resolve(cwd, expanded);
}

export function localSkillRoots(cwd: string): string[] {
  const home = homedir();
  const envPaths = (process.env.PSYCLAW_SKILLS_PATH ?? "")
    .split(delimiter)
    .map((path) => path.trim())
    .filter(Boolean)
    .map((path) => expandConfiguredPath(path, cwd, home));
  return [
    // Fixed precedence: explicit project roots, other project roots, then
    // user-level PsyClaw/Pi and other host agents.
    join(cwd, ".psyclaw", "skills"),
    join(cwd, "skills"),
    join(cwd, ".claude", "skills"),
    join(cwd, ".claude", "commands"),
    join(cwd, ".codex", "skills"),
    join(cwd, ".agents", "skills"),
    join(cwd, ".opencode", "skills"),
    join(cwd, ".cc-switch", "skills"),
    join(home, ".psyclaw", "skills"),
    join(home, ".claude", "skills"),
    join(home, ".claude", "commands"),
    join(home, ".codex", "skills"),
    join(home, ".agents", "skills"),
    join(home, ".opencode", "skills"),
    join(home, ".cc-switch", "skills"),
    ...envPaths,
  ];
}

/**
 * Roots whose contents are fully governed by the recommended Skill manager
 * (`.psyclaw/imports/recommended` and `getAgentDir()/skills`).  These are
 * excluded from the local *load* path so a disabled recommended Skill is not
 * silently re-enabled by the user-skill scan; the management page still shows
 * them through their recommended rows.
 */
export function managedSkillRoots(cwd: string): string[] {
  return [
    join(getAgentDir(), "skills"),
    join(cwd, ".psyclaw", "imports", "recommended"),
  ];
}

function parseSkillFrontmatter(text: string): { name?: string; description?: string } | null {
  const normalized = text.replace(/^\uFEFF/, "");
  const match = normalized.match(/^---[ \t]*\r?\n([\s\S]*?)\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|$)/);
  if (!match?.[1]) return null;
  try {
    const metadata = parseYaml(match[1]) as unknown;
    if (!isRecord(metadata)) return null;
    const name = typeof metadata.name === "string" ? metadata.name.trim() : undefined;
    const description = typeof metadata.description === "string" ? metadata.description.trim() : undefined;
    if (!name) return null;
    return { name, ...(description === undefined ? {} : { description }) };
  } catch {
    return null;
  }
}

async function readLocalSkill(dir: string, root: string, scope: "user" | "project"): Promise<LocalSkillInfo | null> {
  try {
    const text = await readFile(join(dir, "SKILL.md"), "utf8");
    const meta = parseSkillFrontmatter(text);
    if (!meta) return null;
    return {
      id: meta.name!,
      name: meta.name!,
      description: meta.description ?? "",
      path: dir,
      root,
      scope,
      duplicatePaths: [],
    };
  } catch {
    return null;
  }
}

/**
 * A skill directory that carries a `psyclaw-install.json` manifest is a
 * managed recommended install and must not be double-listed as a local skill.
 */
async function hasInstallManifest(directory: string): Promise<boolean> {
  try {
    await readFile(join(directory, INSTALL_MANIFEST), "utf8");
    return true;
  } catch {
    return false;
  }
}

/**
 * Collect every directory under `root` that directly contains SKILL.md,
 * mirroring Pi's loader semantics (a directory with SKILL.md is a skill and
 * its children are not scanned separately).  Hidden dirs and dependency
 * folders are skipped.  When `skipManaged` is set, skill directories that are
 * managed recommended installs (carrying a manifest) are excluded.
 */
async function collectSkillDirs(
  directory: string,
  root: string,
  scope: "user" | "project",
  depth: number,
  out: LocalSkillInfo[],
  skipManaged = false,
): Promise<void> {
  if (depth > 5) return;
  let entries;
  try {
    entries = await readdir(directory, { withFileTypes: true });
  } catch {
    return;
  }
  if (entries.some((entry) => entry.isFile() && entry.name === "SKILL.md")) {
    if (skipManaged && (await hasInstallManifest(directory))) return;
    const info = await readLocalSkill(directory, root, scope);
    if (info) out.push(info);
    return;
  }
  for (const entry of entries) {
    if (entry.name.startsWith(".") || entry.name === "node_modules") continue;
    if (!entry.isDirectory() || entry.isSymbolicLink()) continue;
    await collectSkillDirs(join(directory, entry.name), root, scope, depth + 1, out, skipManaged);
  }
}

/** Scan all discovery roots for user-installed skills (used by the manager). */
export async function scanLocalSkills(cwd: string, options: { includeManaged?: boolean } = {}): Promise<LocalSkillInfo[]> {
  const roots = options.includeManaged === false
    ? localSkillRoots(cwd)
    : [...localSkillRoots(cwd), ...managedSkillRoots(cwd)];
  const out: LocalSkillInfo[] = [];
  for (const root of roots) {
    const scope: "user" | "project" = root.includes(cwd) && !root.startsWith(homedir()) ? "project" : "user";
    // Managed roots carry manifests; skip them so a managed recommended
    // install is not double-listed as a local skill.
    const skipManaged = options.includeManaged !== false && managedSkillRoots(cwd).includes(root);
    await collectSkillDirs(root, root, scope, 0, out, skipManaged);
  }
  const selected = new Map<string, LocalSkillInfo>();
  for (const skill of out) {
    const key = skill.name.trim().toLocaleLowerCase();
    const existing = selected.get(key);
    if (existing) {
      if (existing.path !== skill.path && !existing.duplicatePaths.includes(skill.path)) {
        existing.duplicatePaths.push(skill.path);
      }
      continue;
    }
    selected.set(key, skill);
  }
  return [...selected.values()];
}

/** Read only descriptors from already-selected roots, including collections. */
export async function skillNamesInPaths(paths: readonly string[]): Promise<string[]> {
  const names = new Set<string>();
  for (const root of paths) {
    const skills: LocalSkillInfo[] = [];
    await collectSkillDirs(root, root, "project", 0, skills);
    for (const skill of skills) names.add(skill.name.trim().toLocaleLowerCase());
  }
  return [...names];
}

/** Claude command markdown is a prompt resource, not a Skill directory. */
export async function enabledLocalPromptPaths(cwd: string): Promise<string[]> {
  const roots = [join(cwd, ".claude", "commands"), join(homedir(), ".claude", "commands")];
  const selected = new Set<string>();
  const paths: string[] = [];
  for (const root of roots) {
    let entries;
    try {
      entries = await readdir(root, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries.sort((left, right) => left.name.localeCompare(right.name))) {
      if (!entry.isFile() || !entry.name.toLocaleLowerCase().endsWith(".md")) continue;
      const key = entry.name.slice(0, -3).toLocaleLowerCase();
      if (selected.has(key)) continue;
      selected.add(key);
      paths.push(resolve(root, entry.name));
    }
  }
  return paths;
}

function userSkillStatePath(root: string): string {
  return join(root, ".psyclaw", "user-skills.json");
}

export async function readUserSkillState(root: string): Promise<UserSkillState> {
  try {
    const value = JSON.parse(await readFile(userSkillStatePath(root), "utf8")) as unknown;
    if (!isRecord(value) || value.schemaVersion !== USER_SKILL_STATE) throw new Error("invalid state");
    const disabled = Array.isArray(value.disabled)
      ? value.disabled.filter((id): id is string => typeof id === "string")
      : [];
    return { schemaVersion: USER_SKILL_STATE, disabled: [...new Set(disabled)].sort() };
  } catch {
    return { schemaVersion: USER_SKILL_STATE, disabled: [] };
  }
}

async function saveUserSkillState(root: string, state: UserSkillState): Promise<void> {
  await atomicWriteFile(userSkillStatePath(root), `${JSON.stringify({
    schemaVersion: USER_SKILL_STATE,
    disabled: [...new Set(state.disabled)].sort(),
  }, null, 2)}\n`);
}

export async function setLocalSkillEnabled(root: string, id: string, enabled: boolean): Promise<void> {
  const state = await readUserSkillState(root);
  const current = new Set(state.disabled);
  if (enabled) current.delete(id); else current.add(id);
  await saveUserSkillState(root, { schemaVersion: USER_SKILL_STATE, disabled: [...current] });
}

export async function setLocalSkillsEnabled(root: string, ids: readonly string[], enabled: boolean): Promise<void> {
  const state = await readUserSkillState(root);
  const current = new Set(state.disabled);
  for (const id of ids) {
    if (enabled) current.delete(id); else current.add(id);
  }
  await saveUserSkillState(root, { schemaVersion: USER_SKILL_STATE, disabled: [...current] });
}

export interface EnabledLocalSkillPaths {
  paths: string[];
  warnings: string[];
}

/**
 * Return existing, absolute Skill directories for Pi. Same-name skills are
 * selected once by the root order above; loose markdown commands are not
 * treated as Skills.
 */
export async function enabledLocalSkillPaths(
  cwd: string,
  options: { excludedNames?: Iterable<string> } = {},
): Promise<EnabledLocalSkillPaths> {
  const state = await readUserSkillState(cwd);
  const disabled = new Set(state.disabled);
  const selectedNames = new Set(
    [...(options.excludedNames ?? [])].map((name) => name.trim().toLocaleLowerCase()),
  );
  const paths: string[] = [];
  const warnings: string[] = [];
  const seen = new Set<string>();
  for (const root of localSkillRoots(cwd)) {
    const exists = await lstat(root).then((stat) => stat.isDirectory()).catch(() => false);
    if (!exists) continue;
    const skills: LocalSkillInfo[] = [];
    const scope: "user" | "project" = root.includes(cwd) && !root.startsWith(homedir()) ? "project" : "user";
    await collectSkillDirs(root, root, scope, 0, skills);
    if (skills.length === 0) continue;
    for (const skill of skills) {
      const nameKey = skill.name.trim().toLocaleLowerCase();
      if (selectedNames.has(nameKey)) continue;
      if (disabled.has(skill.id)) {
        warnings.push(`User Skill '${skill.id}' is disabled and was not loaded.`);
        continue;
      }
      const key = process.platform === "win32" ? skill.path.toLocaleLowerCase() : skill.path;
      if (!seen.has(key)) {
        seen.add(key);
        selectedNames.add(nameKey);
        paths.push(skill.path);
      }
    }
  }
  return { paths, warnings };
}

export function userSkillId(name: string): string {
  return `local:${name}`;
}

async function assertNoSymlinks(directory: string): Promise<void> {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    if (entry.name === ".git" || entry.name === "node_modules") continue;
    const path = join(directory, entry.name);
    if (entry.isSymbolicLink()) throw new Error(`Local Skill contains a symbolic link: ${path}`);
    if (entry.isDirectory()) await assertNoSymlinks(path);
  }
}

/** Copy one local Skill directory into PsyClaw's user-level Skill directory. */
export async function installLocalSkill(
  source: string,
  cwd: string,
  options: { targetRoot?: string } = {},
): Promise<{ name: string; source: string; target: string }> {
  const requested = resolve(cwd, source);
  const sourcePath = await realpath(requested);
  const stat = await lstat(sourcePath);
  if (!stat.isDirectory() || stat.isSymbolicLink()) throw new Error("Local Skill source must be a real directory");
  const skill = await readLocalSkill(sourcePath, sourcePath, "user");
  if (!skill) throw new Error("Local Skill directory must contain a valid SKILL.md with name frontmatter");
  if (!/^[a-z0-9][a-z0-9-]{0,127}$/.test(skill.name)) throw new Error(`Invalid local Skill name: ${skill.name}`);
  await assertNoSymlinks(sourcePath);
  const targetRoot = options.targetRoot ?? join(homedir(), ".psyclaw", "skills");
  const target = join(targetRoot, skill.name);
  const rel = relative(targetRoot, target);
  if (!rel || rel.startsWith(`..${sep}`) || isAbsolute(rel)) throw new Error("Local Skill target escapes the user Skill directory");
  const exists = await lstat(target).then(() => true).catch(() => false);
  if (exists) throw new Error(`Skill '${skill.name}' is already installed at ${target}`);
  await mkdir(targetRoot, { recursive: true });
  try {
    await cp(sourcePath, target, {
      recursive: true,
      errorOnExist: true,
      filter: (path) => basename(path) !== ".git" && basename(path) !== "node_modules",
    });
  } catch (error) {
    await rm(target, { recursive: true, force: true }).catch(() => undefined);
    throw error;
  }
  return { name: skill.name, source: sourcePath, target };
}
