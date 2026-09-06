import { mkdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import type { ResearchProject } from "../core/contracts.js";
import { atomicWriteFile } from "../project/jsonl.js";
import { assertSafeProjectPath, projectPaths } from "../project/paths.js";
import { readManuscript } from "../project/manuscript.js";
import { searchOpenAlex, type MetaStudy } from "../workflows/meta-analysis.js";
import type { Plan, TaskNode, WorkerReport } from "./contracts.js";
import { runPlanWithPi, type PiExecutorOptions } from "./pi-executor.js";
import {
  bundledPersonasForPack,
  personaMarkdown,
  type BundledPersonaDefinition,
} from "./bundled-personas.js";

export type ResearchAgentMode = "literature" | "review";

type PersonaDefinition = BundledPersonaDefinition;

export interface MultiAgentRunOptions extends Pick<PiExecutorOptions, "provider" | "model" | "env" | "timeoutMs"> {
  root: string;
  project: ResearchProject;
  onEvent?: PiExecutorOptions["onEvent"];
  skillGuidance?: string;
}

export interface MultiAgentResearchResult {
  runId: string;
  status: "completed" | "paused" | "blocked";
  outputPath: string;
  reports: WorkerReport[];
  diagnostics: string[];
}

function personaFile(persona: PersonaDefinition): string {
  return personaMarkdown(persona);
}

/** Create only the personas needed for the requested workflow. Existing files are user-owned and remain unchanged. */
export async function ensureResearchAgentPersonas(root: string, mode: ResearchAgentMode): Promise<Array<PersonaDefinition & { prompt: string }>> {
  const definitions = bundledPersonasForPack(mode);
  const directory = await assertSafeProjectPath(root, `.psyclaw/agents/${mode}`);
  await mkdir(directory, { recursive: true });
  const loaded: Array<PersonaDefinition & { prompt: string }> = [];
  for (const persona of definitions) {
    const relative = `.psyclaw/agents/${mode}/${persona.id}.md`;
    const path = await assertSafeProjectPath(root, relative);
    try {
      loaded.push({ ...persona, prompt: await readFile(path, "utf8") });
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      const prompt = personaFile(persona);
      await atomicWriteFile(path, prompt);
      loaded.push({ ...persona, prompt });
    }
  }
  return loaded;
}

function task(persona: PersonaDefinition & { prompt: string }, objective: string, inputs: string[]): TaskNode {
  return {
    id: persona.id,
    role: persona.role,
    objective: [persona.prompt, objective, "请用中文完成分析。summary 字段可以使用简洁 Markdown，但必须保留论文 DOI/OpenAlex 标识或稿件章节定位。"].join("\n\n"),
    deps: [],
    ownedPaths: [],
    parallelSafe: true,
    inputs,
    outputs: [],
    allowedEffects: ["read"],
    completionContract: { requiredArtifacts: [], requiredReceiptEffects: [], mustPassGates: [] },
  };
}

function plan(runId: string, tasks: TaskNode[]): Plan {
  return {
    schemaVersion: "psyclaw/plan/v1",
    runId,
    tasks,
    budget: { maxTurns: tasks.length, maxWorkers: Math.min(4, tasks.length) },
    horizon: { strategy: "hierarchical-plan-act-reflect", maxIterations: tasks.length, reflectionEvery: 1 },
  };
}

async function savePlan(root: string, value: Plan): Promise<void> {
  await mkdir(projectPaths(root).plans, { recursive: true });
  await atomicWriteFile(join(projectPaths(root).plans, `${value.runId}.json`), `${JSON.stringify(value, null, 2)}\n`);
}

function reportsInPlanOrder(value: Plan, reports: WorkerReport[]): WorkerReport[] {
  const byTask = new Map(reports.map((report) => [report.taskId, report]));
  return value.tasks.map((item) => byTask.get(item.id)).filter((item): item is WorkerReport => item !== undefined);
}

async function writeSynthesis(root: string, relative: string, title: string, project: ResearchProject, reports: WorkerReport[], diagnostics: string[]): Promise<void> {
  const contents = [
    `# ${title}`,
    "",
    `研究目标：${project.goal}`,
    "",
    "> 本报告由相互独立的子智能体并发生成后汇总。它是研究或审稿辅助材料，不替代全文核验与研究者判断。",
    "",
    ...reports.flatMap((report) => [
      `## ${report.taskId}`,
      "",
      report.summary,
      "",
      ...(report.blockers.length ? ["### 阻断与待核验事项", "", ...report.blockers.map((item) => `- ${item}`), ""] : []),
    ]),
    ...(diagnostics.length ? ["## 运行诊断", "", ...diagnostics.map((item) => `- ${item}`), ""] : []),
  ].join("\n");
  await atomicWriteFile(await assertSafeProjectPath(root, relative), contents);
}

function studyInput(studies: MetaStudy[]): string {
  return JSON.stringify(studies.map((study) => ({
    openAlexId: study.id,
    title: study.title,
    authors: study.authors,
    abstract: study.abstract,
    year: study.year,
    venue: study.venue,
    doi: study.doi,
    citations: study.citations,
  })));
}

/** Search independently, then let four isolated Pi workers analyse separate evidence slices in parallel. */
export async function runParallelLiteratureResearch(options: MultiAgentRunOptions): Promise<MultiAgentResearchResult> {
  const personas = await ensureResearchAgentPersonas(options.root, "literature");
  const queries = [
    options.project.goal,
    `${options.project.goal} systematic review`,
    `${options.project.goal} empirical study`,
    `${options.project.goal} measurement methodology`,
  ];
  const batches = await Promise.all(queries.map((query) => searchOpenAlex(query, 12)));
  const seen = new Set<string>();
  const distinct = batches.map((batch) => batch.filter((study) => {
    const key = study.doi ?? study.id ?? study.title.toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }));
  const runId = `literature_agents_${Date.now()}`;
  const researchPlan = plan(runId, personas.map((persona, index) => task(
    persona,
    `围绕研究目标“${options.project.goal}”分析分配给你的 OpenAlex 检索结果。检索式：${queries[index]}. 这些记录仅表示检索命中；只有字段中明确出现的信息才可作为依据。${options.skillGuidance ? `\n用户指定的 Skill 指引：${options.skillGuidance}` : ""}`,
    [studyInput(distinct[index] ?? [])],
  )));
  await savePlan(options.root, researchPlan);
  const result = await runPlanWithPi(researchPlan, {
    cwd: options.root,
    root: options.root,
    maxWorkers: 4,
    ...(options.provider === undefined ? {} : { provider: options.provider }),
    ...(options.model === undefined ? {} : { model: options.model }),
    ...(options.env === undefined ? {} : { env: options.env }),
    ...(options.timeoutMs === undefined ? {} : { timeoutMs: options.timeoutMs }),
    ...(options.onEvent === undefined ? {} : { onEvent: options.onEvent }),
  });
  const reports = reportsInPlanOrder(researchPlan, result.reports);
  const outputPath = "outputs/multi-agent-literature-report.md";
  await writeSynthesis(options.root, outputPath, "多智能体文献调研报告", options.project, reports, result.diagnostics);
  return { runId, status: result.status, outputPath, reports, diagnostics: result.diagnostics };
}

/** Run four independent reviewers against the current manuscript; no worker may edit it. */
export async function runParallelPeerReview(options: MultiAgentRunOptions): Promise<MultiAgentResearchResult> {
  const manuscript = await readManuscript(options.root);
  const isActualManuscript = manuscript.path === "notes/manuscript.md"
    || manuscript.path?.startsWith("paper/")
    || manuscript.path?.startsWith("docs/");
  if (!manuscript.exists || !manuscript.path || !isActualManuscript || !manuscript.markdown.trim()) {
    throw new Error("未找到可审稿的论文。请先完成并保存手稿，再运行 /review");
  }
  const manuscriptPath = manuscript.path;
  const personas = await ensureResearchAgentPersonas(options.root, "review");
  const runId = `peer_review_agents_${Date.now()}`;
  const reviewPlan = plan(runId, personas.map((persona) => task(
    persona,
    `对当前手稿 ${manuscriptPath} 进行独立模拟同行评审。输出总体建议（接收/小修/大修/拒稿仅作模拟）、主要问题、次要问题、具体定位和修改理由。不得直接修改手稿。${options.skillGuidance ? `\n用户指定的 Skill 指引：${options.skillGuidance}` : ""}`,
    [manuscriptPath],
  )));
  await savePlan(options.root, reviewPlan);
  const result = await runPlanWithPi(reviewPlan, {
    cwd: options.root,
    root: options.root,
    maxWorkers: 4,
    ...(options.provider === undefined ? {} : { provider: options.provider }),
    ...(options.model === undefined ? {} : { model: options.model }),
    ...(options.env === undefined ? {} : { env: options.env }),
    ...(options.timeoutMs === undefined ? {} : { timeoutMs: options.timeoutMs }),
    ...(options.onEvent === undefined ? {} : { onEvent: options.onEvent }),
  });
  const reports = reportsInPlanOrder(reviewPlan, result.reports);
  const outputPath = "outputs/simulated-peer-review.md";
  await writeSynthesis(options.root, outputPath, "多智能体模拟同行评审", options.project, reports, result.diagnostics);
  return { runId, status: result.status, outputPath, reports, diagnostics: result.diagnostics };
}
