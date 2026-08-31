import { writeFile, readFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import { join } from "node:path";
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

export interface AnalysisDocsProject {
  goal: string;
  paradigm: ResearchParadigm;
}

const PARADIGM_VALUES = new Set<ResearchParadigm>([
  "survey-observational",
  "qualitative-thematic",
  "experimental",
  "quasi-experimental",
  "longitudinal-panel",
  "meta-analysis",
  "ethnographic",
  "historical-documentary",
  "policy-legal",
  "mixed-methods",
]);

function hasFrontmatterSchema(text: string, expected: string): boolean {
  const match = text.replace(/^\uFEFF/, "").match(/^---[ \t]*\r?\n([\s\S]*?)\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|$)/);
  if (!match?.[1]) return false;
  const escaped = expected.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(?:^|\\n)\\s*schemaVersion\\s*:\\s*${escaped}(?:\\s|$)`, "i").test(match[1]);
}

function frontmatterBody(text: string): string {
  const match = text.replace(/^\uFEFF/, "").match(/^---[ \t]*\r?\n[\s\S]*?\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|$)/);
  return match ? text.slice(match[0].length) : text;
}

async function readTextIfExists(path: string): Promise<string | null> {
  try {
    return await readFile(path, "utf8");
  } catch {
    return null;
  }
}

/**
 * Detect whether the project already contains compliant analysis documents
 * (the HITL research specification and plan with valid schemas) so `/run` can
 * skip the explicit `/init` step.  Returns null when the project is not
 * analysis-ready.
 */
export async function readAnalysisDocsProject(root: string): Promise<AnalysisDocsProject | null> {
  const paths = projectPaths(root);
  const researchSpec = await readTextIfExists(join(paths.root, "notes", "research-spec.md"));
  const plan = await readTextIfExists(join(paths.root, "notes", "plan.md"));
  if (!researchSpec || !plan) return null;
  if (!hasFrontmatterSchema(researchSpec, "psyclaw/research-spec/v1")) return null;
  if (!hasFrontmatterSchema(plan, "psyclaw/hitl-plan/v1")) return null;

  let goal = "";
  const goalDoc = await readTextIfExists(join(paths.root, "notes", "goal.md"));
  if (goalDoc) {
    goal = frontmatterBody(goalDoc)
      .split(/\r?\n/)
      .map((line) => line.trim())
      .find((line) => line.length > 0 && !line.startsWith("#")) ?? "";
  }
  if (!goal) {
    const initial = researchSpec.split(/\r?\n/).find((line) => /initial goal:/i.test(line));
    goal = (initial ?? "").replace(/^[-\s]*initial goal:\s*/i, "").trim();
  }
  if (!goal) return null;

  const paradigmLine = researchSpec.split(/\r?\n/).find((line) => /paradigm:/i.test(line));
  const paradigmName = (paradigmLine ?? "").replace(/^[-\s]*paradigm:\s*/i, "").trim().toLowerCase() as ResearchParadigm;
  const paradigm: ResearchParadigm = PARADIGM_VALUES.has(paradigmName) ? paradigmName : "survey-observational";
  return { goal, paradigm };
}

/**
 * Bootstrap a project from existing compliant analysis documents.  This lets
 * `/run` work on a project that was prepared outside the `/init` flow, as long
 * as the required research-spec and plan documents are present and valid.
 */
export async function bootstrapProjectFromAnalysisDocs(root: string): Promise<ResearchProject> {
  const docs = await readAnalysisDocsProject(root);
  if (!docs) {
    throw new Error("项目中缺少合规的分析文档（notes/research-spec.md 与 notes/plan.md 且 schemaVersion 正确）；请先运行 /init，或补充这些文档后重试。");
  }
  try {
    return await bootstrapProject({ root, goal: docs.goal, paradigm: docs.paradigm });
  } catch (error) {
    // The project file may have been created concurrently or is corrupt;
    // surface the original error so the user can repair it.
    throw error;
  }
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
