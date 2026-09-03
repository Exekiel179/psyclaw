import { readFile } from "node:fs/promises";
import { atomicWriteFile } from "./jsonl.js";
import { assertSafeProjectPath } from "./paths.js";

export const RESEARCH_WORKSPACE_SCHEMA = "psyclaw/research-workspace/v1" as const;
/** @deprecated Kept as a source-compatible alias; this module is a project
 * workspace, not an always-on human-approval system. */
export const HITL_SCHEMA = RESEARCH_WORKSPACE_SCHEMA;

export interface HitlFile {
  path: string;
  label: string;
  status: "ready" | "pending" | "missing";
  contents?: string;
}

const header = (schema: string, title: string): string => `---\nschemaVersion: ${schema}\ndocumentVersion: 1.0.0\n---\n\n# ${title}\n\n`;

const templates: readonly { path: string; label: string; contents: (goal: string) => string }[] = [
  { path: "notes/goal.md", label: "Goal", contents: (goal) => `${header("psyclaw/research-goal/v1", "Research Goal")}${goal}\n\n## Scope\n\n- Population / context: to be defined\n- Primary question: to be defined\n- Exclusions: none confirmed\n` },
  { path: "notes/research-spec.md", label: "Research Specification", contents: (goal) => `${header("psyclaw/research-spec/v1", "Research Specification")}- Status: awaiting-grill\n- Initial goal: ${goal}\n- Paradigm: to be confirmed\n- Exploratory / confirmatory boundary: to be confirmed\n\n## Research Question\n\nTo be clarified through /grill.\n\n## Constructs and Scope\n\nTo be clarified through /grill.\n\n## Design and Evidence\n\nTo be clarified through /grill.\n\n## Analysis and Reporting Commitments\n\nTo be clarified through /grill.\n\n## Claims Boundary\n\nNo empirical claim is established by this planning document.\n` },
  { path: "notes/decisions.md", label: "Research Decisions", contents: () => `${header("psyclaw/research-decisions/v1", "Research Decisions")}- Status: none\n\n| Decision | Rationale | Alternatives considered | Owner | Status |\n| --- | --- | --- | --- | --- |\n| None recorded | - | - | - | - |\n` },
  { path: "notes/plan.md", label: "Plan", contents: (goal) => `${header("psyclaw/research-plan/v1", "Research Plan")}- Status: drafting-specification\n- Goal: ${goal}\n\n| Step | Owner | Inputs | Outputs | Researcher decision | Status |\n| --- | --- | --- | --- | --- | --- |\n| 1 | planner | goal and project context | this plan | only for unresolved research trade-offs | pending |\n| 2 | executor | current plan | outputs/* and logs/run_log.md | only for unresolved research trade-offs | pending |\n| 3 | critic | scripts and outputs | notes/review.md | only when competing interpretations remain | pending |\n| 4 | verifier | review and receipts | notes/repro_manifest.md | no | pending |\n\n## Research Decision Condition\n\n- Two or more substantively defensible choices remain after available evidence and established methods have been checked, and the choice changes the research question, sample treatment, operationalization, estimand, method, or interpretation\n\n## Separate Safety Boundaries\n\n- Credentials, raw-data overwrite, destructive operations, access-control bypass, and external publication require separate authorization or refusal; they never create a research-decision state\n` },
  { path: "notes/decision_request.md", label: "Decision Request", contents: () => `${header("psyclaw/research-decision-request/v1", "Research Decision Request")}- Status: none\n- Decision needed: -\n- Evidence reviewed: -\n- Established methods checked: -\n- Why the disagreement remains unresolved: -\n- Alternatives, evidence, and consequences: -\n- Recommended option: -\n\n> Use this file only when two or more defensible research choices remain after checking available evidence and established methods, and the choice changes the research question, sample treatment, operationalization, estimand, method, or interpretation. Software installation, formatting, recoverable execution errors, and repairable reporting omissions are not researcher decisions.\n` },
  { path: "notes/review.md", label: "Critic Review", contents: () => `${header("psyclaw/hitl-review/v1", "Critic Review")}- Status: pending\n- Reviewer: -\n- Reviewed run: -\n\n## Blocking Issues\n\n- None recorded\n\n## Warnings\n\n- Review not completed\n\n## Approved Points\n\n- -\n` },
  { path: "notes/repro_manifest.md", label: "Reproducibility Manifest", contents: () => `${header("psyclaw/hitl-repro-manifest/v1", "Reproducibility Manifest")}- Status: pending\n- Run: -\n- Environment: -\n- Commands: -\n- Inputs and hashes: -\n- Outputs and hashes: -\n` },
  { path: "logs/run_log.md", label: "Run Log", contents: () => `${header("psyclaw/hitl-run-log/v1", "Run Log")}| Time | Step | Command / tool | Inputs | Outputs | Status | Receipt |\n| --- | --- | --- | --- | --- | --- | --- |\n` },
];

export async function initializeHitlWorkspace(root: string, goal: string): Promise<void> {
  for (const template of templates) {
    const target = await assertSafeProjectPath(root, template.path);
    try { await readFile(target, "utf8"); }
    catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      await atomicWriteFile(target, template.contents(goal.trim()));
    }
  }
}

export async function readHitlWorkspace(root: string, includeContents = false): Promise<{ schemaVersion: typeof HITL_SCHEMA; files: HitlFile[] }> {
  const files: HitlFile[] = [];
  for (const template of templates) {
    const target = await assertSafeProjectPath(root, template.path);
    try {
      const contents = await readFile(target, "utf8");
      files.push({ path: template.path, label: template.label, status: contents.includes("Status: pending") || contents.includes("Status: awaiting-human") ? "pending" : "ready", ...(includeContents ? { contents } : {}) });
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      files.push({ path: template.path, label: template.label, status: "missing" });
    }
  }
  return { schemaVersion: HITL_SCHEMA, files };
}
