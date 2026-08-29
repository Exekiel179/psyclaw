import { mkdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import type { ResearchProject } from "../core/contracts.js";
import { atomicWriteFile } from "../project/jsonl.js";
import { assertSafeProjectPath, projectPaths } from "../project/paths.js";
import { readManuscript } from "../project/manuscript.js";
import { searchOpenAlex, type MetaStudy } from "../workflows/meta-analysis.js";
import type { Plan, TaskNode, WorkerReport } from "./contracts.js";
import { runPlanWithPi, type PiExecutorOptions } from "./pi-executor.js";

export type ResearchAgentMode = "literature" | "review";

interface PersonaDefinition {
  id: string;
  label: string;
  role: TaskNode["role"];
  instructions: string;
}

const LITERATURE_PERSONAS: readonly PersonaDefinition[] = [
  {
    id: "landscape-mapper",
    label: "研究版图分析者",
    role: "researcher",
    instructions: "梳理研究主题、年代分布、代表性论文和研究方向。只依据提供的可核验元数据与摘要，不得补造论文内容。",
  },
  {
    id: "methods-scout",
    label: "方法学分析者",
    role: "analyst",
    instructions: "识别文献中的研究设计、测量与分析线索，指出仅凭元数据无法判断之处，不得把推测写成研究事实。",
  },
  {
    id: "evidence-critic",
    label: "证据批判者",
    role: "critic",
    instructions: "检查证据强弱、潜在偏倚、相互冲突与因果边界，明确区分检索结果、摘要信息和进一步需要全文核验的主张。",
  },
  {
    id: "gap-finder",
    label: "研究缺口分析者",
    role: "verifier",
    instructions: "寻找尚未充分覆盖的问题、对象、情境和方法，并把真正的证据缺口与单纯的检索缺口分开。",
  },
] as const;

const REVIEW_PERSONAS: readonly PersonaDefinition[] = [
  {
    id: "theory-reviewer",
    label: "理论与贡献审稿人",
    role: "critic",
    instructions: "以匿名同行评审标准检查问题重要性、理论定位、创新性、主张与证据的一致性。给出带稿件定位的主要与次要意见。",
  },
  {
    id: "methods-reviewer",
    label: "研究设计审稿人",
    role: "analyst",
    instructions: "检查抽样、设计、测量、效度、探索与确证边界、因果推断边界以及方法与问题的适配性。",
  },
  {
    id: "statistics-reviewer",
    label: "统计与可复现性审稿人",
    role: "verifier",
    instructions: "检查分析策略、效应量、置信区间、缺失值、稳健性、图表和可复现信息。不得重新计算或虚构任何统计量。",
  },
  {
    id: "ethics-editorial-reviewer",
    label: "伦理与编辑审稿人",
    role: "writer",
    instructions: "检查伦理、隐私、透明报告、引用表达、结构与可读性，并给出可执行但不直接改稿的建议。",
  },
] as const;

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

function personaMarkdown(persona: PersonaDefinition): string {
  return [
    "---",
    "schemaVersion: psyclaw/agent-persona/v1",
    `id: ${persona.id}`,
    `label: ${persona.label}`,
    "---",
    "",
    `# ${persona.label}`,
    "",
    persona.instructions,
    "",
    "所有判断必须标明依据和不确定性；不得虚构引用、数据、统计结果或稿件中不存在的内容。",
    "",
  ].join("\n");
}

/** Create only the personas needed for the requested workflow. Existing files are user-owned and remain unchanged. */
export async function ensureResearchAgentPersonas(root: string, mode: ResearchAgentMode): Promise<Array<PersonaDefinition & { prompt: string }>> {
  const definitions = mode === "literature" ? LITERATURE_PERSONAS : REVIEW_PERSONAS;
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
      const prompt = personaMarkdown(persona);
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
