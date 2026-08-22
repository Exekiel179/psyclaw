import { writeFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import type { Handoff, ResearchParadigm, ResearchProject } from "../core/contracts.js";
import { CONTRACT_VERSION } from "../core/contracts.js";
import { asHandoff, asProject } from "../core/schemas.js";
import { atomicWriteFile } from "./jsonl.js";
import { projectPaths, ensureProjectDirectories, assertSafeProjectPath } from "./paths.js";
import { initializeHitlWorkspace } from "./hitl.js";

export interface BootstrapOptions {
  root: string;
  goal: string;
  paradigm: ResearchParadigm;
  projectId?: string;
  now?: string;
}

export async function bootstrapProject(options: BootstrapOptions): Promise<ResearchProject> {
  const paths = projectPaths(options.root);
  const now = options.now ?? new Date().toISOString();
  const project: ResearchProject = {
    id: options.projectId ?? `project_${randomUUID().replaceAll("-", "")}`,
    root: paths.root,
    paradigm: options.paradigm,
    goal: options.goal.trim(),
    policyVersion: CONTRACT_VERSION,
    createdAt: now,
  };
  if (!project.goal) throw new Error("Research goal cannot be empty");
  // Validate the complete record before creating any project directories. An
  // invalid request must not leave behind a misleading partial project.
  asProject(project);
  await ensureProjectDirectories(paths.root);
  await initializeHitlWorkspace(paths.root, project.goal);
  const projectFile = await assertSafeProjectPath(paths.root, ".psyclaw/project.json");
  try {
    await writeFile(projectFile, `${JSON.stringify(project, null, 2)}\n`, { encoding: "utf8", flag: "wx" });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "EEXIST") {
      throw new Error(`Project already initialized: ${projectFile}`);
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
  // Validate before touching the filesystem, then replace each artifact via a
  // same-directory temporary file so readers never observe partial JSON/MD.
  await ensureProjectDirectories(paths.root);
  await assertSafeProjectPath(paths.root, "notes/handoff.json");
  await assertSafeProjectPath(paths.root, "notes/HANDOFF.md");
  await atomicWriteFile(paths.handoffJson, `${JSON.stringify(handoff, null, 2)}\n`);
  await atomicWriteFile(paths.handoffMarkdown, markdown);
  return handoff;
}
