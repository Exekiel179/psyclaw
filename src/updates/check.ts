import { KNOWN_AGENTS } from "../agents/catalog.js";
import { checkSkillDrift, type SkillDrift } from "./skills.js";
import { isUnpinnedRef, versionStatus, type UpdateStatus } from "./status.js";
import { npmPackageName, pipxPackageName, type RegistryClient } from "./registry.js";
import { PI_CODING_AGENT, resolvePsyClawManifest } from "./manifest.js";

export interface SelfUpdate {
  current: string;
  latest?: string;
  status: UpdateStatus;
}

/** The bundled Pi runtime: psyclaw's pinned dependency vs the official latest. */
export interface PiRuntimeUpdate {
  packageName: string;
  current?: string;
  latest?: string;
  note?: string;
  status: UpdateStatus;
}

export interface AgentUpdate {
  id: string;
  name: string;
  method: string;
  ref: string;
  latest?: string;
  status: UpdateStatus;
}

export interface UpdateReport {
  schemaVersion: "psyclaw/update-report/v1";
  checkedAt: string;
  self: SelfUpdate;
  runtime: PiRuntimeUpdate;
  agents: AgentUpdate[];
  skills: SkillDrift[];
}

export interface CheckUpdatesOptions {
  registry: RegistryClient;
  cwd: string;
  now?: () => string;
}

/**
 * Build an update report: psyclaw itself, its bundled Pi runtime, each
 * installable agent, and imported skill drift. All registry lookups fail
 * closed to `undefined`; nothing here installs or modifies state.
 */
export async function checkUpdates(options: CheckUpdatesOptions): Promise<UpdateReport> {
  const manifest = await resolvePsyClawManifest();
  const current = manifest?.version ?? "unknown";
  const selfLatest = await options.registry.latestNpm("psyclaw");
  const self: SelfUpdate = {
    current,
    ...(selfLatest === undefined ? {} : { latest: selfLatest }),
    status: selfLatest === undefined ? "not-published" : versionStatus(current, selfLatest),
  };

  const piRelease = await options.registry.latestPiRelease();
  const piVersion = manifest?.piVersion;
  const piNote = piRelease?.note;
  const runtime: PiRuntimeUpdate = {
    packageName: PI_CODING_AGENT,
    ...(piVersion === undefined ? {} : { current: piVersion }),
    ...(piRelease === undefined ? {} : { latest: piRelease.version }),
    ...(piNote === undefined ? {} : { note: piNote }),
    status: piRelease === undefined ? "unavailable" : versionStatus(piVersion, piRelease.version),
  };

  const agents: AgentUpdate[] = [];
  for (const agent of KNOWN_AGENTS) {
    const install = agent.install;
    if (!install) continue;
    let latest: string | undefined;
    if (install.method === "npm") {
      const packageName = npmPackageName(install.installCommand);
      if (packageName !== undefined) latest = await options.registry.latestNpm(packageName);
    } else if (install.method === "pipx") {
      const packageName = pipxPackageName(install.installCommand);
      if (packageName !== undefined) latest = await options.registry.latestPypi(packageName);
    }
    agents.push({
      id: agent.id,
      name: agent.name,
      method: install.method,
      ref: install.ref,
      ...(latest === undefined ? {} : { latest }),
      status: isUnpinnedRef(install.ref) ? "unpinned" : versionStatus(install.ref, latest),
    });
  }

  const skills: SkillDrift[] = [];
  for (const agent of KNOWN_AGENTS) {
    skills.push(await checkSkillDrift(options.cwd, agent.id));
  }

  return {
    schemaVersion: "psyclaw/update-report/v1",
    checkedAt: (options.now ?? (() => new Date().toISOString()))(),
    self,
    runtime,
    agents,
    skills,
  };
}
