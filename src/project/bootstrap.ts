import { writeFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import type { Handoff, ResearchParadigm, ResearchProject } from "../core/contracts.js";
import { CONTRACT_VERSION } from "../core/contracts.js";
import { asHandoff, asProject } from "../core/schemas.js";
import { atomicWriteFile } from "./jsonl.js";
import { projectPaths, ensureProjectDirectories, assertSafeProjectPath } from "./paths.js";
import { scaffoldWorkspace } from "./workspace.js";
import { defaultVerifyChecklist, saveVerifyChecklist } from "../verify/checklist.js";

export interface BootstrapOptions {
  root: string;
  /** Optional; defaults to a placeholder so /init can be scaffold-only. */
  goal?: string;
  paradigm?: ResearchParadigm;
  projectId?: string;
  now?: string;
}

/**
 * Scaffold a clean shared workspace + minimal project.json.
 * Does not run academic-grill or create a controlled /run.
 */
export async function bootstrapProject(options: BootstrapOptions): Promise<ResearchProject> {
  const paths = projectPaths(options.root);
  const now = options.now ?? new Date().toISOString();
  const goal = (options.goal?.trim() || "未命名研究项目");
  const paradigm: ResearchParadigm = options.paradigm ?? "survey-observational";
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
  await saveVerifyChecklist(paths.root, defaultVerifyChecklist(now));
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
  await ensureProjectDirectories(paths.root);
  await assertSafeProjectPath(paths.root, ".psyclaw/notes/handoff.json");
  await assertSafeProjectPath(paths.root, ".psyclaw/notes/HANDOFF.md");
  await atomicWriteFile(paths.handoffJson, `${JSON.stringify(handoff, null, 2)}\n`);
  await atomicWriteFile(paths.handoffMarkdown, markdown);
  return handoff;
}
