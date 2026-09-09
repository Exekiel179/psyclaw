import { access, readFile, writeFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import { constants as fsConstants } from "node:fs";
import { join } from "node:path";
import type { Handoff, ResearchParadigm, ResearchProject } from "../core/contracts.js";
import { CONTRACT_VERSION } from "../core/contracts.js";
import { asHandoff, asProject } from "../core/schemas.js";
import { atomicWriteFile } from "./jsonl.js";
import { projectPaths, ensureProjectDirectories, assertSafeProjectPath } from "./paths.js";
import { scaffoldWorkspace } from "./workspace.js";
import { readProject } from "../research/ledger.js";

export interface BootstrapOptions {
  root: string;
  /** Optional; defaults to a placeholder so /init can be scaffold-only. */
  goal?: string;
  paradigm?: ResearchParadigm;
  projectId?: string;
  now?: string;
}

const CANONICAL_MARKERS = [
  "psyclaw.md",
  "data/raw",
  "data/clean",
  "analysis",
  "literature",
  "paper",
  ".psyclaw",
] as const;

async function pathExists(path: string): Promise<boolean> {
  try {
    await access(path, fsConstants.F_OK);
    return true;
  } catch {
    return false;
  }
}

/** True when the directory already looks like a prior /init (cross-session). */
export async function hasCanonicalWorkspace(root: string): Promise<boolean> {
  const paths = projectPaths(root);
  const checks = await Promise.all(
    CANONICAL_MARKERS.map(async (marker) => pathExists(marker === "psyclaw.md" ? paths.psyclawMd : join(paths.root, marker))),
  );
  return checks.every(Boolean);
}

/**
 * Return the bound project if `.psyclaw/project.json` exists, or recreate the
 * binding when the canonical layout is already present (skip re-/init nag).
 */
export async function ensureProjectBinding(options: BootstrapOptions): Promise<{
  project: ResearchProject;
  created: boolean;
  reusedCanonical: boolean;
}> {
  try {
    const project = await readProject(options.root);
    return { project, created: false, reusedCanonical: false };
  } catch {
    // fall through
  }

  if (!(await hasCanonicalWorkspace(options.root))) {
    throw new Error("Workspace is not initialized");
  }

  const paths = projectPaths(options.root);
  const now = options.now ?? new Date().toISOString();
  let goal = options.goal?.trim() || "";
  if (!goal) {
    try {
      const md = await readFile(paths.psyclawMd, "utf8");
      const heading = md.match(/^#\s+(.+)$/m);
      goal = heading?.[1]?.trim() || "未命名研究项目";
    } catch {
      goal = "未命名研究项目";
    }
  }
  const project: ResearchProject = {
    id: options.projectId ?? `project_${randomUUID().replaceAll("-", "")}`,
    root: paths.root,
    paradigm: options.paradigm ?? "survey-observational",
    goal,
    policyVersion: CONTRACT_VERSION,
    createdAt: now,
  };
  asProject(project);
  const projectFile = await assertSafeProjectPath(paths.root, ".psyclaw/project.json");
  try {
    await writeFile(projectFile, `${JSON.stringify(project, null, 2)}\n`, { encoding: "utf8", flag: "wx" });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "EEXIST") {
      const existing = await readProject(options.root);
      return { project: existing, created: false, reusedCanonical: true };
    }
    throw error;
  }
  return { project, created: true, reusedCanonical: true };
}

/**
 * Scaffold a clean shared workspace + minimal project.json.
 * Does not run academic-grill.
 * If the canonical layout already exists, rebinds project.json instead of failing.
 */
export async function bootstrapProject(options: BootstrapOptions): Promise<ResearchProject> {
  const paths = projectPaths(options.root);
  const now = options.now ?? new Date().toISOString();
  const goal = (options.goal?.trim() || "未命名研究项目");
  const paradigm: ResearchParadigm = options.paradigm ?? "survey-observational";

  try {
    return await readProject(options.root);
  } catch {
    // continue
  }

  if (await hasCanonicalWorkspace(options.root)) {
    const bound = await ensureProjectBinding({ ...options, goal, paradigm, now });
    return bound.project;
  }

  const project: ResearchProject = {
    id: options.projectId ?? `project_${randomUUID().replaceAll("-", "")}`,
    root: paths.root,
    paradigm,
    goal,
    policyVersion: CONTRACT_VERSION,
    createdAt: now,
  };
  asProject(project);
  await scaffoldWorkspace(paths.root, { label: goal });
  const projectFile = await assertSafeProjectPath(paths.root, ".psyclaw/project.json");
  try {
    await writeFile(projectFile, `${JSON.stringify(project, null, 2)}\n`, { encoding: "utf8", flag: "wx" });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "EEXIST") {
      return readProject(options.root);
    }
    throw error;
  }
  return project;
}

export async function writeHandoff(
  root: string,
  input: Omit<Handoff, "schemaVersion">,
): Promise<Handoff> {
  const paths = projectPaths(root);
  const handoff: Handoff = { schemaVersion: "psyclaw/handoff/v1", ...input };
  asHandoff(handoff);
  const markdown = [
    "# psyclaw Handoff",
    "",
    `- Project: ${handoff.projectId}`,
    `- Run: ${handoff.runId}`,
    `- Generated: ${handoff.generatedAt}`,
    "",
    "## Goal",
    "",
    handoff.goal,
    "",
    "## Completed",
    "",
    ...handoff.completed.map((item) => `- ${item}`),
    "",
    "## Verified",
    "",
    ...handoff.verified.map((item) => `- ${item}`),
    "",
    "## Blocked",
    "",
    ...(handoff.blocked.length ? handoff.blocked.map((item) => `- ${item}`) : ["- None"]),
    "",
    "## Next Steps",
    "",
    ...handoff.nextSteps.map((item) => `- ${item}`),
    "",
    "## Verification Commands",
    "",
    ...handoff.verificationCommands.map((item) => `- \`${item}\``),
    "",
  ].join("\n");
  await ensureProjectDirectories(paths.root);
  await assertSafeProjectPath(paths.root, ".psyclaw/notes/handoff.json");
  await assertSafeProjectPath(paths.root, ".psyclaw/notes/HANDOFF.md");
  await atomicWriteFile(paths.handoffJson, `${JSON.stringify(handoff, null, 2)}\n`);
  await atomicWriteFile(paths.handoffMarkdown, markdown);
  return handoff;
}
