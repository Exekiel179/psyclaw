import { readFile } from "node:fs/promises";
import { atomicWriteFile } from "./jsonl.js";
import { assertSafeProjectPath } from "./paths.js";

export const HITL_SCHEMA = "psyclaw/hitl/v1" as const;

export interface HitlFile {
  path: string;
  label: string;
  status: "ready" | "pending" | "missing";
  contents?: string;
}

const header = (schema: string, title: string): string => `---\nschemaVersion: ${schema}\ndocumentVersion: 1.0.0\n---\n\n# ${title}\n\n`;

const templates: readonly { path: string; label: string; contents: (goal: string) => string }[] = [
  { path: "notes/goal.md", label: "Goal", contents: (goal) => `${header("psyclaw/hitl-goal/v1", "Research Goal")}${goal}\n\n## Scope\n\n- Population / context: to be defined\n- Primary question: to be defined\n- Exclusions: none approved\n` },
  { path: "notes/plan.md", label: "Plan", contents: (goal) => `${header("psyclaw/hitl-plan/v1", "Research Plan")}- Status: awaiting-human\n- Goal: ${goal}\n\n| Step | Owner | Inputs | Outputs | Approval needed | Status |\n| --- | --- | --- | --- | --- | --- |\n| 1 | planner | goal and project context | this plan | yes | pending |\n| 2 | executor | approved plan | outputs/* and logs/run_log.md | yes for side effects | pending |\n| 3 | critic | scripts and outputs | notes/review.md | yes | pending |\n| 4 | verifier | review and receipts | notes/repro_manifest.md | yes | pending |\n\n## Stop Conditions\n\n- Missing or unverifiable input\n- Any raw-data mutation, deletion, recoding, or external side effect without approval\n- Blocking issue in the critic review\n` },
  { path: "notes/decision_request.md", label: "Decision Request", contents: () => `${header("psyclaw/hitl-decision-request/v1", "Decision Request")}- Status: none\n- Requested by: -\n- Decision needed: -\n- Affected paths: -\n- Evidence / alternatives: -\n\n> Write a request here and pause before changing raw data, recoding, excluding cases, or taking a destructive/external action.\n` },
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
