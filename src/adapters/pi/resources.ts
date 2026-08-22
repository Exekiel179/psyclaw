import { readFile } from "node:fs/promises";
import {
  DefaultResourceLoader,
  getAgentDir,
  type ResourceDiagnostic,
  type ResourceLoader,
  type Skill,
} from "@earendil-works/pi-coding-agent";

export interface PiResourceOptions {
  cwd: string;
  agentDir?: string;
  additionalSkillPaths?: string[];
  additionalExtensionPaths?: string[];
  noExtensions?: boolean;
  noSkills?: boolean;
  noContextFiles?: boolean;
}

export interface PiResourceSnapshot {
  skills: ReadonlyArray<Pick<Skill, "name" | "description" | "filePath" | "baseDir"> & { source: string }>;
  diagnostics: readonly ResourceDiagnostic[];
  extensions: number;
  contextFiles: readonly string[];
}

function assertAbsolute(pathValue: string, label: string): void {
  if (!/^([A-Za-z]:[\\/]|[\\/]{1,2})/.test(pathValue)) {
    throw new Error(`${label} must be an absolute path`);
  }
}

/** Create Pi's resource loader with explicit roots and no ambient cwd. */
export async function createPiResourceLoader(options: PiResourceOptions): Promise<DefaultResourceLoader> {
  assertAbsolute(options.cwd, "cwd");
  const agentDir = options.agentDir ?? getAgentDir();
  assertAbsolute(agentDir, "agentDir");
  for (const pathValue of options.additionalSkillPaths ?? []) assertAbsolute(pathValue, "additional skill path");
  for (const pathValue of options.additionalExtensionPaths ?? []) assertAbsolute(pathValue, "additional extension path");
  const loader = new DefaultResourceLoader({
    cwd: options.cwd,
    agentDir,
    ...(options.additionalSkillPaths === undefined ? {} : { additionalSkillPaths: [...options.additionalSkillPaths] }),
    ...(options.additionalExtensionPaths === undefined ? {} : { additionalExtensionPaths: [...options.additionalExtensionPaths] }),
    // Ambient project/user resources are executable or can carry sensitive
    // context. Loading them is an explicit opt-in at this adapter boundary.
    noExtensions: options.noExtensions ?? (options.additionalExtensionPaths === undefined),
    noSkills: options.noSkills ?? (options.additionalSkillPaths === undefined),
    noContextFiles: options.noContextFiles ?? true,
  });
  await loader.reload();
  return loader;
}

export function snapshotPiResources(loader: ResourceLoader): PiResourceSnapshot {
  const skillState = loader.getSkills();
  const extensionState = loader.getExtensions();
  return Object.freeze({
    skills: Object.freeze(skillState.skills.map((skill) => Object.freeze({
      name: skill.name,
      description: skill.description,
      filePath: skill.filePath,
      baseDir: skill.baseDir,
      source: skill.sourceInfo.source,
    }))),
    diagnostics: Object.freeze([...skillState.diagnostics]),
    extensions: extensionState.extensions.length,
    contextFiles: Object.freeze(loader.getAgentsFiles().agentsFiles.map((file) => file.path)),
  });
}

/** Progressive disclosure: read one skill body only after explicit selection. */
export async function loadPiSkillBody(loader: ResourceLoader, name: string): Promise<string> {
  const skill = loader.getSkills().skills.find((candidate) => candidate.name === name);
  if (!skill) throw new Error(`Skill not found: ${name}`);
  return readFile(skill.filePath, "utf8");
}
