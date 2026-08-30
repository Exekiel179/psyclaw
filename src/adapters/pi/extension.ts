import { getAgentDir, type ExtensionAPI, type ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { asProject, bootstrapProject, exportTraces, projectPaths, runOfflineBrief, runInstitutionalFulltext, runLiteratureReview, runExpertReview, runAnalysisDelegation, runWritingReview, runMetaAnalysis, createStageRunner, exportAcademicDocument, recordCitationUse, runParallelLiteratureResearch, runParallelPeerReview, writeHandoff } from "../../index.js";
import type { ResearchParadigm } from "../../core/contracts.js";
import { runPlanWithPi } from "../../orchestration/pi-executor.js";
import { atomicWriteFile } from "../../project/jsonl.js";
import { RunEventLog } from "../../panel/events.js";
import { readProject } from "../../research/ledger.js";
import { join } from "node:path";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { PROVIDER_PRESETS, saveProviderConfig } from "../../setup.js";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import {
  coreSkillNames,
  enabledRecommendedSkillPaths,
  installRecommendedSkill,
  normalizeRecommendedSkillId,
  readRecommendationState,
  readRecommendedCatalog,
  recommendedSkillTarget,
  saveRecommendationState,
  validateModelInstalledRecommendedSkill,
  type RecommendedSkillScope,
  type RecommendationState,
} from "../../skills/recommended.js";
import { SkillManagerComponent, type SkillManagerAction, type SkillManagerItem } from "../../tui/skill-manager.js";
import { RuntimeMcpRegistry } from "../../integrations/mcp-runtime.js";
import {
  ProviderPickerComponent,
  SecretInputComponent,
  type ProviderPickerItem,
  type ProviderPickerResult,
  type SecretInputResult,
} from "../../tui/provider-picker.js";

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

function parseInitArgs(args: string): { goal: string; paradigm: ResearchParadigm } {
  const trimmed = args.trim();
  const match = trimmed.match(/^--paradigm(?:=|\s+)(\S+)(?:\s+([\s\S]*))?$/i);
  if (trimmed.startsWith("--")) {
    const paradigm = match?.[1] as ResearchParadigm | undefined;
    const goal = match?.[2]?.trim();
    if (!match || !paradigm || !goal) {
      throw new Error("Usage: /init [--paradigm survey-observational] <research goal>");
    }
    if (!PARADIGMS.has(paradigm)) throw new Error(`Unsupported paradigm: ${paradigm}`);
    return { paradigm, goal };
  }
  if (!trimmed) throw new Error("Usage: /init [--paradigm survey-observational] <research goal>");
  return { paradigm: "survey-observational", goal: trimmed };
}

async function notifyError(ctx: ExtensionCommandContext, error: unknown): Promise<void> {
  ctx.ui.notify(error instanceof Error ? error.message : String(error), "error");
}

const activeAgentRuns = new Set<string>();
const CORE_SKILLS = new Set(["academic-grill", "research-intake", "evidence-capture", "citation-audit", "research-brief"]);

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

const petSettingsPath = () => join(getAgentDir(), "psyclaw-settings.json");

async function setPetPreference(enabled: boolean): Promise<void> {
  const path = petSettingsPath();
  let settings: Record<string, unknown>;
  try {
    const parsed = JSON.parse(await readFile(path, "utf8")) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Invalid PsyClaw settings file");
    settings = parsed as Record<string, unknown>;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    settings = {};
  }
  await mkdir(dirname(path), { recursive: true });
  await atomicWriteFile(path, `${JSON.stringify({ ...settings, psyclawPet: enabled }, null, 2)}\n`);
}

async function petPreference(): Promise<boolean> {
  try {
    const value = JSON.parse(await readFile(petSettingsPath(), "utf8")) as { psyclawPet?: unknown };
    return value.psyclawPet === true;
  } catch { return false; }
}

async function saveDefaultModel(provider: string, model: string): Promise<void> {
  const path = join(getAgentDir(), "settings.json");
  let settings: Record<string, unknown> = {};
  try {
    const parsed = JSON.parse(await readFile(path, "utf8")) as unknown;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) settings = parsed as Record<string, unknown>;
  } catch { /* start with a new settings file */ }
  await mkdir(dirname(path), { recursive: true });
  await atomicWriteFile(path, `${JSON.stringify({ ...settings, defaultProvider: provider, defaultModel: model }, null, 2)}\n`);
}

async function pickProviderItem(
  ctx: ExtensionCommandContext,
  title: string,
  items: ProviderPickerItem[],
): Promise<string | undefined> {
  const result = await ctx.ui.custom<ProviderPickerResult>((tui, theme, keybindings, done) =>
    new ProviderPickerComponent(title, items, tui, theme, keybindings, done));
  return result.type === "select" ? result.id : undefined;
}

async function promptProviderKey(
  ctx: ExtensionCommandContext,
  providerName: string,
  envName: string,
): Promise<string | undefined> {
  const result = await ctx.ui.custom<SecretInputResult>((tui, theme, keybindings, done) =>
    new SecretInputComponent(`配置 ${providerName}`, envName, tui, theme, keybindings, done));
  return result.type === "submit" ? result.value.trim() : undefined;
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

function academicGrillRequest(subject: string, mode: "init" | "review"): string {
  return [
    "先调用 psyclaw_skill 工具加载 PsyClaw 内置的 academic-grill Skill，然后严格遵循该 Skill 对我的学术研究进行追问。",
    subject
      ? `本次要讨论的研究主题或方案：${subject}`
      : "从当前对话、当前项目文件和已有研究状态中确定要讨论的研究主题或方案；能从这些材料查到的信息不要反问我。",
    "从最上游、影响最大的未决问题开始。每一轮只问一个问题，同时给出你的推荐答案或推荐决策及主要取舍。",
    "明确区分探索性与确证性研究，不把规划内容当作已有证据。直到关键分支已经解决或明确交由研究者决定后，再整理研究规格。",
    mode === "init"
      ? "持久化模式：init。追问完成后直接更新 academic-grill Skill 规定的全部项目文档，不再询问是否更新；写入后列出实际更新的文件。"
      : "持久化模式：review。追问完成后先展示拟更新摘要和受影响文件，并询问我是否写回；得到明确确认前不得修改项目文档。",
  ].join("\n");
}

interface ControlledRunState {
  schemaVersion: "psyclaw/controlled-run/v1";
  projectId: string;
  objective: string;
  activatedAt: string;
  status: "active";
}

async function controlledRunPath(root: string): Promise<string> {
  return join(projectPaths(root).root, ".psyclaw", "controlled-run.json");
}

async function readControlledRun(root: string): Promise<ControlledRunState | null> {
  try {
    const value = JSON.parse(await readFile(await controlledRunPath(root), "utf8")) as Partial<ControlledRunState>;
    return value.schemaVersion === "psyclaw/controlled-run/v1" && value.status === "active" && typeof value.projectId === "string" && typeof value.objective === "string" && typeof value.activatedAt === "string"
      ? value as ControlledRunState
      : null;
  } catch {
    return null;
  }
}

async function activateControlledRun(root: string, projectId: string, objective: string): Promise<ControlledRunState> {
  const state: ControlledRunState = {
    schemaVersion: "psyclaw/controlled-run/v1",
    projectId,
    objective,
    activatedAt: new Date().toISOString(),
    status: "active",
  };
  await atomicWriteFile(await controlledRunPath(root), `${JSON.stringify(state, null, 2)}\n`);
  return state;
}

function controlledRunRequest(objective: string): string {
  return [
    "PsyClaw 受控研究流程已由用户通过 /run 明确启动。先读取 .psyclaw/project.json、.psyclaw/controlled-run.json、notes/research-spec.md 和 notes/plan.md。",
    `本次目标：${objective}`,
    "实际推进当前尚未完成的研究任务；先形成或更新符合学术规范的 Markdown 分析报告，不能只描述计划。分析报告必须清楚区分数据来源、统计结果、文献证据、限制与尚未核验内容。",
    "分析报告完成后，下一步不是直接询问是否导出 DOCX，而是询问用户是否据此撰写论文。",
    "若用户选择撰写论文，再单独询问是否先进行文献调研，并说明该阶段可能花费较长时间；提示用户可以指定已启用的 Skill，或者选择 PsyClaw 默认的文献调研方式。不要在获得答复前自动开始长时调研。",
    "文献调研完成并核验后，再询问是否进行全文撰写，并询问使用哪个写作 Skill；未指定时可以建议默认方案，但仍需用户确认。只有充分证据经过核验后，才能把相关主张写入论文正文。",
    "同行评审由用户需要时另行运行 /review；不要在本轮自动审稿。/review 会再次询问使用哪个评审 Skill。最后才询问是否导出 DOCX，以及格式要求。",
    "开放获取 PDF 自动保存到 literature/pdfs/。不得绕过付费墙；没有合法开放全文时给出 https://doi.org/<DOI> 可点击链接，提示用户通过自己的权限下载到系统给出的目标路径。论文中的每篇引用都必须完成 DOI 核验并有本地 PDF，否则列出缺失项并保持正文或发布状态为 blocked。",
    "如果用户在未完成文献调研、全文写作或评审前要求导出 DOCX，允许导出当前分析报告，但必须明确标为遵循学术规范的分析报告，不得称为论文。",
  ].join("\n");
}

async function recommendedItems(kind: "skills" | "mcp"): Promise<{ items: Array<Record<string, unknown>>; externalTools: Array<Record<string, unknown>>; installPrep: Array<Record<string, unknown>> }> {
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
      const value = JSON.parse(await readFile(path, "utf8")) as { items?: unknown; externalTools?: unknown; installPrep?: unknown };
      return {
        items: Array.isArray(value.items) ? value.items.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object")) : [],
        externalTools: Array.isArray(value.externalTools) ? value.externalTools.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object")) : [],
        installPrep: Array.isArray(value.installPrep) ? value.installPrep.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object")) : [],
      };
    } catch { /* try next candidate */ }
  }
  return { items: [], externalTools: [], installPrep: [] };
}

interface SkillManagerRow {
  id: string;
  name: string;
  description: string;
  sourceRef?: string;
  installHint?: string;
  collection: boolean;
  installed: boolean;
  enabled: boolean;
  scope: RecommendedSkillScope;
  blocked: boolean;
  reason?: string;
}

interface McpManagerRow {
  id: string;
  name: string;
  description: string;
  sourceRef?: string;
  enabled: boolean;
  details: string[];
}

function skillScopeLabel(scope: RecommendedSkillScope): string {
  return scope === "user" ? "系统目录（所有项目）" : "项目目录（仅当前项目）";
}

async function skillManagerRows(root: string, state: RecommendationState): Promise<SkillManagerRow[]> {
  const catalog = await readRecommendedCatalog();
  return Promise.all(catalog.items.filter((item) => item.kind === "skill").map(async (item) => {
    const id = normalizeRecommendedSkillId(item.id);
    const scope = state.skillScopes?.[id] ?? "project";
    try {
      await validateModelInstalledRecommendedSkill(root, id, scope);
      return {
        id,
        name: item.name,
        description: String(item.description ?? ""),
        ...(item.sourceRef === undefined ? {} : { sourceRef: item.sourceRef }),
        ...(typeof item.installHint === "string" ? { installHint: item.installHint } : {}),
        collection: item.skillLayout === "collection",
        installed: true,
        enabled: state.skills.includes(id),
        scope,
        blocked: false,
      };
    } catch {
      return {
        id,
        name: item.name,
        description: String(item.description ?? ""),
        ...(item.sourceRef === undefined ? {} : { sourceRef: item.sourceRef }),
        ...(typeof item.installHint === "string" ? { installHint: item.installHint } : {}),
        collection: item.skillLayout === "collection",
        installed: false,
        enabled: false,
        scope,
        blocked: typeof item.sourceRef !== "string" || !/^https:\/\//.test(item.sourceRef),
        reason: typeof item.sourceRef === "string" && /^https:\/\//.test(item.sourceRef)
          ? "尚未安装；按 Enter 选择安装范围并交给当前模型处理"
          : "没有可交给模型检查的来源网址",
      };
    }
  }));
}

async function mcpManagerRows(state: RecommendationState): Promise<McpManagerRow[]> {
  const { items, installPrep } = await recommendedItems("mcp");
  return items.map((item) => {
    const id = String(item.id ?? "");
    const plan = installPrep.find((candidate) => candidate.id === id);
    const dependencies = Array.isArray(plan?.dependencies)
      ? plan.dependencies.filter((value): value is string => typeof value === "string")
      : [];
    return {
      id,
      name: String(item.name ?? id),
      description: String(item.description ?? ""),
      ...(typeof item.sourceRef === "string" ? { sourceRef: item.sourceRef } : {}),
      enabled: state.mcp.includes(id),
      details: [
        `传输：${String(item.transport ?? "未声明")} · 风险：${String(item.risk ?? "未声明")}`,
        `参考版本：${String(plan?.ref ?? "由模型读取来源确定")} · 许可证：${String(plan?.license ?? "由模型读取来源确定")}`,
        `可能需要：${dependencies.length > 0 ? dependencies.join(", ") : "由模型读取来源确定"}`,
      ],
    };
  });
}

function skillRowLabel(row: SkillManagerRow): string {
  const state = row.blocked ? "× 阻断" : row.enabled ? "● 已启用" : row.installed ? "○ 未启用" : "↓ 未安装";
  return `${state}  ${row.name}  [${row.id}]`;
}

async function setRecommendedSkillEnabled(root: string, requestedId: string, enabled: boolean, requestedScope?: RecommendedSkillScope): Promise<void> {
  const id = normalizeRecommendedSkillId(requestedId);
  const state = await readRecommendationState(root);
  const scope = requestedScope ?? state.skillScopes?.[id] ?? "project";
  if (enabled) await validateModelInstalledRecommendedSkill(root, id, scope);
  const current = new Set(state.skills);
  if (enabled) current.add(id); else current.delete(id);
  state.skills = [...current];
  state.skillScopes = { ...(state.skillScopes ?? {}), [id]: scope };
  await saveRecommendationState(root, state);
}

function skillManagerItems(rows: SkillManagerRow[]): SkillManagerItem[] {
  return [
    ...coreSkillNames().map((name) => ({
      id: `core:${name}`,
      name,
      description: "PsyClaw 核心研究流程 Skill。",
      status: "core" as const,
      sourceRef: "PsyClaw core",
    })),
    ...rows.map((row) => ({
      id: row.id,
      name: row.name,
      description: row.description,
      status: row.blocked ? "blocked" as const : row.enabled ? "enabled" as const : row.installed ? "disabled" as const : "missing" as const,
      ...(row.sourceRef === undefined ? {} : { sourceRef: row.sourceRef }),
      details: [`安装位置：${skillScopeLabel(row.scope)}`],
      ...(row.reason === undefined ? {} : { reason: row.reason }),
    })),
  ];
}

async function openSkillManager(ctx: ExtensionCommandContext, rows: SkillManagerRow[]): Promise<SkillManagerAction> {
  return ctx.ui.custom((tui, theme, keybindings, done) => (
    new SkillManagerComponent(skillManagerItems(rows), tui, theme, keybindings, done)
  ));
}

function mcpManagerItems(rows: McpManagerRow[]): SkillManagerItem[] {
  return rows.map((row) => ({
    id: row.id,
    name: row.name,
    description: row.description,
    status: row.enabled ? "enabled" as const : "disabled" as const,
    configuredEnabled: row.enabled,
    ...(row.sourceRef === undefined ? {} : { sourceRef: row.sourceRef }),
    details: row.details,
  }));
}

async function openMcpManager(ctx: ExtensionCommandContext, rows: McpManagerRow[]): Promise<SkillManagerAction> {
  return ctx.ui.custom((tui, theme, keybindings, done) => (
    new SkillManagerComponent(mcpManagerItems(rows), tui, theme, keybindings, done, {
      title: "MCP 管理",
      itemLabel: "MCP",
      footer: "↑/↓ 移动 · Space 开启/关闭项目配置 · Enter 交给模型安装并配置 · Esc 关闭",
      enterAction: "install",
      enabledText: "项目配置已开启；Enter 可让当前模型重新安装或修复配置",
      disabledText: "项目配置已关闭",
    })
  ));
}

async function setRecommendedMcpEnabled(root: string, id: string, enabled: boolean): Promise<void> {
  const state = await readRecommendationState(root);
  const rows = await mcpManagerRows(state);
  const row = rows.find((candidate) => candidate.id === id);
  if (!row) throw new Error(`未找到推荐 MCP: ${id}`);
  const current = new Set(state.mcp);
  if (enabled) current.add(id); else current.delete(id);
  state.mcp = [...current];
  await saveRecommendationState(root, state);
}

function modelMcpInstallTask(root: string, row: McpManagerRow, plan?: Record<string, unknown>): string {
  const suggestedCommand = typeof plan?.command === "string" ? plan.command : "请根据来源仓库的最新安装说明确定";
  const suggestedTarget = typeof plan?.target === "string" ? plan.target : `.psyclaw/mcp/${row.id}.json`;
  return [
    `安装并配置推荐 MCP：${row.name} (${row.id})。`,
    `来源网址：${row.sourceRef ?? "未提供；请停止并告知用户"}`,
    `当前项目：${root}`,
    `目录中的参考命令：${suggestedCommand}`,
    `建议的项目配置记录：${suggestedTarget}`,
    "用户已经通过 MCP 管理页明确授权本次安装。你可以直接联网、克隆或下载来源、使用所需包管理器安装依赖、执行安装命令，并写入与该 MCP 有关的项目或用户级运行配置；不要再次要求用户批准这些安装步骤。",
    "请先阅读来源仓库的实际安装与启动说明，再根据当前操作系统和宿主环境完成可运行的 stdio/HTTP MCP 配置。目录中的版本、命令和依赖只作参考，不得因为哈希、许可证、依赖或本地数据策略检查而中止安装。",
    "安装完成后实际启动一次服务器或执行等价的最小连通性检查，确认启动命令和工作目录有效。不要输出、复制或提交 API Key、令牌及其他凭据。",
    `成功后确保 .psyclaw/recommendations.json 的 mcp 列表包含 ${JSON.stringify(row.id)}，说明写入了哪些配置，并提醒用户执行 /reload。若安装命令本身失败，直接诊断并修复；只有遇到必须由用户提供的凭据或外部软件许可证时才向用户说明。`,
  ].join("\n");
}

async function queueModelMcpInstall(pi: ExtensionAPI, ctx: ExtensionCommandContext, row: McpManagerRow, plan?: Record<string, unknown>): Promise<void> {
  if (!row.sourceRef) throw new Error(`推荐 MCP 没有来源网址: ${row.id}`);
  await setRecommendedMcpEnabled(ctx.cwd, row.id, true);
  pi.sendUserMessage(modelMcpInstallTask(ctx.cwd, row, plan), ctx.isIdle() ? {} : { deliverAs: "followUp" });
  ctx.ui.notify(`已将 ${row.name} 的下载、安装和配置任务交给当前模型。模型完成并确认可启动后，请执行 /reload。`, "info");
}

async function showMcpManager(pi: ExtensionAPI, args: string, ctx: ExtensionCommandContext): Promise<void> {
  const [verb, id] = args.trim().split(/\s+/).filter(Boolean);
  if (verb && !["status", "enable", "disable", "install"].includes(verb)) {
    throw new Error("Usage: /mcp [status|enable <id>|disable <id>|install <id>]");
  }
  if ((verb === "enable" || verb === "disable" || verb === "install") && !id) {
    throw new Error(`Usage: /mcp ${verb} <id>`);
  }
  const catalog = await recommendedItems("mcp");
  if (verb === "install") {
    const rows = await mcpManagerRows(await readRecommendationState(ctx.cwd));
    const row = rows.find((candidate) => candidate.id === id);
    if (!row) throw new Error(`未找到推荐 MCP: ${id}`);
    await queueModelMcpInstall(pi, ctx, row, catalog.installPrep.find((candidate) => candidate.id === row.id));
    return;
  }
  if (verb === "enable" || verb === "disable") {
    await setRecommendedMcpEnabled(ctx.cwd, id!, verb === "enable");
    ctx.ui.notify(`MCP ${id} 的项目配置已${verb === "enable" ? "开启" : "关闭"}；重启后重新检查安装、信任和工具策略`, "info");
    return;
  }

  if (!ctx.hasUI || typeof ctx.ui.custom !== "function" || verb === "status") {
    const rows = await mcpManagerRows(await readRecommendationState(ctx.cwd));
    ctx.ui.notify(rows.map((row) => `${row.enabled ? "[on]" : "[off]"} ${row.id} — ${row.name}`).join("\n"), "info");
    return;
  }

  while (true) {
    const rows = await mcpManagerRows(await readRecommendationState(ctx.cwd));
    const action = await openMcpManager(ctx, rows);
    if (action.type === "close") return;
    const row = rows.find((candidate) => candidate.id === action.id);
    if (!row) continue;
    if (action.type === "install") {
      await queueModelMcpInstall(pi, ctx, row, catalog.installPrep.find((candidate) => candidate.id === row.id));
      return;
    }
    if (action.type === "toggle") {
      await setRecommendedMcpEnabled(ctx.cwd, row.id, action.enabled);
      ctx.ui.notify(`${row.name} 的项目配置已${action.enabled ? "开启" : "关闭"}；重启后重新检查运行时可用性`, "info");
    }
  }
}

function modelSkillInstallTask(root: string, row: SkillManagerRow, scope: RecommendedSkillScope): string {
  const target = recommendedSkillTarget(root, row.id, scope);
  return [
    `安装推荐 Skill：${row.name} (${row.id})。`,
    `来源网址：${row.sourceRef}`,
    ...(row.installHint ? [`仓库入口提示：${row.installHint}`] : []),
    `安装位置：${skillScopeLabel(scope)}。`,
    `唯一允许的最终目标目录：${target}`,
    "用户已通过 Skill 管理页授权本次安装。请使用当前会话的联网、文件和命令工具读取来源仓库，并直接下载、安装所需依赖和完成 Skill 安装；不要再次要求安装权限。不要写入其他 Skill 目录，不要修改 data/raw、.git 或研究产物。",
    row.collection
      ? "这是多 Skill 套件：目标目录自身无需 SKILL.md，但其子目录必须包含一个或多个有效 SKILL.md。保留套件内共享目录和相对路径，不得包含 .git、符号链接或凭据。"
      : "目标目录最终必须直接包含有效 SKILL.md（YAML frontmatter 至少包含 name 和 description），不得包含 .git、符号链接、凭据或二进制大文件。",
    "如果仓库包含多个 Skill，只安装与此推荐项相符的部分；如果它不是 Skill 或无法合理适配，停止并说明原因，不要伪造 SKILL.md。",
    "安装完成后检查目标目录结构，并提醒用户执行 /skills 启用该项，再执行 /reload。",
  ].join("\n");
}

async function chooseSkillScope(ctx: ExtensionCommandContext): Promise<RecommendedSkillScope | undefined> {
  const projectLabel = skillScopeLabel("project");
  const systemLabel = skillScopeLabel("user");
  const selected = await ctx.ui.select("选择 Skill 安装位置", [projectLabel, systemLabel]);
  if (selected === projectLabel) return "project";
  if (selected === systemLabel) return "user";
  return undefined;
}

async function queueModelSkillInstall(pi: ExtensionAPI, ctx: ExtensionCommandContext, row: SkillManagerRow): Promise<void> {
  if (!row.sourceRef) throw new Error(`推荐 Skill 没有来源网址: ${row.id}`);
  const scope = await chooseSkillScope(ctx);
  if (!scope) return;
  const approved = await ctx.ui.confirm(
    "交给当前模型安装 Skill？",
    `${row.name}\n来源：${row.sourceRef}\n安装位置：${skillScopeLabel(scope)}\n目标目录：${recommendedSkillTarget(ctx.cwd, row.id, scope)}\n模型将检查仓库并使用文件与命令工具完成安装。`,
  );
  if (!approved) return;
  const state = await readRecommendationState(ctx.cwd);
  state.skillScopes = { ...(state.skillScopes ?? {}), [row.id]: scope };
  await saveRecommendationState(ctx.cwd, state);
  pi.sendUserMessage(modelSkillInstallTask(ctx.cwd, row, scope), ctx.isIdle() ? {} : { deliverAs: "followUp" });
  ctx.ui.notify(`已将 ${row.name} 的安装任务交给当前模型，目标为${skillScopeLabel(scope)}。安装完成后请在 /skills 中启用，再执行 /reload。`, "info");
}

async function showSkillManager(pi: ExtensionAPI, args: string, ctx: ExtensionCommandContext): Promise<void> {
  const action = args.trim().split(/\s+/).filter(Boolean);
  const verb = action[0];
  const id = action[1];
  if (verb && !["status", "enable", "disable", "install"].includes(verb)) {
    throw new Error("Usage: /skills [status|enable <id>|disable <id>|install <id>]");
  }
  if ((verb === "enable" || verb === "disable" || verb === "install") && !id) {
    throw new Error(`Usage: /skills ${verb} <id>`);
  }
  if (verb === "install") {
    const row = (await skillManagerRows(ctx.cwd, await readRecommendationState(ctx.cwd))).find((candidate) => candidate.id === normalizeRecommendedSkillId(id!));
    if (!row) throw new Error(`未找到推荐 Skill: ${id}`);
    await queueModelSkillInstall(pi, ctx, row);
    return;
  }
  if (verb === "enable" || verb === "disable") {
    await setRecommendedSkillEnabled(ctx.cwd, id!, verb === "enable");
    ctx.ui.notify(`${verb === "enable" ? "已启用" : "已停用"} ${normalizeRecommendedSkillId(id!)}。请运行 /reload 重新加载。`, "info");
    return;
  }

  if (!ctx.hasUI || typeof ctx.ui.custom !== "function" || verb === "status") {
    const state = await readRecommendationState(ctx.cwd);
    const rows = await skillManagerRows(ctx.cwd, state);
    const lines = [
      ...coreSkillNames().map((name) => `● 内置  ${name}`),
      ...rows.map((row) => `${skillRowLabel(row)}${row.reason ? ` — ${row.reason}` : ""}`),
    ];
    ctx.ui.notify(lines.join("\n"), "info");
    return;
  }

  while (true) {
    const state = await readRecommendationState(ctx.cwd);
    const rows = await skillManagerRows(ctx.cwd, state);
    const action = await openSkillManager(ctx, rows);
    if (action.type === "close") return;
    const row = rows.find((candidate) => candidate.id === action.id);
    if (!row) continue;
    if (action.type === "install") {
      await queueModelSkillInstall(pi, ctx, row);
      return;
    }
    if (action.type === "toggle") {
      await setRecommendedSkillEnabled(ctx.cwd, row.id, action.enabled);
      ctx.ui.notify(`已${action.enabled ? "启用" : "停用"} ${row.name}。请运行 /reload 重新加载。`, "info");
    }
  }
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
  const runtimeMcps = new RuntimeMcpRegistry();
  if (!legacyTestApi && typeof pi.on === "function") pi.on("resources_discover", async (event, ctx) => {
    const enabled = await enabledRecommendedSkillPaths(event.cwd);
    for (const warning of enabled.warnings) ctx.ui.notify(`PsyClaw Skill: ${warning}`, "warning");
    const localSkillPaths = [
      join(homedir(), ".claude", "skills"),
      join(homedir(), ".claude", "commands"),
      join(homedir(), ".codex", "skills"),
      join(homedir(), ".agents", "skills"),
      join(event.cwd, ".claude", "skills"),
      join(event.cwd, ".claude", "commands"),
      join(event.cwd, ".codex", "skills"),
      join(event.cwd, ".agents", "skills"),
    ];
    return { skillPaths: [...enabled.paths, ...localSkillPaths] };
  });
  if (!legacyTestApi && typeof pi.on === "function") pi.on("session_shutdown", () => runtimeMcps.close());
  pi.registerCommand("init", {
    description: "初始化可追溯的研究项目",
    handler: async (args, ctx) => {
      try {
        const parsed = parseInitArgs(args);
        const project = await bootstrapProject({ root: ctx.cwd, ...parsed });
        if (typeof pi.sendUserMessage === "function") {
          pi.sendUserMessage(academicGrillRequest(project.goal, "init"), ctx.isIdle() ? {} : { deliverAs: "followUp" });
          ctx.ui.notify(`研究项目已初始化：${project.id}（${project.paradigm}）。现在开始学术追问；准备好后使用 /run 启动受控研究流程。`, "info");
        } else {
          ctx.ui.notify(`研究项目已初始化：${project.id}（${project.paradigm}）。使用 /run 启动受控研究流程。`, "info");
        }
      } catch (error) {
        await notifyError(ctx, error);
      }
    },
  });

  if (!legacyTestApi) pi.registerCommand("run", {
    description: "在 /init 后启动受控研究流程",
    handler: async (args, ctx) => {
      try {
        const project = await readProject(ctx.cwd);
        const objective = args.trim() || project.goal;
        await activateControlledRun(ctx.cwd, project.id, objective);
        pi.appendEntry("psyclaw:controlled-run", { projectId: project.id, objective, activatedAt: new Date().toISOString() });
        pi.sendUserMessage(controlledRunRequest(objective), ctx.isIdle() ? {} : { deliverAs: "followUp" });
        ctx.ui.notify("受控研究流程已启动。分析完成后会先询问是否撰写论文；不会直接进入 DOCX 导出。", "info");
      } catch {
        ctx.ui.notify("请先使用 /init 初始化研究项目；未运行 /init 和 /run 时保持普通对话模式。", "warning");
      }
    },
  });

  if (developerCommands || legacyTestApi) pi.registerCommand("verify", {
    description: "写入机器可读的交接检查点",
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
    description: "运行离线证据门控研究简报",
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

  if (!legacyTestApi) pi.registerCommand("grill", {
    description: "逐题追问并压力测试学术研究方案",
    handler: async (args, ctx) => {
      const subject = args.trim();
      pi.sendUserMessage(academicGrillRequest(subject, "review"), ctx.isIdle() ? {} : { deliverAs: "followUp" });
      ctx.ui.notify("已启动学术追问。完成后会先展示文档更新建议，并询问是否写回。", "info");
    },
  });

  if (!legacyTestApi) pi.registerCommand("review", {
    description: "并发运行多角色模拟同行评审",
    handler: async (_args, ctx) => {
      if (activeAgentRuns.has(ctx.cwd)) {
        ctx.ui.notify("当前项目已有一个多智能体任务正在运行", "warning");
        return;
      }
      try {
        const project = await readProject(ctx.cwd);
        if (!(await readControlledRun(ctx.cwd))) {
          ctx.ui.notify("请先使用 /run 启动受控研究流程；普通对话模式不会自动执行同行评审。", "warning");
          return;
        }
        const reviewSkill = ctx.hasUI
          ? await ctx.ui.input("同行评审使用哪个 Skill？", "留空使用 PsyClaw 默认多角色模拟评审")
          : undefined;
        if (reviewSkill === undefined && ctx.hasUI) {
          ctx.ui.notify("已取消同行评审", "info");
          return;
        }
        activeAgentRuns.add(ctx.cwd);
        ctx.ui.notify(`正在使用${reviewSkill?.trim() ? ` Skill“${reviewSkill.trim()}”辅助的` : "默认"} 4 角色并发模拟评审；不会自动改稿。`, "info");
        const result = await runParallelPeerReview({
          root: ctx.cwd,
          project,
          ...(ctx.model?.provider === undefined ? {} : { provider: ctx.model.provider }),
          ...(ctx.model?.id === undefined ? {} : { model: ctx.model.id }),
          env: providerEnvironment(ctx.model?.provider),
          ...(reviewSkill?.trim() ? { skillGuidance: reviewSkill.trim() } : {}),
          onEvent: async (event) => { await new RunEventLog(ctx.cwd, event.runId).append(event); },
        });
        pi.appendEntry("psyclaw:multi-agent-review", {
          runId: result.runId,
          status: result.status,
          outputPath: result.outputPath,
          adoption: "pending-human-decision",
          recordedAt: new Date().toISOString(),
        });
        ctx.ui.notify(
          `模拟审稿${result.status === "completed" ? "已完成" : "未完整完成"}：${result.outputPath}。审稿意见仅供研究者决定是否采纳。`,
          result.status === "completed" ? "info" : "warning",
        );
      } catch (error) {
        await notifyError(ctx, error);
      } finally {
        activeAgentRuns.delete(ctx.cwd);
      }
    },
  });

  if (!legacyTestApi) pi.registerCommand("loop", {
    description: "按计划循环推进当前研究阶段",
    handler: async (args, ctx) => {
      const requested = args.trim();
      if (requested.toLowerCase() === "stop") {
        if (ctx.isIdle()) ctx.ui.notify("当前没有正在运行的研究循环", "info");
        else {
          ctx.abort();
          ctx.ui.notify("已请求停止当前研究循环", "warning");
        }
        return;
      }
      let project: Awaited<ReturnType<typeof readProject>>;
      try {
        project = await readProject(ctx.cwd);
      } catch {
        ctx.ui.notify("请先使用 /init 初始化研究项目，再运行 /loop", "warning");
        return;
      }
      const objective = requested || project.goal;
      const request = [
        "运行一个有边界的 PsyClaw 研究循环，采用计划、执行、检查、修正的顺序推进当前研究阶段。",
        `本轮目标：${objective}`,
        "开始前读取 .psyclaw/project.json、notes/goal.md 和 notes/plan.md；如果当前对话或项目中存在经研究者确认的 /grill 研究规格，以该规格细化初始计划，但不得违反系统规则、AGENTS.md 或研究门禁。",
        "先识别当前最高优先级且依赖已满足的一个任务，再使用可用工具实际推进。不要只描述准备做什么。普通项目文件写入限于该任务所需范围；原始数据、凭据、外部发布、破坏性操作和方法学关键变更仍需明确批准。",
        "每完成一个实质步骤就检查产物、证据和计划是否一致。遇到缺失证据、研究者决策、权限边界、不可恢复错误或当前阶段已经完成时立即停止，不得为了继续循环而虚构输入或结论。",
        "本次最多推进一个可验收的研究阶段。结束时简要报告已完成、已核验、阻塞、计划变化和下一步；规划内容不得表述为已有研究证据。",
      ].join("\n");
      pi.sendUserMessage(request, ctx.isIdle() ? {} : { deliverAs: "followUp" });
      ctx.ui.notify("已启动有界研究循环；使用 /loop stop 可请求中止", "info");
    },
  });

  if (!legacyTestApi) pi.registerCommand("skills", {
    description: "打开 Skill 安装与启用管理页",
    handler: async (args, ctx) => {
      try { await showSkillManager(pi, args, ctx); } catch (error) { await notifyError(ctx, error); }
    },
  });

  if (!legacyTestApi) pi.registerCommand("skill", {
    description: "调用任意已加载 Skill（/skill <name> [任务]）",
    handler: async (args, ctx) => {
      const [name, ...rest] = args.trim().split(/\s+/).filter(Boolean);
      if (!name || !/^[a-z0-9-]+$/.test(name)) {
        ctx.ui.notify("Usage: /skill <name> [task]；也可直接使用 /skill:<name>", "info");
        return;
      }
      pi.sendUserMessage(`/skill:${name}${rest.length ? ` ${rest.join(" ")}` : ""}`, ctx.isIdle() ? {} : { deliverAs: "followUp" });
    },
  });

  if (!legacyTestApi) pi.registerCommand("mcp", {
    description: "打开 MCP 安装与配置管理页",
    handler: async (args, ctx) => {
      try { await showMcpManager(pi, args, ctx); } catch (error) { await notifyError(ctx, error); }
    },
  });

  if (!legacyTestApi) pi.registerCommand("install", {
    description: "查看推荐 Skill/MCP，或交给当前模型安装",
    handler: async (args, ctx) => {
      try {
        const [kind, id] = args.trim().split(/\s+/, 2);
        if (!kind) {
          const [skills, mcps] = await Promise.all([recommendedItems("skills"), recommendedItems("mcp")]);
          const skillLines = skills.items.slice(0, 8).map((item) => `Skill: ${String(item.id)} — ${String(item.name)}`);
          const mcpLines = mcps.items.slice(0, 8).map((item) => `MCP: ${String(item.id)} — ${String(item.name)}`);
          const toolLines = skills.externalTools.slice(0, 8).map((item) => `外部工具: ${String(item.name)} — ${String(item.sourceRef ?? "请查看项目文档")}`);
          ctx.ui.notify(["推荐安装入口", "", ...skillLines, ...mcpLines, "", ...toolLines, "", "安装：/install skill|mcp <id>", "管理：/skills 或 /mcp", "外部工具不通过 Skill 安装器安装", "也可以打开 /panel 查看推荐页面"].join("\n"), "info");
          return;
        }
        if (kind !== "skill" && kind !== "mcp") throw new Error("Usage: /install skill|mcp <id>");
        if (!id) {
          if (kind === "skill") await showSkillManager(pi, "", ctx);
          else await showMcpManager(pi, "", ctx);
          return;
        }
        if (kind === "skill") await showSkillManager(pi, `install ${id}`, ctx);
        else await showMcpManager(pi, `install ${id}`, ctx);
      } catch (error) { await notifyError(ctx, error); }
    },
  });

  if (!legacyTestApi) pi.registerCommand("provider", {
    description: "查看或切换模型 Provider",
    handler: async (args, ctx) => {
      try {
        let requested = args.trim();
        const providers = new Map<string, ReturnType<typeof ctx.modelRegistry.getAll>>();
        for (const model of ctx.modelRegistry.getAll()) {
          const list = providers.get(model.provider) ?? [];
          list.push(model);
          providers.set(model.provider, list);
        }
        if (!requested) {
          const current = ctx.model?.provider ?? "none";
          const available = new Map(PROVIDER_PRESETS.filter((preset) => preset.models.length > 0).map((preset) => [preset.id, preset]));
          for (const id of providers.keys()) if (!available.has(id)) available.set(id, {
            id,
            name: ctx.modelRegistry.getProviderDisplayName(id),
            baseUrl: "",
            api: "openai-completions",
            apiKeyEnv: `${id.toUpperCase().replace(/[^A-Z0-9]/g, "_")}_API_KEY`,
            models: [],
          });
          if (!ctx.hasUI || typeof ctx.ui.custom !== "function") {
            const lines = [...available].map(([id, preset]) => `${id}${id === current ? " *" : ""} — ${preset.name}`);
            ctx.ui.notify([`当前 Provider: ${current}`, ...lines, "", "切换：/provider <id>"].join("\n"), "info");
            return;
          }
          const selectedProvider = await pickProviderItem(ctx, "选择模型 Provider", [...available].map(([id, preset]) => ({
            id,
            label: preset.name,
            description: `${id} · ${providers.get(id)?.length ?? preset.models.length} 个模型`,
            current: id === current,
          })));
          if (!selectedProvider) return;
          requested = selectedProvider;
        }
        if (!/^[A-Za-z0-9._:-]+$/.test(requested)) throw new Error("Usage: /provider <provider-id>");
        const preset = PROVIDER_PRESETS.find((item) => item.id === requested);
        let models = providers.get(requested) ?? [];
        const modelChoices = models.length > 0 ? models : (preset?.models ?? []);
        if (modelChoices.length === 0) throw new Error(`Unknown provider or no configured models: ${requested}`);
        let selectedId = modelChoices[0]!.id;
        if (modelChoices.length > 1) {
          if (!ctx.hasUI || typeof ctx.ui.custom !== "function") throw new Error(`Provider ${requested} has multiple models; use /model ${requested}/<model-id>`);
          const choice = await pickProviderItem(ctx, `选择 ${preset?.name ?? requested} 模型`, modelChoices.map((model) => ({
            id: model.id,
            label: "name" in model && typeof model.name === "string" ? model.name : model.id,
            description: model.id,
            current: ctx.model?.provider === requested && ctx.model.id === model.id,
          })));
          if (!choice) return;
          selectedId = choice;
        }
        if (preset && ctx.hasUI && typeof ctx.ui.custom === "function") {
          const key = await promptProviderKey(ctx, preset.name, preset.apiKeyEnv);
          if (key === undefined) return;
          await saveProviderConfig({ ...preset, ...(key ? { apiKey: key } : {}) });
          await ctx.modelRegistry.refresh();
          models = ctx.modelRegistry.getAll().filter((model) => model.provider === requested);
        }
        const selected = models.find((model) => model.id === selectedId);
        if (!selected) throw new Error(`No model selected for provider: ${requested}`);
        const changed = await pi.setModel(selected);
        if (!changed) throw new Error(`未找到 ${requested} 的可用凭据；请重新运行 /provider 并输入 API Key`);
        await saveDefaultModel(requested, selected.id);
        ctx.ui.notify(`已切换并设为默认模型：${requested}/${selected.id}`, "info");
      } catch (error) { await notifyError(ctx, error); }
    },
  });

  if (!legacyTestApi) pi.registerCommand("pet", {
    description: "开启或关闭启动横幅宠物",
    handler: async (args, ctx) => {
      const action = args.trim().toLowerCase() || "status";
      if (action === "status") {
        ctx.ui.notify(`启动横幅宠物：${await petPreference() ? "已开启" : "已关闭（默认）"}`, "info");
        return;
      }
      if (action !== "on" && action !== "off") {
        ctx.ui.notify("Usage: /pet on|off|status", "error");
        return;
      }
      await setPetPreference(action === "on");
      ctx.ui.notify(`启动横幅宠物已${action === "on" ? "开启" : "关闭"}，下次启动生效`, "info");
    },
  });

  const traceCommand = {
    description: "导出脱敏使用路径，供 Langfuse 或 LangSmith 分析",
    handler: async (args: string, ctx: ExtensionCommandContext) => {
      try {
        if (args.trim()) throw new Error("Usage: /trace");
        const result = await exportTraces({ root: ctx.cwd });
        ctx.ui.notify([
          "使用路径已导出（未上传）",
          `文件：${result.output}`,
          `轨迹：${result.traces}`,
          `步骤：${result.spans}`,
          "隐私：不含对话正文、工具参数、原始 ID 或绝对路径",
        ].join("\n"), "info");
      } catch (error) {
        await notifyError(ctx, error);
      }
    },
  };
  pi.registerCommand("trace", traceCommand);

  if (typeof pi.registerTool === "function") {
  pi.registerTool({
    name: "psyclaw_mcp",
    label: "MCP tools",
    description: "List and call tools from MCP servers enabled in .psyclaw/mcp/*.json. Use action=list first, then action=call with the exact server and tool names.",
    promptSnippet: "Discover and call enabled MCP servers such as MNE through PsyClaw.",
    parameters: Type.Object({
      action: Type.Union([Type.Literal("list"), Type.Literal("call")]),
      server: Type.Optional(Type.String({ description: "Configured MCP server id, for example mne-mcp" })),
      tool: Type.Optional(Type.String({ description: "Exact MCP tool name returned by action=list" })),
      input: Type.Optional(Type.Record(Type.String(), Type.Unknown())),
    }),
    executionMode: "sequential",
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      try {
        if (params.action === "list") {
          const servers = await runtimeMcps.list(ctx.cwd, params.server);
          return { content: [{ type: "text", text: JSON.stringify({ servers }, null, 2) }], details: { action: "list", servers: servers.length } };
        }
        if (!params.server || !params.tool) throw new Error("server and tool are required for action=call");
        const result = await runtimeMcps.call(ctx.cwd, params.server, params.tool, params.input ?? {});
        return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }], details: { action: "call", server: params.server, tool: params.tool } };
      } catch (error) {
        return {
          content: [{ type: "text", text: `MCP call failed: ${error instanceof Error ? error.message : String(error)}` }],
          details: { action: params.action, status: "failed" },
          isError: true,
        };
      }
    },
  });

  pi.registerTool({
    name: "psyclaw_skill",
    label: "Research skill",
    description: "Load one trusted bundled psyclaw core skill and make its use visible to the user. Use this instead of directly reading a core SKILL.md file.",
    parameters: Type.Object({
      name: Type.String({ description: "Core skill name: academic-grill, research-intake, evidence-capture, citation-audit, or research-brief" }),
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
        if (!(await readControlledRun(ctx.cwd))) {
          return {
            content: [{ type: "text", text: JSON.stringify({
              schemaVersion: "psyclaw/workbench-routing/v1",
              status: "general-mode",
              message: "PsyClaw controlled research mode is inactive. Continue as a normal conversational agent; do not impose research workflow gates. The user can run /init and then /run when they want the controlled workflow.",
            }, null, 2) }],
            details: { status: "general-mode", request },
          };
        }
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
            const result = await exportAcademicDocument(ctx.cwd);
            return {
              content: [{ type: "text", text: JSON.stringify({
                schemaVersion: "psyclaw/publish-result/v1",
                workflow: result.kind === "manuscript" ? "publish-manuscript" : "export-analysis-report",
                status: "completed",
                markdownPath: result.markdownPath,
                docxPath: result.docxPath,
                docxSha256: result.docxSha256,
                classification: result.kind,
                ...(result.kind === "analysis-report" ? { notice: result.notice } : {}),
              }, null, 2) }],
              details: { workflow: result.kind === "manuscript" ? "publish-manuscript" : "export-analysis-report", markdownPath: result.markdownPath, docxPath: result.docxPath },
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
        if (!(await readControlledRun(ctx.cwd))) {
          return {
            content: [{ type: "text", text: "当前是普通对话模式；请先运行 /init，再运行 /run，之后才会启用引用归档与论文证据门禁。" }],
            details: { status: "general-mode" },
          };
        }
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
            fulltext: result.fulltext,
            next: result.record.verified && result.fulltext?.status === "downloaded"
              ? `引用已双源核验，开放全文已保存到 ${result.fulltext.localPath}。`
              : result.fulltext?.status === "manual-download-required"
                ? `该引用的题录已登记，但未找到开放 PDF。请通过 ${result.fulltext.doiUrl} 使用你的合法访问权限下载，并保存到 ${result.fulltext.localPath}；完成前不得将依赖全文的主张写入正文。`
                : "该 DOI 或全文未能完成核验；请在最终交付前补核验或替换来源。",
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
    description: "列出或切换当前模型",
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
    description: "运行经批准的只读研究 Agent",
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
      // uninitialized or corrupt project. `/init` is
      // the explicit state-creation step.
      try {
        await readProject(ctx.cwd);
      } catch {
        ctx.ui.notify("请先使用 /init 初始化研究项目，再运行 /agents", "warning");
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
