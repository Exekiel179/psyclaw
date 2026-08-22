import { lstat, readdir } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";
import { KNOWN_AGENTS, type AgentInstallSpec, type KnownAgent } from "./catalog.js";

export interface DiscoveredSkill {
  name: string;
  path: string;
  kind: "dir" | "file";
}

export interface AgentScan {
  id: string;
  name: string;
  found: boolean;
  /** Absolute path of the first matching config directory. */
  configPath?: string;
  skills: DiscoveredSkill[];
  skillDirs: string[];
  hasCredentials: boolean;
  credentialPaths: string[];
  install?: AgentInstallSpec;
}

function safeCatalogPath(home: string, relativePath: string): string | undefined {
  const normalized = relativePath.replaceAll("\\", "/");
  if (isAbsolute(relativePath) || normalized.split("/").some((segment) => segment === "..")) return undefined;
  const candidate = resolve(home, relativePath);
  const rel = relative(resolve(home), candidate).replaceAll("\\", "/");
  if (rel === ".." || rel.startsWith("../") || isAbsolute(rel)) return undefined;
  return candidate;
}

async function hasSymlinkAncestor(path: string, boundary: string): Promise<boolean> {
  let cursor = resolve(path);
  const root = resolve(boundary);
  while (true) {
    try {
      if ((await lstat(cursor)).isSymbolicLink()) return true;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return false;
      return true;
    }
    if (cursor === root) return false;
    const rel = relative(root, cursor).replaceAll("\\", "/");
    if (rel === ".." || rel.startsWith("../") || isAbsolute(rel)) return true;
    cursor = dirname(cursor);
  }
}

async function isDirectory(path: string, boundary: string): Promise<boolean> {
  try {
    const stat = await lstat(path);
    return stat.isDirectory() && !stat.isSymbolicLink() && !(await hasSymlinkAncestor(path, boundary));
  } catch {
    return false;
  }
}

async function exists(path: string, boundary: string): Promise<boolean> {
  try {
    const stat = await lstat(path);
    return !stat.isSymbolicLink() && !(await hasSymlinkAncestor(path, boundary));
  } catch {
    return false;
  }
}

async function listSkillEntries(dir: string, boundary: string): Promise<DiscoveredSkill[]> {
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch {
    return [];
  }
  const skills: DiscoveredSkill[] = [];
  for (const entry of entries) {
    if (entry.isSymbolicLink()) continue;
    const path = join(dir, entry.name);
    if (await hasSymlinkAncestor(path, boundary)) continue;
    if (entry.isDirectory()) {
      skills.push({ name: entry.name, path, kind: "dir" });
    } else if (entry.isFile() && entry.name.endsWith(".md")) {
      skills.push({ name: entry.name.replace(/\.md$/, ""), path, kind: "file" });
    }
  }
  return skills.sort((left, right) => left.name.localeCompare(right.name));
}

export interface DiscoverOptions {
  homeDir?: string;
  agents?: readonly KnownAgent[];
}

/**
 * Read-only scan of local agent configurations. This never reads credential
 * contents, never follows symlinks, and never executes an install command; it
 * only records what exists on disk for display and import planning.
 */
export async function discoverAgents(options: DiscoverOptions = {}): Promise<AgentScan[]> {
  const home = options.homeDir ?? homedir();
  if (isAbsolute(home) === false) throw new Error("homeDir must be absolute");
  const agents = options.agents ?? KNOWN_AGENTS;
  const scans: AgentScan[] = [];
  for (const agent of agents) {
    let configPath: string | undefined;
    for (const dir of agent.configDirs) {
      const absolute = safeCatalogPath(home, dir);
      if (absolute !== undefined && await isDirectory(absolute, home)) {
        configPath = absolute;
        break;
      }
    }
    const skillDirs: string[] = [];
    const skills: DiscoveredSkill[] = [];
    for (const dir of agent.skillDirs) {
      const absolute = safeCatalogPath(home, dir);
      if (absolute !== undefined && await isDirectory(absolute, home)) {
        skillDirs.push(absolute);
        skills.push(...await listSkillEntries(absolute, home));
      }
    }
    const credentialPaths: string[] = [];
    for (const file of agent.credentialFiles) {
      const absolute = safeCatalogPath(home, file);
      if (absolute !== undefined && await exists(absolute, home)) credentialPaths.push(absolute);
    }
    scans.push({
      id: agent.id,
      name: agent.name,
      found: configPath !== undefined,
      ...(configPath === undefined ? {} : { configPath }),
      skills,
      skillDirs,
      hasCredentials: credentialPaths.length > 0,
      credentialPaths,
      ...(agent.install === undefined ? {} : { install: agent.install }),
    });
  }
  return scans;
}
