import { mkdir, readdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import { atomicWriteFile } from "../project/jsonl.js";
import { assertSafeProjectPath, projectPaths } from "../project/paths.js";
import { validateAnalysisPlan, type AnalysisPlanContract } from "./hooks.js";

export const ANALYSIS_PLAN_SCHEMA = "psyclaw/analysis-plan/v1" as const;
export const ANALYSIS_PLAN_ACTIVE = "analysis/plans/active.json" as const;

export type AnalysisPlanStatus =
  | "clarifying"
  | "drafting"
  | "awaiting-confirm"
  | "reviewing"
  | "ready"
  | "running"
  | "deferred"
  | "completed"
  | "blocked";

export type AnalysisPlanStage =
  | "clarify-eda"
  | "propose"
  | "confirm"
  | "review"
  | "execute"
  | "report-checks"
  | "handoff";

export type AnalysisExecutionBackend = "local-script" | "mcp" | "undecided";

export type AnalysisApprovalMode = "human" | "auto";

export interface AnalysisPlanChoice {
  id: string;
  question: string;
  /** First option should be a concrete new method; “already enough” may appear last. */
  options: string[];
  recommendation?: string;
  selected?: string;
  decidedAt?: string;
}

export interface AnalysisPlanEdaNote {
  at: string;
  summary: string;
  paths?: string[];
}

export interface AnalysisPlanRecord extends AnalysisPlanContract {
  schemaVersion: typeof ANALYSIS_PLAN_SCHEMA;
  id: string;
  status: AnalysisPlanStatus;
  stage: AnalysisPlanStage;
  goal: string;
  dataPaths: string[];
  questions: string[];
  edaNotes: AnalysisPlanEdaNote[];
  proposedMethods: string[];
  /** One human (or auto) decision per analysis step — not a single mega-confirm. */
  analysisChoices: AnalysisPlanChoice[];
  confirmedMethod?: string;
  executionBackend: AnalysisExecutionBackend;
  approvalMode: AnalysisApprovalMode;
  mcpServer?: string;
  scriptEntrypoint?: string;
  reviewFindings: string[];
  runPreference: "unset" | "now" | "later";
  createdAt: string;
  updatedAt: string;
  notes?: string;
}

const STATUS_STAGE: Record<AnalysisPlanStatus, AnalysisPlanStage> = {
  clarifying: "clarify-eda",
  drafting: "propose",
  "awaiting-confirm": "confirm",
  reviewing: "review",
  ready: "execute",
  running: "execute",
  deferred: "execute",
  completed: "handoff",
  blocked: "review",
};

function nowIso(): string {
  return new Date().toISOString();
}

function planId(now = Date.now()): string {
  return `ap_${now}`;
}

export function createAnalysisPlan(input: {
  goal: string;
  dataPaths?: string[];
  confirmatory?: boolean;
  now?: string;
}): AnalysisPlanRecord {
  const createdAt = input.now ?? nowIso();
  return {
    schemaVersion: ANALYSIS_PLAN_SCHEMA,
    id: planId(Date.parse(createdAt) || Date.now()),
    status: "clarifying",
    stage: "clarify-eda",
    goal: input.goal.trim() || "未命名分析目标",
    confirmatory: input.confirmatory === true,
    exploratoryAnalyses: input.confirmatory === true ? [] : ["待澄清后声明"],
    dataPaths: [...(input.dataPaths ?? [])],
    questions: [],
    edaNotes: [],
    proposedMethods: [],
    analysisChoices: [],
    executionBackend: "local-script",
    approvalMode: "human",
    reviewFindings: [],
    runPreference: "unset",
    createdAt,
    updatedAt: createdAt,
  };
}

export async function analysisPlansDir(root: string): Promise<string> {
  const dir = await assertSafeProjectPath(root, "analysis/plans");
  await mkdir(dir, { recursive: true });
  return dir;
}

export async function writeAnalysisPlan(root: string, plan: AnalysisPlanRecord): Promise<AnalysisPlanRecord> {
  const dir = await analysisPlansDir(root);
  const updated: AnalysisPlanRecord = { ...plan, stage: STATUS_STAGE[plan.status], updatedAt: nowIso() };
  const file = join(dir, `${updated.id}.json`);
  await atomicWriteFile(file, `${JSON.stringify(updated, null, 2)}\n`);
  await atomicWriteFile(join(dir, "active.json"), `${JSON.stringify({ schemaVersion: "psyclaw/analysis-plan-active/v1", planId: updated.id, updatedAt: updated.updatedAt }, null, 2)}\n`);
  await atomicWriteFile(join(dir, `${updated.id}.md`), renderAnalysisPlanMarkdown(updated));
  return updated;
}

export async function readAnalysisPlan(root: string, id: string): Promise<AnalysisPlanRecord | null> {
  try {
    const path = await assertSafeProjectPath(root, `analysis/plans/${id}.json`);
    const value = JSON.parse(await readFile(path, "utf8")) as AnalysisPlanRecord;
    if (value.schemaVersion !== ANALYSIS_PLAN_SCHEMA || typeof value.id !== "string") return null;
    return {
      ...value,
      analysisChoices: Array.isArray(value.analysisChoices) ? value.analysisChoices : [],
      approvalMode: value.approvalMode === "auto" ? "auto" : "human",
    };
  } catch {
    return null;
  }
}

export async function readActiveAnalysisPlan(root: string): Promise<AnalysisPlanRecord | null> {
  try {
    const activePath = await assertSafeProjectPath(root, ANALYSIS_PLAN_ACTIVE);
    const active = JSON.parse(await readFile(activePath, "utf8")) as { planId?: string };
    if (!active.planId) return null;
    return readAnalysisPlan(root, active.planId);
  } catch {
    return null;
  }
}

export async function listAnalysisPlans(root: string): Promise<string[]> {
  try {
    const dir = await analysisPlansDir(root);
    const names = await readdir(dir);
    return names.filter((name) => /^ap_\d+\.json$/.test(name)).map((name) => name.replace(/\.json$/, "")).sort();
  } catch {
    return [];
  }
}

export function advanceAnalysisPlan(
  plan: AnalysisPlanRecord,
  action:
    | { type: "add-question"; question: string }
    | { type: "add-eda"; summary: string; paths?: string[] }
    | { type: "draft"; primaryOutcome?: string; primaryAnalysis?: string; exploratoryAnalyses?: string[]; proposedMethods?: string[]; missingDataPlan?: string; multiplicityPlan?: string; exclusionCriteria?: string }
    | { type: "add-choice"; choice: Omit<AnalysisPlanChoice, "selected" | "decidedAt"> }
    | { type: "decide-choice"; id: string; selected: string }
    | { type: "set-approval-mode"; mode: AnalysisApprovalMode }
    | { type: "confirm"; method: string; backend?: AnalysisExecutionBackend; mcpServer?: string }
    | { type: "review" }
    | { type: "ready" }
    | { type: "run-now" }
    | { type: "defer" }
    | { type: "complete"; scriptEntrypoint?: string }
    | { type: "block"; reason: string },
): AnalysisPlanRecord {
  const next: AnalysisPlanRecord = {
    ...plan,
    analysisChoices: [...(plan.analysisChoices ?? [])],
    approvalMode: plan.approvalMode ?? "human",
    updatedAt: nowIso(),
  };
  switch (action.type) {
    case "add-question":
      next.questions = [...plan.questions, action.question.trim()].filter(Boolean);
      next.status = "clarifying";
      break;
    case "add-eda":
      next.edaNotes = [...plan.edaNotes, { at: nowIso(), summary: action.summary.trim(), ...(action.paths ? { paths: action.paths } : {}) }];
      next.status = "clarifying";
      break;
    case "draft":
      if (action.primaryOutcome !== undefined) next.primaryOutcome = action.primaryOutcome;
      if (action.primaryAnalysis !== undefined) next.primaryAnalysis = action.primaryAnalysis;
      if (action.exploratoryAnalyses !== undefined) next.exploratoryAnalyses = action.exploratoryAnalyses;
      if (action.proposedMethods !== undefined) next.proposedMethods = action.proposedMethods;
      if (action.missingDataPlan !== undefined) next.missingDataPlan = action.missingDataPlan;
      if (action.multiplicityPlan !== undefined) next.multiplicityPlan = action.multiplicityPlan;
      if (action.exclusionCriteria !== undefined) next.exclusionCriteria = action.exclusionCriteria;
      next.status = "awaiting-confirm";
      break;
    case "add-choice":
      next.analysisChoices = [...next.analysisChoices.filter((row) => row.id !== action.choice.id), { ...action.choice }];
      next.status = "awaiting-confirm";
      break;
    case "decide-choice": {
      next.analysisChoices = next.analysisChoices.map((row) =>
        row.id === action.id ? { ...row, selected: action.selected.trim(), decidedAt: nowIso() } : row);
      break;
    }
    case "set-approval-mode":
      next.approvalMode = action.mode;
      if (action.mode === "auto") {
        next.notes = [next.notes, "approvalMode=auto：结果须标注「未经人审批」"].filter(Boolean).join("\n");
      }
      break;
    case "confirm":
      next.confirmedMethod = action.method.trim();
      next.primaryAnalysis = action.method.trim();
      next.executionBackend = action.backend ?? "local-script";
      if (action.mcpServer) next.mcpServer = action.mcpServer;
      next.status = "reviewing";
      break;
    case "review": {
      const result = validateAnalysisPlan(next);
      next.reviewFindings = result.findings.map((finding) => `${finding.severity}: ${finding.message}`);
      next.status = result.findings.some((finding) => finding.severity === "block") ? "blocked" : "ready";
      break;
    }
    case "ready":
      next.status = "ready";
      break;
    case "run-now":
      next.runPreference = "now";
      next.status = "running";
      break;
    case "defer":
      next.runPreference = "later";
      next.status = "deferred";
      break;
    case "complete":
      if (action.scriptEntrypoint) next.scriptEntrypoint = action.scriptEntrypoint;
      next.status = "completed";
      break;
    case "block":
      next.reviewFindings = [...next.reviewFindings, `block: ${action.reason}`];
      next.status = "blocked";
      break;
  }
  next.stage = STATUS_STAGE[next.status];
  return next;
}

export function renderAnalysisPlanMarkdown(plan: AnalysisPlanRecord): string {
  const lines = [
    `# Analysis plan \`${plan.id}\``,
    "",
    `- Status: **${plan.status}** (stage: ${plan.stage})`,
    `- Goal: ${plan.goal}`,
    `- Confirmatory: ${plan.confirmatory ? "yes" : "no (exploratory OK if disclosed)"}`,
    `- Execution: ${plan.executionBackend}${plan.mcpServer ? ` (${plan.mcpServer})` : ""}`,
    `- Approval mode: **${plan.approvalMode ?? "human"}**${(plan.approvalMode ?? "human") === "auto" ? "（结果须标注未经人审批）" : ""}`,
    `- Run preference: ${plan.runPreference}`,
    "",
    "## Per-analysis choices",
    "",
    ...(plan.analysisChoices?.length
      ? plan.analysisChoices.map((choice) => {
        const picked = choice.selected ? ` → **${choice.selected}**` : "（待选）";
        return `- ${choice.id}: ${choice.question}${picked}\n  Options: ${choice.options.join(" | ")}${choice.recommendation ? `\n  Recommend: ${choice.recommendation}` : ""}`;
      })
      : ["- (none yet — add one choice per proposed analysis; first option = concrete new method; last may be「已经足够」)"]),
    "",
    "## Data",
    "",
    ...(plan.dataPaths.length > 0 ? plan.dataPaths.map((path) => `- ${path}`) : ["- (not set)"]),
    "",
    "## Clarifying questions",
    "",
    ...(plan.questions.length > 0 ? plan.questions.map((q, i) => `${i + 1}. ${q}`) : ["- (none yet)"]),
    "",
    "## EDA notes",
    "",
    ...(plan.edaNotes.length > 0
      ? plan.edaNotes.map((note) => `- ${note.at}: ${note.summary}${note.paths?.length ? ` (${note.paths.join(", ")})` : ""}`)
      : ["- (none yet)"]),
    "",
    "## Proposal",
    "",
    `- Primary outcome: ${plan.primaryOutcome ?? "(missing)"}`,
    `- Primary analysis: ${plan.primaryAnalysis ?? "(missing)"}`,
    `- Confirmed method: ${plan.confirmedMethod ?? "(not confirmed)"}`,
    `- Proposed methods: ${plan.proposedMethods.join("; ") || "(none)"}`,
    `- Exploratory: ${(plan.exploratoryAnalyses ?? []).join("; ") || "(none)"}`,
    `- Missing data: ${plan.missingDataPlan ?? "(missing)"}`,
    `- Multiplicity: ${plan.multiplicityPlan ?? "(missing)"}`,
    `- Exclusion: ${plan.exclusionCriteria ?? "(missing)"}`,
    "",
    "## Review",
    "",
    ...(plan.reviewFindings.length > 0 ? plan.reviewFindings.map((item) => `- ${item}`) : ["- (not reviewed)"]),
    "",
    "## Execution",
    "",
    `- Script entrypoint: ${plan.scriptEntrypoint ?? "analysis/scripts/run_all.py (expected)"}`,
    "- Default: write local reproducible scripts; MCP only for special backends or explicit request.",
    "",
    "## Next",
    "",
    plan.status === "ready" || plan.status === "deferred"
      ? "- Choose `/plan run` (now) or `/plan defer` (later), then execute."
      : plan.status === "completed"
        ? "- Update `analysis/HANDOFF.md` before switching to academic."
        : "- Continue the current stage; do not jump to academic/ARS.",
    "",
  ];
  return lines.join("\n");
}

export function formatAnalysisPlanStatus(plan: AnalysisPlanRecord): string {
  const pending = (plan.analysisChoices ?? []).filter((row) => !row.selected).length;
  return [
    `分析 Plan \`${plan.id}\` · ${plan.status}/${plan.stage}`,
    `目标：${plan.goal}`,
    `主分析：${plan.confirmedMethod ?? plan.primaryAnalysis ?? "（未确认）"}`,
    `审批：${plan.approvalMode ?? "human"}${pending > 0 ? ` · 待选分析 ${pending} 项` : ""}`,
    `后端：${plan.executionBackend}${plan.mcpServer ? `/${plan.mcpServer}` : ""} · 执行偏好：${plan.runPreference}`,
    `文件：analysis/plans/${plan.id}.md`,
    plan.reviewFindings.length > 0 ? `审核：${plan.reviewFindings.join("；")}` : "审核：尚未完成或无发现",
  ].join("\n");
}

/** Seed HANDOFF fields from a completed/ready plan without wiping human edits wholesale when stubby. */
export async function syncHandoffFromAnalysisPlan(root: string, plan: AnalysisPlanRecord): Promise<string> {
  const path = projectPaths(root).analysisHandoff;
  const block = [
    `# Analysis → Academic handoff`,
    "",
    `- Status: ${plan.status === "completed" ? "ready-for-academic" : "draft"}`,
    `- Plan id: ${plan.id}`,
    `- Question / design: ${plan.goal}`,
    `- Primary analysis: ${plan.confirmedMethod ?? plan.primaryAnalysis ?? ""}`,
    `- Primary outcome: ${plan.primaryOutcome ?? ""}`,
    `- Primary results paths: ${plan.scriptEntrypoint ?? "analysis/results/"}`,
    `- Key numbers (N, effects): (fill after execution)`,
    `- Limits / unverified items: ${(plan.reviewFindings.concat(plan.exploratoryAnalyses ?? [])).join("; ") || "none listed"}`,
    `- Ready for academic: ${plan.status === "completed" ? "yes-if-results-present" : "no"}`,
    "",
  ].join("\n");
  await mkdir(projectPaths(root).analysis, { recursive: true });
  await atomicWriteFile(path, block);
  return "analysis/HANDOFF.md";
}
