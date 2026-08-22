import type { ExtensionAPI, ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { asProject, bootstrapProject, projectPaths, runOfflineBrief, runInstitutionalFulltext, runLiteratureReview, runExpertReview, runAnalysisDelegation, runWritingReview, runMetaAnalysis, createStageRunner, publishManuscript, recordCitationUse, writeHandoff } from "../../index.js";
import type { ResearchParadigm } from "../../core/contracts.js";
import { runPlanWithPi } from "../../orchestration/pi-executor.js";
import { atomicWriteFile } from "../../project/jsonl.js";
import { RunEventLog } from "../../panel/events.js";
import { readProject } from "../../research/ledger.js";
import { join } from "node:path";
import { mkdir, readFile } from "node:fs/promises";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

const PARADIGMS = new Set<ResearchParadigm>([
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

function parseResearchArgs(args: string): { goal: string; paradigm: ResearchParadigm } {
  const trimmed = args.trim();
  const match = trimmed.match(/^--paradigm(?:=|\s+)(\S+)(?:\s+([\s\S]*))?$/i);
  if (trimmed.startsWith("--")) {
    const paradigm = match?.[1] as ResearchParadigm | undefined;
    const goal = match?.[2]?.trim();
    if (!match || !paradigm || !goal) {
      throw new Error("Usage: /research --paradigm survey-observational <research goal>");
    }
    if (!PARADIGMS.has(paradigm)) throw new Error(`Unsupported paradigm: ${paradigm}`);
    return { paradigm, goal };
  }
  if (!trimmed) throw new Error("Usage: /research --paradigm survey-observational <research goal>");
  return { paradigm: "survey-observational", goal: trimmed };
}

async function notifyError(ctx: ExtensionCommandContext, error: unknown): Promise<void> {
  ctx.ui.notify(error instanceof Error ? error.message : String(error), "error");
}

const activeAgentRuns = new Set<string>();
const CORE_SKILLS = new Set(["research-intake", "evidence-capture", "citation-audit", "research-brief"]);
type RecommendationKind = "skill" | "mcp";
interface RecommendationState { schemaVersion: "psyclaw/recommendation-state/v1"; skills: string[]; mcp: string[]; }

async function recommendationState(root: string): Promise<RecommendationState> {
  try {
    const value = JSON.parse(await readFile(join(root, ".psyclaw", "recommendations.json"), "utf8")) as Partial<RecommendationState>;
    return { schemaVersion: "psyclaw/recommendation-state/v1", skills: Array.isArray(value.skills) ? value.skills.filter((id): id is string => typeof id === "string") : [], mcp: Array.isArray(value.mcp) ? value.mcp.filter((id): id is string => typeof id === "string") : [] };
  } catch { return { schemaVersion: "psyclaw/recommendation-state/v1", skills: [], mcp: [] }; }
}

async function saveRecommendationState(root: string, state: RecommendationState): Promise<void> {
  await mkdir(join(root, ".psyclaw"), { recursive: true });
  await atomicWriteFile(join(root, ".psyclaw", "recommendations.json"), `${JSON.stringify({ ...state, skills: [...new Set(state.skills)].sort(), mcp: [...new Set(state.mcp)].sort() }, null, 2)}\n`);
}

function coreSkillPath(name: string): string {
  return join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "..", "skills", "core", name, "SKILL.md");
}

function providerEnvironment(provider: string | undefined): Record<string, string> {
  const envName = provider === "deepseek"
    ? "DEEPSEEK_API_KEY"
    : provider === "openai"
      ? "OPENAI_API_KEY"
      : provider === "anthropic"
        ? "ANTHROPIC_API_KEY"
        : undefined;
  if (!envName) return {};
  const value = process.env[envName];
  return value === undefined ? {} : { [envName]: value };
}

function modelSummary(ctx: ExtensionCommandContext): string {
  const current = ctx.model ? `${ctx.model.provider}/${ctx.model.id}` : "none";
  const available = ctx.modelRegistry.getAll().map((model) => `${model.provider}/${model.id}`);
  return `current=${current}; available=${available.length > 0 ? available.slice(0, 12).join(", ") : "none"}`;
}

function parseModelRef(args: string): { provider: string; id: string } {
  const value = args.trim();
  const slash = value.indexOf("/");
  const parts = slash > 0 ? [value.slice(0, slash), value.slice(slash + 1)] : value.split(/\s+/, 2);
  if (parts.length !== 2 || !parts[0] || !parts[1] || !/^[A-Za-z0-9._:-]+$/.test(parts[0]) || !/^[A-Za-z0-9._:/-]+$/.test(parts[1])) {
    throw new Error("Usage: /model [provider/model]");
  }
  return { provider: parts[0], id: parts[1] };
}

function researchTaskPlan(runId: string, objective: string) {
  return {
    schemaVersion: "psyclaw/plan/v1" as const,
    runId,
    tasks: [{
      id: "agent-task-1",
      role: "researcher" as const,
      objective,
      deps: [],
      ownedPaths: ["notes"],
      parallelSafe: true,
      inputs: [],
      outputs: [],
      completionContract: { requiredArtifacts: [], requiredReceiptEffects: [], mustPassGates: [] },
    }],
    budget: { maxTurns: 4, maxWorkers: 1 },
    horizon: { strategy: "hierarchical-plan-act-reflect" as const, maxIterations: 12, reflectionEvery: 1 },
  };
}

async function recommendedItems(kind: "skills" | "mcp"): Promise<{ items: Array<Record<string, unknown>>; installPrep: Array<Record<string, unknown>> }> {
  const file = kind === "skills" ? "catalog.json" : "mcp-catalog.json";
  const moduleDir = dirname(fileURLToPath(import.meta.url));
  const candidates = [
    join(moduleDir, "..", "..", "..", "..", "skills", "recommended", file),
    join(moduleDir, "..", "..", "..", "skills", "recommended", file),
    join(moduleDir, "..", "..", "skills", "recommended", file),
    join(process.cwd(), "skills", "recommended", file),
  ];
  for (const path of candidates) {
    try {
      const value = JSON.parse(await readFile(path, "utf8")) as { items?: unknown; installPrep?: unknown };
      return {
        items: Array.isArray(value.items) ? value.items.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object")) : [],
        installPrep: Array.isArray(value.installPrep) ? value.installPrep.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object")) : [],
      };
    } catch { /* try next candidate */ }
  }
  return { items: [], installPrep: [] };
}

async function showRecommended(kind: "skills" | "mcp", args: string, ctx: ExtensionCommandContext): Promise<void> {
  const { items, installPrep } = await recommendedItems(kind);
  const state = await recommendationState(ctx.cwd);
  const stateKey: RecommendationKind = kind === "skills" ? "skill" : "mcp";
  const stateField: "skills" | "mcp" = kind === "skills" ? "skills" : "mcp";
  const action = args.trim().split(/\s+/).filter(Boolean);
  const verb = action[0];
  const id = action[1];

  if (verb && !["status", "enable", "disable", "install", "select"].includes(verb)) {
    throw new Error(`Usage: /${kind} [status|enable <id>|disable <id>|install <id>]`);
  }

  // 1. 无参数或显式 select 时，如果处于交互 TUI 模式，则启动键盘上下键选择器
  if ((!verb || verb === "select") && ctx.hasUI && typeof ctx.ui.select === "function") {
    if (!items.length) {
      ctx.ui.notify(`暂无推荐${kind === "skills" ? " Skill" : " MCP"}`, "info");
      return;
    }

    const enabled = new Set(state[stateField]);
    const optionLabels = items.map((item) => {
      const isEnabled = enabled.has(String(item.id));
      const mark = isEnabled ? "● [已启用]" : "○ [未启用]";
      const stage = item.stage ? ` [${String(item.stage)}]` : "";
      const desc = item.description ? ` — ${String(item.description)}` : "";
      return `${mark} ${String(item.name)}${stage}${desc}`;
    });

    const CANCEL_LABEL = "↩️ 取消 / 返回";
    const selected = await ctx.ui.select(
      `选择推荐 ${kind === "skills" ? "Skill" : "MCP"}（使用键盘 ↑/↓ 移动光标，Enter 确认）:`,
      [...optionLabels, CANCEL_LABEL],
    );

    if (!selected || selected === CANCEL_LABEL) return;

    const selectedIndex = optionLabels.indexOf(selected);
    if (selectedIndex < 0 || selectedIndex >= items.length) return;

    const selectedItem = items[selectedIndex];
    if (!selectedItem) return;
    const targetId = String(selectedItem.id);
    const isCurrentlyEnabled = enabled.has(targetId);

    const actionChoice = await ctx.ui.select(
      `管理推荐 ${kind === "skills" ? "Skill" : "MCP"}: ${String(selectedItem.name)} (${targetId})`,
      [
        isCurrentlyEnabled ? `🔴 禁用 (Disable ${String(selectedItem.name)})` : `🟢 启用 (Enable ${String(selectedItem.name)})`,
        `📦 查看安装预检与依赖计划 (Install Plan)`,
        `🌐 查看来源仓库 (${String(selectedItem.sourceRef ?? "无")})`,
        `↩️ 取消`,
      ],
    );

    if (!actionChoice || actionChoice === "↩️ 取消") return;

    if (actionChoice.startsWith("🔴") || actionChoice.startsWith("🟢")) {
      const nextAction = isCurrentlyEnabled ? "disable" : "enable";
      if (await ctx.ui.confirm(`${nextAction === "enable" ? "启用" : "禁用"}推荐${stateKey === "skill" ? " Skill" : " MCP"}`, `${String(selectedItem.name)} 的状态将写入当前项目配置。`)) {
        const current = new Set(state[stateField]);
        if (nextAction === "enable") current.add(targetId); else current.delete(targetId);
        state[stateField] = [...current];
        await saveRecommendationState(ctx.cwd, state);
        ctx.ui.notify(`${nextAction === "enable" ? "已启用" : "已禁用"} ${String(selectedItem.name)}（/reload 后生效；打开 /panel 可可视化管理）`, "info");
      }
      return;
    }

    if (actionChoice.startsWith("📦")) {
      const plan = installPrep.find((candidate) => candidate.id === targetId);
      ctx.ui.notify(JSON.stringify({
        schemaVersion: "psyclaw/recommendation-install/v1",
        kind: stateKey,
        id: targetId,
        name: selectedItem.name,
        sourceRef: selectedItem.sourceRef,
        plan: plan ?? null,
        status: plan?.status ?? "review-required",
        next: "安装预检与启用是两个步骤；打开 /panel 查看完整计划，安装完成后再执行启用。",
      }, null, 2), "info");
      return;
    }

    if (actionChoice.startsWith("🌐")) {
      ctx.ui.notify(`来源仓库: ${String(selectedItem.sourceRef ?? "无")}`, "info");
      return;
    }
    return;
  }

  // 2. 命令行显式参数调用
  if ((verb === "enable" || verb === "disable" || verb === "install") && !id) {
    throw new Error(`Usage: /${kind} ${verb} <id>`);
  }

  if (verb === "enable" || verb === "disable") {
    const item = items.find((candidate) => candidate.id === id);
    if (!item) throw new Error(`未找到推荐${stateKey === "skill" ? " Skill" : " MCP"}: ${id}`);
    if (!ctx.hasUI || !(await ctx.ui.confirm(`${verb === "enable" ? "启用" : "禁用"}推荐${stateKey === "skill" ? " Skill" : " MCP"}`, `${String(item.name)} 的状态将写入当前项目配置。`))) return;
    const current = new Set(state[stateField]);
    if (verb === "enable") current.add(id!); else current.delete(id!);
    state[stateField] = [...current];
    await saveRecommendationState(ctx.cwd, state);
    ctx.ui.notify(`${verb === "enable" ? "已启用" : "已禁用"} ${String(item.name)}（/reload 后生效；打开 /panel 可可视化管理）`, "info");
    return;
  }

  if (verb === "install") {
    const item = items.find((candidate) => candidate.id === id);
    const plan = installPrep.find((candidate) => candidate.id === id);
    if (!item) throw new Error(`未找到推荐${kind === "skills" ? " Skill" : " MCP"}: ${id}`);
    ctx.ui.notify(JSON.stringify({ schemaVersion: "psyclaw/recommendation-install/v1", kind: stateKey, id, name: item.name, sourceRef: item.sourceRef, plan: plan ?? null, status: plan?.status ?? "review-required", next: "安装预检与启用是两个步骤；打开 /panel 查看完整计划，安装完成后再执行启用。" }, null, 2), "info");
    return;
  }

  // 3. 非交互模式或 status 命令回退输出
  const enabled = new Set(state[stateField]);
  const lines = items.map((item) => `${enabled.has(String(item.id)) ? "[on]" : "[off]"} ${String(item.id)} — ${String(item.name)}  (/${kind} enable|disable ${String(item.id)})`);
  lines.push("", "可视化管理：打开 /panel（推荐 + 现有 Skill/MCP 的启用/停用）");
  ctx.ui.notify(lines.length ? lines.join("\n") : `暂无推荐${kind === "skills" ? " Skill" : " MCP"}`, "info");
}

type WorkflowResultLike = Awaited<ReturnType<typeof runMetaAnalysis>>;

type ToolTextContent = { type: "text"; text: string };
interface ToolResultShape { content: ToolTextContent[]; details: Record<string, unknown> }

/** Run meta-analysis with the staged progress captured into a buffer (no TTY). */
async function runMetaAnalysisStaged(root: string, target: string, nStudies: number): Promise<{ result: WorkflowResultLike; stages: string[] }> {
  const stages: string[] = [];
  const result = await runMetaAnalysis(root, {
    target,
    nStudies,
    runner: createStageRunner({ write: (line) => { stages.push(line); }, color: false }),
  });
  return { result, stages };
}

/** Shape a workflow result as a tool response the agent can reason over. */
function workflowToolResult(workflow: string, result: WorkflowResultLike, stages: string[]): ToolResultShape {
  return {
    content: [{
      type: "text",
      text: JSON.stringify({
        schemaVersion: "psyclaw/workflow-result/v1",
        workflow,
        status: result.verdict === "pass" ? "completed" : "blocked",
        verdict: result.verdict,
        runId: result.runId,
        stages,
        gates: result.gates.map((gate) => ({ id: gate.gateId, ok: gate.ok, severity: gate.severity, reason: gate.reason })),
        outputs: result.outputPaths,
        next: result.verdict === "pass"
          ? "Review the outputs before relying on them; statistics stay delegated to R (metafor) until the effect-size dataset is complete."
          : "Resolve the blocked gates (e.g. supply data/clean/effects.csv), then rerun the workflow.",
      }, null, 2),
    }],
    details: { workflow, runId: result.runId, verdict: result.verdict, outputPaths: result.outputPaths, gateCount: result.gates.length },
  };
}

function workflowToolError(workflow: string, error: unknown): ToolResultShape {
  return {
    content: [{ type: "text", text: `Workflow ${workflow} failed: ${error instanceof Error ? error.message : String(error)}` }],
    details: { workflow, status: "failed" },
  };
}

async function runMetaAnalysisTool(root: string, target: string, nStudies: number): Promise<ToolResultShape> {
  try {
    const { result, stages } = await runMetaAnalysisStaged(root, target, nStudies);
    return workflowToolResult("meta-analysis", result, stages);
  } catch (error) {
    return workflowToolError("meta-analysis", error);
  }
}

/**
 * Explicit workflow dispatch shared by the workbench's direct (`workflow`
 * parameter) and natural-language routed paths, so every workflow result has
 * the same `psyclaw/workflow-result/v1` contract.
 */
export async function runWorkflowTool(root: string, workflow: string, target?: string, nStudies?: number): Promise<ToolResultShape> {
  const id = workflow.trim();
  if (id === "meta-analysis") {
    const cleanedTarget = target?.trim();
    if (!cleanedTarget) {
      return {
        content: [{ type: "text", text: JSON.stringify({ schemaVersion: "psyclaw/workflow-result/v1", workflow: id, status: "blocked", verdict: "blocked", reason: "meta-analysis requires a target, e.g. online-learning-engagement" }, null, 2) }],
        details: { workflow: id, status: "blocked" },
      };
    }
    const count = Math.min(200, Math.max(2, Math.round(nStudies ?? 20)));
    return runMetaAnalysisTool(root, cleanedTarget, count);
  }
  const runner = WORKFLOW_RUNNERS[id as keyof typeof WORKFLOW_RUNNERS];
  if (!runner) {
    return {
      content: [{ type: "text", text: JSON.stringify({ schemaVersion: "psyclaw/workflow-result/v1", workflow: id, status: "blocked", verdict: "blocked", reason: `Unknown workflow: ${id}; expected meta-analysis, literature-review, analysis-delegation, writing-review, or expert-review` }, null, 2) }],
      details: { workflow: id, status: "blocked" },
    };
  }
  try {
    const result = await runner(root);
    return workflowToolResult(id, result, []);
  } catch (error) {
    return workflowToolError(id, error);
  }
}

/** Turn a natural-language meta-analysis request into a searchable target. */
export function cleanMetaTarget(request: string): string {
  const cleaned = request
    .replace(/请|帮我|麻烦|对|针对|进行|做|执行|开展|一下|元分析|系统综述|系统评价|meta[- ]?analysis|meta分析|效应量|森林图/gi, "")
    .replace(/\b(of|for|on|the|a|an|and|with|in|to)\b/gi, " ")
    .replace(/\s+/g, " ")
    .trim();
  return cleaned || request.trim();
}

const WORKFLOW_RUNNERS = {
  "literature-review": runLiteratureReview,
  "analysis-delegation": runAnalysisDelegation,
  "writing-review": runWritingReview,
  "expert-review": runExpertReview,
} as const;

export default function psyclawExtension(pi: ExtensionAPI): void {
  const developerCommands = process.env.PSYCLAW_DEVELOPER_COMMANDS === "1";
  const legacyTestApi = typeof pi.registerTool !== "function";
  pi.registerCommand("research", {
    description: "Bootstrap an evidence-grounded psyclaw research project",
    handler: async (args, ctx) => {
      try {
        const parsed = parseResearchArgs(args);
        const project = await bootstrapProject({ root: ctx.cwd, ...parsed });
        ctx.ui.notify(`Initialized ${project.id} (${project.paradigm})`, "info");
      } catch (error) {
        await notifyError(ctx, error);
      }
    },
  });

  if (developerCommands || legacyTestApi) pi.registerCommand("verify", {
    description: "Write a machine-readable psyclaw handoff checkpoint",
    handler: async (_args, ctx) => {
      try {
        const paths = projectPaths(ctx.cwd);
        const project = await import("node:fs/promises").then(({ readFile }) =>
          readFile(paths.project, "utf8").then((text) => asProject(JSON.parse(text))),
        );
        await writeHandoff(ctx.cwd, {
          projectId: project.id,
          runId: `run_${Date.now()}`,
          goal: project.goal,
          completed: ["project bootstrap"],
          verified: ["project.json exists"],
          blocked: ["evidence ledger has not been reviewed"],
          nextSteps: ["import a local source and create Claim-Evidence links"],
          verificationCommands: ["pnpm typecheck", "pnpm test"],
          generatedAt: new Date().toISOString(),
        });
        ctx.ui.notify("Wrote notes/HANDOFF.md and notes/handoff.json", "info");
      } catch (error) {
        await notifyError(ctx, error);
      }
    },
  });

  pi.registerCommand("brief", {
    description: "Run the offline evidence-gated research brief",
    handler: async (_args, ctx) => {
      try {
        const result = await runOfflineBrief(ctx.cwd);
        ctx.ui.notify(
          result.verdict === "pass" ? `Brief ready: ${result.briefPath}` : "Brief blocked by evidence gates",
          result.verdict === "pass" ? "info" : "warning",
        );
      } catch (error) {
        await notifyError(ctx, error);
      }
    },
  });

  if (!legacyTestApi) pi.registerCommand("skills", {
    description: "查看并启用/禁用推荐 Skill",
    handler: async (args, ctx) => {
      try { await showRecommended("skills", args, ctx); } catch (error) { await notifyError(ctx, error); }
    },
  });

  if (!legacyTestApi) pi.registerCommand("mcp", {
    description: "查看并启用/禁用推荐 MCP",
    handler: async (args, ctx) => {
      try { await showRecommended("mcp", args, ctx); } catch (error) { await notifyError(ctx, error); }
    },
  });

  if (!legacyTestApi) pi.registerCommand("install", {
    description: "查看推荐 Skill/MCP，或生成安装预检计划",
    handler: async (args, ctx) => {
      try {
        const [kind, id] = args.trim().split(/\s+/, 2);
        if (!kind) {
          const [skills, mcps] = await Promise.all([recommendedItems("skills"), recommendedItems("mcp")]);
          const skillLines = skills.items.slice(0, 8).map((item) => `Skill: ${String(item.id)} — ${String(item.name)}`);
          const mcpLines = mcps.items.slice(0, 8).map((item) => `MCP: ${String(item.id)} — ${String(item.name)}`);
          ctx.ui.notify(["推荐安装入口", "", ...skillLines, ...mcpLines, "", "安装：/install skill|mcp <id>", "管理：/skills 或 /mcp", "也可以打开 /panel 查看推荐页面"].join("\n"), "info");
          return;
        }
        if (kind !== "skill" && kind !== "mcp") throw new Error("Usage: /install skill|mcp <id>");
        if (!id) {
          await showRecommended(kind === "skill" ? "skills" : "mcp", "", ctx);
          return;
        }
        await showRecommended(kind === "skill" ? "skills" : "mcp", `install ${id}`, ctx);
      } catch (error) { await notifyError(ctx, error); }
    },
  });

  if (typeof pi.registerTool === "function") {
  pi.registerTool({
    name: "psyclaw_skill",
    label: "Research skill",
    description: "Load one trusted bundled psyclaw core skill and make its use visible to the user. Use this instead of directly reading a core SKILL.md file.",
    parameters: Type.Object({
      name: Type.String({ description: "Core skill name: research-intake, evidence-capture, citation-audit, or research-brief" }),
      purpose: Type.Optional(Type.String({ description: "Short user-facing reason for using this skill now" })),
    }),
    executionMode: "sequential",
    async execute(_toolCallId, params) {
      const name = params.name.trim();
      if (!CORE_SKILLS.has(name)) {
        return {
          content: [{ type: "text", text: `Skill not available in the trusted core pack: ${name}` }],
          details: { status: "blocked", name },
        };
      }
      try {
        const instructions = await readFile(coreSkillPath(name), "utf8");
        return {
          content: [{ type: "text", text: `正在使用 Skill：${name}${params.purpose ? `（${params.purpose}）` : ""}\n\n${instructions}` }],
          details: { status: "active", name, ...(params.purpose === undefined ? {} : { purpose: params.purpose }) },
        };
      } catch (error) {
        return {
          content: [{ type: "text", text: `Skill could not be loaded: ${error instanceof Error ? error.message : String(error)}` }],
          details: { status: "failed", name },
        };
      }
    },
  });

  pi.registerTool({
    name: "psyclaw_workbench",
    label: "Research workbench",
    description: "Primary psyclaw workbench for durable research state, evidence tracking, academic analysis/report contracts, human approval, and recoverable workflows. Infer the workflow from natural language, or pass an explicit `workflow` id to run it directly. Workflows: meta-analysis (real OpenAlex literature search, effect-size dataset contract at data/clean/effects.csv, R metafor delegation for REML / I² / Egger / forest — psyclaw never fabricates statistics), literature-review, analysis-delegation, writing-review, expert-review, institutional-fulltext. For paper/full-text requests call this first; for data analysis or academic reports route through research-intake -> evidence-capture -> citation-audit -> research-brief and record figure/document deliverables. Do not handle credentials.",
    parameters: Type.Object({
      request: Type.String({ description: "The user's research task in natural language" }),
      identifier: Type.Optional(Type.String({ description: "DOI, publisher URL, or exact paper title when relevant" })),
      workflow: Type.Optional(Type.String({ description: "Explicit workflow id to run directly: meta-analysis, literature-review, analysis-delegation, writing-review, or expert-review (otherwise inferred from the request)" })),
      target: Type.Optional(Type.String({ description: "Research target topic; required for meta-analysis (e.g. online-learning-engagement)" })),
      nStudies: Type.Optional(Type.Number({ description: "Studies to search for meta-analysis (default 20, clamped to 2-200)" })),
    }),
    executionMode: "sequential",
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      try {
        const request = params.request.trim();
        const combined = `${request} ${params.identifier ?? ""}`;
        const explicitWorkflow = params.workflow?.trim();
        if (explicitWorkflow) {
          return runWorkflowTool(ctx.cwd, explicitWorkflow, params.target, params.nStudies);
        }
        const metaAnalysisIntent = /meta[- ]?analysis|meta分析|元分析|系统综述|系统评价|效应量|forest plot|funnel|publication bias/i.test(combined);
        const publishIntent = /publish|finalize|发布|导出|定稿|投稿|export (to )?(docx|word|apa)|docx export|apa ?7/i.test(combined);
        const knowledgeMapIntent = /knowledge[ -]?map|literature[ -]?map|literature review|文献综述|知识图谱|知识地图|文献地图/i.test(combined);
        const expertReviewIntent = /expert review|peer review|reviewer|专家评审|同行评审|审稿/i.test(combined);
        const journalArtifactIntent = /journal style|journal format|publication[- ]ready|figure artifact|期刊格式|期刊风格|图表产物|投稿图表/i.test(combined);
        const fulltextIntent = !knowledgeMapIntent && !expertReviewIntent && /\b(doi|paper|article|full.?text|pdf|publisher|institution)\b|学校|机构|论文|全文|下载/i.test(combined);
        const academicReportIntent = journalArtifactIntent || /分析|数据集|统计|报告|学术|论文|word|docx|markdown|图表|可视化|csv|sav|dataset|report/i.test(combined);
        if (metaAnalysisIntent) {
          return runWorkflowTool(ctx.cwd, "meta-analysis", cleanMetaTarget(request), 20);
        }
        if (knowledgeMapIntent) {
          return runWorkflowTool(ctx.cwd, "literature-review");
        }
        if (expertReviewIntent) {
          return runWorkflowTool(ctx.cwd, "expert-review");
        }
        if (publishIntent) {
          try {
            const result = await publishManuscript(ctx.cwd, { name: "论文初稿", exportDocx: true });
            return {
              content: [{ type: "text", text: JSON.stringify({
                schemaVersion: "psyclaw/publish-result/v1",
                workflow: "publish-manuscript",
                status: "completed",
                markdownPath: result.markdownPath,
                docxPath: result.docxPath,
                markdownSha256: result.markdownSha256,
                docxSha256: result.docxSha256,
                evidenceIds: result.evidenceIds,
                next: "手稿已发布到 paper/（panel 与文档清单会自动识别）。如需再修改，直接编辑 paper/论文初稿.md 或继续在 panel 手稿编辑器修改后重新发布。",
              }, null, 2) }],
              details: { workflow: "publish-manuscript", markdownPath: result.markdownPath, docxPath: result.docxPath, evidenceIds: result.evidenceIds },
            };
          } catch (error) {
            return workflowToolError("publish-manuscript", error);
          }
        }
        if (academicReportIntent && (!fulltextIntent || journalArtifactIntent)) {
          return {
            content: [{ type: "text", text: JSON.stringify({
              schemaVersion: "psyclaw/academic-report-plan/v1",
              workflow: "academic-analysis-report",
              status: "plan-required",
              requiredSkills: ["research-intake", "evidence-capture", "citation-audit", "research-brief"],
              requiredDeliverables: ["analysis-plan", "source-backed-reference-list", "publication-ready-figures-or-reproducible-plot-script", "markdown-report", "docx-report"],
              documentExport: {
                primary: "pandoc",
                fallback: "python-docx script only after a failed Pandoc installation",
                missingDependencyAction: "detect package manager, request side-effect approval, install with bash, verify version, and write a structured receipt",
              },
              dependencyReceipt: {
                schemaVersion: "psyclaw/dependency-receipt/v1",
                requiredFields: ["dependency", "requestedVersion", "resolvedVersion", "packageManager", "command", "approvedAt", "verifiedAt", "status"],
                secretPolicy: "never record credentials, tokens, or environment values",
              },
              costNotice: {
                confirmBeforeStart: true,
                message: "文献检索与多源核验、全稿写作、DOCX 导出会消耗较多 token 与时间（长会话下缓存重读是主要费用）。开始前将告知预估 token/费用/时间，并可在更小范围或分段会话中执行。",
              },
              message: "Proceed through the four core skills and keep the report blocked until citations, figures, and document export are accounted for.",
            }, null, 2) }],
            details: { status: "plan-required", workflow: "academic-analysis-report" },
          };
        }
        if (!fulltextIntent) {
          return {
            content: [{ type: "text", text: JSON.stringify({
              schemaVersion: "psyclaw/workbench-routing/v1",
              status: "conversation-first",
              message: "This request does not yet require a durable psyclaw workflow. Continue conversationally and invoke the workbench when an artifact, evidence record, approval, or resumable run is needed.",
            }, null, 2) }],
            details: { status: "conversation-first", request },
          };
        }
        const result = await runInstitutionalFulltext(ctx.cwd, params.identifier ?? request);
        return {
          content: [{ type: "text", text: JSON.stringify({
            schemaVersion: "psyclaw/workbench-result/v1",
            workflow: "institutional-fulltext",
            status: "awaiting-human-approval",
            verdict: result.verdict,
            runId: result.runId,
            outputs: result.outputPaths,
            next: "Ask the user to complete institutional login in the visible browser and confirm the exact article before any download.",
          }, null, 2) }],
          details: { runId: result.runId, verdict: result.verdict, outputPaths: result.outputPaths, approval: "pending" },
        };
      } catch (error) {
        return {
          content: [{ type: "text", text: `Institutional full-text planning failed: ${error instanceof Error ? error.message : String(error)}` }],
          details: { status: "failed" },
        };
      }
    },
  });

  pi.registerTool({
    name: "psyclaw_cite",
    label: "Record a citation use",
    description: "Record one in-text citation while writing a manuscript: the DOI reference (verified against the archive) plus the reason it was cited and the sentence context. Call this every time a citation is added to the paper so the reference archive stays traceable — which citation appears where, why it was chosen, and whether its metadata was verified (docs/文档规范.md §8).",
    parameters: Type.Object({
      doi: Type.String({ description: "DOI of the cited reference" }),
      reason: Type.String({ description: "One-line reason this source is cited at this position (e.g. 支持：社会支持缓冲压力假说)" }),
      context: Type.String({ description: "The sentence/context in the manuscript where the citation appears" }),
      section: Type.Optional(Type.String({ description: "Manuscript section, e.g. 1 引言" })),
    }),
    executionMode: "sequential",
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      try {
        const result = await recordCitationUse(ctx.cwd, {
          doi: params.doi,
          reason: params.reason,
          context: params.context,
          ...(params.section === undefined || !params.section.trim() ? {} : { section: params.section }),
        });
        const ref = result.reference;
        return {
          content: [{ type: "text", text: JSON.stringify({
            schemaVersion: "psyclaw/citation-use/v1",
            citationId: result.record.citationId,
            doi: result.record.doi,
            verified: result.record.verified,
            reason: result.record.reason,
            referenceTitle: ref?.title ?? null,
            archived: ref !== null,
            next: result.record.verified
              ? "引用已双源核验并写入存档（含引用原因）。继续写作时保持每次引用都登记用途。"
              : "该 DOI 未能完成双源核验，引用用途已如实登记（verified=false）；请在最终交付前补核验或替换来源。",
          }, null, 2) }],
          details: { citationId: result.record.citationId, doi: result.record.doi, verified: result.record.verified },
        };
      } catch (error) {
        return {
          content: [{ type: "text", text: `记录引用失败：${error instanceof Error ? error.message : String(error)}` }],
          details: { status: "failed" },
        };
      }
    },
  });
  }

  if (developerCommands || legacyTestApi) pi.registerCommand("model", {
    description: "List or switch the active Pi model without exposing credentials",
    handler: async (args, ctx) => {
      try {
        if (!args.trim()) {
          ctx.ui.notify(modelSummary(ctx), "info");
          return;
        }
        const ref = parseModelRef(args);
        const model = ctx.modelRegistry.find(ref.provider, ref.id);
        if (!model) throw new Error(`Model not found: ${ref.provider}/${ref.id}`);
        const changed = await pi.setModel(model);
        if (!changed) throw new Error("Model authentication is not configured");
        ctx.ui.notify(`Model selected: ${ref.provider}/${ref.id}`, "info");
      } catch (error) {
        await notifyError(ctx, error);
      }
    },
  });

  if (developerCommands || legacyTestApi) pi.registerCommand("agents", {
    description: "Run a human-approved, read-only Pi research worker",
    handler: async (args, ctx) => {
      const objective = args.trim();
      if (!objective) {
        ctx.ui.notify("Usage: /agents <bounded read-only research task>", "info");
        return;
      }
      if (objective.length > 4_000) {
        ctx.ui.notify("Agent task is too long; split it into smaller bounded tasks", "error");
        return;
      }
      if (!ctx.hasUI) {
        ctx.ui.notify("Multi-agent execution requires an explicit interactive approval", "warning");
        return;
      }
      // Do not let the runner create a partial `.psyclaw/runs` tree for an
      // uninitialized or corrupt project.  `/research` (or `psyclaw init`) is
      // the explicit state-creation step.
      try {
        await readProject(ctx.cwd);
      } catch {
        ctx.ui.notify("Initialize a psyclaw project with /research before running /agents", "warning");
        return;
      }
      const approved = await ctx.ui.confirm(
        "Run read-only research worker?",
        "The worker runs in a separate Pi process with extensions, skills, context files, and mutating tools disabled.",
      );
      if (!approved) {
        ctx.ui.notify("Agent run canceled", "info");
        return;
      }
      if (activeAgentRuns.has(ctx.cwd)) {
        ctx.ui.notify("A psyclaw agent run is already active for this project", "warning");
        return;
      }
      activeAgentRuns.add(ctx.cwd);
      try {
        const runId = `pi_agent_${Date.now()}`;
        const plan = researchTaskPlan(runId, objective);
        await mkdir(join(ctx.cwd, ".psyclaw", "plans"), { recursive: true });
        await atomicWriteFile(join(ctx.cwd, ".psyclaw", "plans", `${runId}.json`), `${JSON.stringify(plan, null, 2)}\n`);
        const eventLog = new RunEventLog(ctx.cwd, runId);
        const result = await runPlanWithPi(plan, {
          cwd: ctx.cwd,
          agentDir: join(ctx.cwd, ".psyclaw", "pi-agent"),
          ...(ctx.model?.provider === undefined ? {} : { provider: ctx.model.provider }),
          ...(ctx.model?.id === undefined ? {} : { model: ctx.model.id }),
          env: providerEnvironment(ctx.model?.provider),
          root: ctx.cwd,
          pauseRequested: async () => {
            try { await import("node:fs/promises").then(({ access }) => access(join(ctx.cwd, ".psyclaw", "runs", `${runId}.pause`))); return true; }
            catch { return false; }
          },
          onEvent: async (event) => { await eventLog.append(event); },
        });
        pi.appendEntry("psyclaw:agent-run", {
          runId,
          status: result.status,
          diagnostics: result.diagnostics,
          recordedAt: new Date().toISOString(),
        });
        ctx.ui.notify(`Agent run ${result.status}: ${result.diagnostics.join("; ") || "verified"}`, result.status === "completed" ? "info" : "warning");
      } catch (error) {
        await notifyError(ctx, error);
      } finally {
        activeAgentRuns.delete(ctx.cwd);
      }
    },
  });
}
