import { getAgentDir, type ExtensionAPI, type ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { appendApproval, approvalInputDigest, approvePrimaryDocument, asProject, bootstrapProject, DEFAULT_RUN_APPROVAL_NODES, exportTraces, PRIMARY_PLAN_DOCUMENTS, primaryPlanApprovalStatus, projectPaths, runOfflineBrief, runInstitutionalFulltext, runLiteratureReview, runExpertReview, runAnalysisDelegation, runWritingReview, runMetaAnalysis, createStageRunner, exportAcademicDocument, recordCitationUse, runParallelLiteratureResearch, runParallelPeerReview, writeHandoff } from "../../index.js";
import type { ResearchParadigm } from "../../core/contracts.js";
import { runPlanWithPi } from "../../orchestration/pi-executor.js";
import { atomicWriteFile } from "../../project/jsonl.js";
import { RunEventLog } from "../../panel/events.js";
import { readProject } from "../../research/ledger.js";
import { join } from "node:path";
import { lstat, mkdir, readFile, writeFile } from "node:fs/promises";
import { PROVIDER_PRESETS, providerCredentialSource, saveProviderConfig } from "../../setup.js";
import { dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
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
import {
  enabledLocalSkillPaths,
  enabledLocalPromptPaths,
  readUserSkillState,
  scanLocalSkills,
  setLocalSkillEnabled,
  setLocalSkillsEnabled,
  skillNamesInPaths,
  installLocalSkill,
  userSkillId,
} from "../../skills/user-skills.js";
import {
  RuntimeMcpRegistry,
  setUserMcpConfigEnabled,
  type UserMcpConfigEntry,
} from "../../integrations/mcp-runtime.js";
import {
  SecretInputComponent,
  type ProviderPickerItem,
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

async function runPluginCommand(args: string[]): Promise<void> {
  const entry = fileURLToPath(import.meta.resolve("@earendil-works/pi-coding-agent"));
  const modulePath = join(dirname(entry), "package-manager-cli.js");
  const { handlePackageCommand } = await import(pathToFileURL(modulePath).href) as {
    handlePackageCommand(commandArgs: string[]): Promise<boolean>;
  };
  const handled = await handlePackageCommand(args);
  if (!handled) throw new Error(`不支持的 Plugin 操作：${args[0] ?? ""}`);
}

const activeAgentRuns = new Set<string>();
const pendingInitApprovals = new Set<string>();
const activeApprovalDialogs = new Set<string>();
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
  const labels = items.map((item) => `${item.current ? "* " : ""}${item.label} (${item.id})`);
  const selected = await ctx.ui.select(title, labels, { timeout: 60_000 });
  const index = selected === undefined ? -1 : labels.indexOf(selected);
  return index < 0 ? undefined : items[index]!.id;
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
      ? "持久化模式：init。追问完成后直接更新 academic-grill Skill 规定的全部项目文档，不再询问是否更新；写入后列出实际更新的文件，并把 notes/research-spec.md 与 notes/plan.md 的 Status 统一写为 awaiting-human-approval。"
      : "持久化模式：review。追问完成后先展示拟更新摘要和受影响文件，并询问我是否写回；得到明确确认前不得修改项目文档。",
  ].join("\n");
}

interface ControlledRunState {
  schemaVersion: "psyclaw/controlled-run/v1";
  runId: string;
  projectId: string;
  objective: string;
  selectedSkills: string[];
  mode: "human" | "auto";
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
      ? { ...value, runId: typeof value.runId === "string" ? value.runId : `legacy_${value.projectId}`, mode: value.mode === "auto" ? "auto" : "human", selectedSkills: Array.isArray(value.selectedSkills) ? value.selectedSkills.filter((item): item is string => typeof item === "string") : [] } as ControlledRunState
      : null;
  } catch {
    return null;
  }
}

async function activateControlledRun(root: string, runId: string, projectId: string, objective: string, selectedSkills: string[], mode: "human" | "auto"): Promise<ControlledRunState> {
  const state: ControlledRunState = {
    schemaVersion: "psyclaw/controlled-run/v1",
    runId,
    projectId,
    objective,
    selectedSkills: [...new Set(selectedSkills)],
    mode,
    activatedAt: new Date().toISOString(),
    status: "active",
  };
  await atomicWriteFile(await controlledRunPath(root), `${JSON.stringify(state, null, 2)}\n`);
  return state;
}

function controlledRunRequest(objective: string, selectedSkills: string[], mode: "human" | "auto"): string {
  return [
    `PsyClaw ${mode === "auto" ? "自动" : "人在环路"}研究流程已由用户通过 /run 明确启动。先读取 .psyclaw/project.json、.psyclaw/controlled-run.json、.psyclaw/approvals.jsonl、notes/research-spec.md 和 notes/plan.md。`,
    `本次目标：${objective}`,
    selectedSkills.length > 0
      ? `本次运行由用户选择的优化 Skill：${selectedSkills.join(", ")}。在相关任务中优先加载并遵循这些 Skill；同名 Skill 只加载一次。`
      : "本次运行未指定额外 Skill，使用 PsyClaw 默认研究流程。不要删除、停用或改写已安装的其他 Skill。",
    mode === "auto"
      ? "自动模式：计划内普通步骤连续推进，不再逐项询问；运行时会自动记录审批。原始数据、凭据、破坏性命令、伦理决定、未经核验的事实与外部发布仍必须停止并请求用户决定。"
      : "人在环路模式：每个有副作用或关键方法决策的步骤都必须通过交互审批；拒绝或超时立即停止，不得绕过审批。",
    "实际推进当前尚未完成的研究任务；先形成或更新符合学术规范的 Markdown 分析报告，不能只描述计划。分析报告必须清楚区分数据来源、统计结果、文献证据、限制与尚未核验内容。",
    "分析报告完成后，下一步不是直接询问是否导出 DOCX，而是询问用户是否据此撰写论文。",
    "若用户选择撰写论文，再单独询问是否先进行文献调研，并说明该阶段可能花费较长时间；提示用户可以指定已启用的 Skill，或者选择 PsyClaw 默认的文献调研方式。不要在获得答复前自动开始长时调研。",
    "文献调研完成并核验后，再询问是否进行全文撰写，并询问使用哪个写作 Skill；未指定时可以建议默认方案，但仍需用户确认。只有充分证据经过核验后，才能把相关主张写入论文正文。",
    "同行评审由用户需要时另行运行 /review；不要在本轮自动审稿。/review 会再次询问使用哪个评审 Skill。最后才询问是否导出 DOCX，以及格式要求。",
    "开放获取 PDF 自动保存到 literature/pdfs/。不得绕过付费墙；没有合法开放全文时给出 https://doi.org/<DOI> 可点击链接，提示用户通过自己的权限下载到系统给出的目标路径。论文中的每篇引用都必须完成 DOI 核验并有本地 PDF，否则列出缺失项并保持正文或发布状态为 blocked。",
    "如果用户在未完成文献调研、全文写作或评审前要求导出 DOCX，允许导出当前分析报告，但必须明确标为遵循学术规范的分析报告，不得称为论文。",
  ].join("\n");
}

interface RunArguments {
  objective: string;
  requestedSkills?: string[];
  mode: "human" | "auto";
}

function parseRunArgs(args: string): RunArguments {
  const value = args.trim();
  const auto = value === "auto" || value.startsWith("auto ");
  const rest = auto ? value.slice(4).trim() : value;
  if (!rest.startsWith("--skills")) return { objective: rest, mode: auto ? "auto" : "human" };
  const match = rest.match(/^--skills(?:=|\s+)([^\s]+)(?:\s+([\s\S]*))?$/);
  if (!match) throw new Error("Usage: /run [auto] [--skills skill-a,skill-b] [objective]");
  return {
    objective: (match[2] ?? "").trim(),
    requestedSkills: [...new Set(match[1]!.split(",").map((item) => item.trim()).filter(Boolean))],
    mode: auto ? "auto" : "human",
  };
}

async function planDocumentsReady(root: string): Promise<boolean> {
  try {
    const [spec, plan] = await Promise.all([
      readFile(join(root, "notes", "research-spec.md"), "utf8"),
      readFile(join(root, "notes", "plan.md"), "utf8"),
    ]);
    return /Status:\s*awaiting-human-approval/i.test(spec) && /Status:\s*awaiting-human-approval/i.test(plan);
  } catch { return false; }
}

async function reviewPrimaryDocuments(ctx: Pick<ExtensionCommandContext, "hasUI" | "cwd" | "ui">): Promise<boolean> {
  if (!ctx.hasUI || activeApprovalDialogs.has(ctx.cwd)) return false;
  if (!(await planDocumentsReady(ctx.cwd))) {
    ctx.ui.notify("主要计划文档尚未生成完成；请先完成 /init 的学术追问。", "warning");
    return false;
  }
  activeApprovalDialogs.add(ctx.cwd);
  try {
    for (const document of PRIMARY_PLAN_DOCUMENTS) {
      const choice = await ctx.ui.select(
        `审批${document.title}：${document.path}`,
        ["批准当前版本", "拒绝并返回修改"],
        { timeout: 120_000 },
      );
      const approved = choice === "批准当前版本";
      await approvePrimaryDocument(ctx.cwd, document, approved ? "approved" : "rejected");
      if (!approved) {
        ctx.ui.notify(`${document.title}未批准；修改后运行 /approve 重新审批。`, "warning");
        return false;
      }
    }
    ctx.ui.notify("主要计划文档已批准。文档内容变化后审批会自动失效。", "info");
    return true;
  } finally {
    activeApprovalDialogs.delete(ctx.cwd);
  }
}

async function approveRunNodes(ctx: ExtensionCommandContext, runId: string, mode: "human" | "auto"): Promise<boolean> {
  for (const node of DEFAULT_RUN_APPROVAL_NODES) {
    if (mode === "auto") {
      await appendApproval(ctx.cwd, { kind: "step", nodeId: node.id, decision: "auto-approved", actor: "auto", runId, summary: node.summary });
      continue;
    }
    const options = node.required ? ["批准", "拒绝并停止"] : ["批准", "本次跳过", "拒绝并停止"];
    const choice = await ctx.ui.select(`${node.title}\n${node.summary}`, options, { timeout: 120_000 });
    const decision = choice === "批准" ? "approved" : choice === "本次跳过" ? "skipped" : "rejected";
    await appendApproval(ctx.cwd, { kind: "step", nodeId: node.id, decision, actor: "human", runId, summary: node.summary });
    if (decision === "rejected" || (node.required && decision !== "approved")) return false;
  }
  return true;
}

function toolApprovalSummary(toolName: string, input: unknown): string {
  const record = input && typeof input === "object" && !Array.isArray(input) ? input as Record<string, unknown> : {};
  const target = [record.path, record.file_path, record.command, record.action, record.server, record.tool]
    .find((value) => typeof value === "string") as string | undefined;
  return `${toolName}${target ? `: ${target.slice(0, 240)}` : ""}`;
}

function toolNeedsApproval(toolName: string, input: unknown): boolean {
  if (["write", "edit", "bash", "powershell", "psyclaw_workbench", "psyclaw_mcp"].includes(toolName)) return true;
  const action = input && typeof input === "object" && !Array.isArray(input) ? (input as Record<string, unknown>).action : undefined;
  return typeof action === "string" && /write|save|publish|install|download|execute|call/i.test(action);
}

function autoApprovalBlocked(toolName: string, input: unknown): string | undefined {
  const text = JSON.stringify(input ?? {}).toLocaleLowerCase();
  if (/data[\\/]raw|credential|secret|auth\.json|api[_ -]?key/.test(text)) return "自动模式不能批准原始数据或凭据路径操作";
  if (["bash", "powershell"].includes(toolName) && /\b(rm|rmdir|del|remove-item|format|shutdown|reboot|git\s+reset\s+--hard)\b/i.test(text)) {
    return "自动模式不能批准破坏性命令";
  }
  return undefined;
}

async function selectableRunSkills(root: string): Promise<Array<{ id: string; name: string }>> {
  const state = await readRecommendationState(root);
  const rows = await skillManagerRows(root, state);
  const available = [
    ...coreSkillNames().map((name) => ({ id: name, name })),
    ...rows.filter((row) => row.installed && row.enabled && !row.blocked).map((row) => ({ id: row.id, name: row.name })),
  ];
  const seen = new Set<string>();
  return available.filter((skill) => {
    const key = skill.name.trim().toLocaleLowerCase();
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function resolveRunSkills(requested: string[], available: Array<{ id: string; name: string }>): string[] {
  const lookup = new Map<string, string>();
  for (const skill of available) {
    lookup.set(skill.id.toLocaleLowerCase(), skill.name);
    lookup.set(skill.name.toLocaleLowerCase(), skill.name);
  }
  const selected: string[] = [];
  const unknown: string[] = [];
  for (const value of requested) {
    const name = lookup.get(value.toLocaleLowerCase());
    if (!name) unknown.push(value);
    else if (!selected.some((item) => item.toLocaleLowerCase() === name.toLocaleLowerCase())) selected.push(name);
  }
  if (unknown.length > 0) throw new Error(`本次运行不可用的 Skill：${unknown.join(", ")}。请先通过 /skill 安装或启用。`);
  return selected;
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
  scope: RecommendedSkillScope | "local";
  blocked: boolean;
  reason?: string;
  /** `recommended` rows come from the catalog; `local` rows are user-installed skills. */
  source: "recommended" | "local";
  duplicatePaths?: string[];
}

interface McpManagerRow {
  id: string;
  name: string;
  description: string;
  sourceRef?: string;
  enabled: boolean;
  details: string[];
  source: "recommended" | "user";
  /** Present for user-configured rows so the toggle can rewrite the config file. */
  userEntry?: UserMcpConfigEntry;
}

function skillScopeLabel(scope: RecommendedSkillScope | "local"): string {
  if (scope === "local") return "用户本地目录（所有项目可发现）";
  return scope === "user" ? "系统目录（所有项目）" : "项目目录（仅当前项目）";
}

async function skillManagerRows(root: string, state: RecommendationState): Promise<SkillManagerRow[]> {
  const catalog = await readRecommendedCatalog();
  const recommendedRows = await Promise.all(catalog.items.filter((item) => item.kind === "skill").map(async (item) => {
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
        source: "recommended" as const,
      };
    } catch (validationError) {
      // A managed target that exists on disk but fails validation (e.g. a URL
      // install whose manifest/hash does not match the pinned catalog) is still
      // shown as installed so the user sees it; enabling it only takes effect
      // once the install is repaired through /install.
      let onDisk = false;
      try {
        const target = recommendedSkillTarget(root, id, scope);
        const stat = await lstat(target);
        onDisk = stat.isDirectory();
      } catch { /* target missing */ }
      return {
        id,
        name: item.name,
        description: String(item.description ?? ""),
        ...(item.sourceRef === undefined ? {} : { sourceRef: item.sourceRef }),
        ...(typeof item.installHint === "string" ? { installHint: item.installHint } : {}),
        collection: item.skillLayout === "collection",
        installed: onDisk,
        enabled: onDisk && state.skills.includes(id),
        scope,
        blocked: typeof item.sourceRef !== "string" || !/^https:\/\//.test(item.sourceRef),
        reason: onDisk
          ? `已检测到目录但未通过来源/许可/哈希校验${state.skills.includes(id) ? "（当前配置为启用，但校验失败不会加载）" : ""}；可按 Enter 重新安装修复`
          : typeof item.sourceRef === "string" && /^https:\/\//.test(item.sourceRef)
            ? "尚未安装；按 Enter 选择安装范围并交给当前模型处理"
            : "没有可交给模型检查的来源网址",
        source: "recommended" as const,
      };
    }
  }));
  // Merge user-installed local skills from the expanded discovery roots so the
  // management page shows them and lets the user toggle each one.  Managed
  // recommended installs are excluded here — they are shown through their
  // recommended rows above (including on-disk-but-unvalidated installs).
  const userState = await readUserSkillState(root);
  const disabled = new Set(userState.disabled);
  const localSkills = await scanLocalSkills(root, { includeManaged: false });
  const localRows: SkillManagerRow[] = localSkills.map((skill) => ({
    id: userSkillId(skill.name),
    name: skill.name,
    description: skill.description,
    sourceRef: skill.path,
    collection: false,
    installed: true,
    enabled: !disabled.has(skill.name),
    scope: "local",
    blocked: false,
    source: "local",
    duplicatePaths: skill.duplicatePaths,
  }));
  // A catalog skill that is actually installed is shown once through its
  // recommended row (which carries source/trust info); purely local skills —
  // including a local copy of a catalog skill that failed managed validation —
  // are appended so they stay visible and toggleable.
  const installedRecommendedNames = new Set(
    recommendedRows.filter((row) => row.installed).map((row) => row.name.toLocaleLowerCase()),
  );
  const uniqueLocalRows = localRows.filter((row) => !installedRecommendedNames.has(row.name.toLocaleLowerCase()));
  return [...recommendedRows, ...uniqueLocalRows];
}

async function mcpManagerRows(root: string, state: RecommendationState, runtime: RuntimeMcpRegistry): Promise<McpManagerRow[]> {
  const { items, installPrep } = await recommendedItems("mcp");
  const recommendedRows: McpManagerRow[] = items.map((item) => {
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
      source: "recommended" as const,
      details: [
        `传输：${String(item.transport ?? "未声明")} · 风险：${String(item.risk ?? "未声明")}`,
        `参考版本：${String(plan?.ref ?? "由模型读取来源确定")} · 许可证：${String(plan?.license ?? "由模型读取来源确定")}`,
        `可能需要：${dependencies.length > 0 ? dependencies.join(", ") : "由模型读取来源确定"}`,
      ],
    };
  });
  // Merge user-configured MCP servers (`.psyclaw/mcp/*.json` and
  // `~/.psyclaw/mcp/*.json`) so the management page shows them too, even when
  // disabled.  User rows win over a same-id recommended row.
  const userRows: McpManagerRow[] = (await runtime.listUserConfigs(root)).map((entry) => ({
    id: entry.id,
    name: entry.name,
    description: `用户配置：${entry.command}`,
    enabled: entry.enabled,
    source: "user" as const,
    userEntry: entry,
    details: [
      `传输：stdio · 范围：${entry.scope === "user" ? "用户级" : "项目级"}`,
      `配置：${entry.path}`,
    ],
  }));
  const merged = new Map(recommendedRows.map((row) => [row.id, row]));
  for (const row of userRows) merged.set(row.id, row);
  return [...merged.values()].sort((left, right) => {
    if (left.source === "user" && right.source !== "user") return -1;
    if (right.source === "user" && left.source !== "user") return 1;
    return left.id.localeCompare(right.id);
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
      details: [
        `安装位置：${skillScopeLabel(row.scope)}`,
        ...(row.duplicatePaths && row.duplicatePaths.length > 0
          ? [`已忽略 ${row.duplicatePaths.length} 个同名来源`]
          : []),
      ],
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
      footer: "↑/↓ 移动 · Space 开启/关闭 · a 全部开启 · d 全部关闭 · Enter 交给模型安装并配置 · Esc 关闭",
      enterAction: "install",
      enabledText: "已开启；Enter 可让当前模型重新安装或修复推荐配置",
      disabledText: "已关闭",
    })
  ));
}

async function setRecommendedMcpEnabled(root: string, id: string, enabled: boolean): Promise<void> {
  const state = await readRecommendationState(root);
  const current = new Set(state.mcp);
  if (enabled) current.add(id); else current.delete(id);
  state.mcp = [...current];
  await saveRecommendationState(root, state);
}

async function setUserMcpEnabled(entry: UserMcpConfigEntry, enabled: boolean): Promise<void> {
  await setUserMcpConfigEnabled(entry, enabled);
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

async function showMcpManager(pi: ExtensionAPI, args: string, ctx: ExtensionCommandContext, runtime: RuntimeMcpRegistry): Promise<void> {
  const [verb, id] = args.trim().split(/\s+/).filter(Boolean);
  if (verb && !["status", "enable", "disable", "enable-all", "disable-all", "install"].includes(verb)) {
    throw new Error("Usage: /mcp [status|enable <id>|disable <id>|enable-all|disable-all|install <id>]");
  }
  if ((verb === "enable" || verb === "disable" || verb === "install") && !id) {
    throw new Error(`Usage: /mcp ${verb} <id>`);
  }
  const catalog = await recommendedItems("mcp");
  if (verb === "install") {
    const rows = await mcpManagerRows(ctx.cwd, await readRecommendationState(ctx.cwd), runtime);
    const row = rows.find((candidate) => candidate.id === id);
    if (!row) throw new Error(`未找到推荐 MCP: ${id}`);
    if (row.source !== "recommended") throw new Error(`MCP ${id} 已是用户配置，无需再次安装`);
    await queueModelMcpInstall(pi, ctx, row, catalog.installPrep.find((candidate) => candidate.id === row.id));
    return;
  }
  if (verb === "enable-all" || verb === "disable-all") {
    const enabled = verb === "enable-all";
    const rows = await mcpManagerRows(ctx.cwd, await readRecommendationState(ctx.cwd), runtime);
    for (const row of rows) {
      if (row.source === "user" && row.userEntry) await setUserMcpEnabled(row.userEntry, enabled);
      else await setRecommendedMcpEnabled(ctx.cwd, row.id, enabled);
    }
    ctx.ui.notify(`已批量${enabled ? "开启" : "关闭"}全部 MCP 配置；重启后重新检查运行时可用性`, "info");
    return;
  }
  if (verb === "enable" || verb === "disable") {
    const rows = await mcpManagerRows(ctx.cwd, await readRecommendationState(ctx.cwd), runtime);
    const row = rows.find((candidate) => candidate.id === id);
    if (!row) throw new Error(`未找到 MCP: ${id}`);
    if (row.source === "user" && row.userEntry) await setUserMcpEnabled(row.userEntry, verb === "enable");
    else await setRecommendedMcpEnabled(ctx.cwd, row.id, verb === "enable");
    ctx.ui.notify(`MCP ${id} 已${verb === "enable" ? "开启" : "关闭"}；重启后重新检查安装、信任和工具策略`, "info");
    return;
  }

  if (!ctx.hasUI || typeof ctx.ui.custom !== "function" || verb === "status") {
    const rows = await mcpManagerRows(ctx.cwd, await readRecommendationState(ctx.cwd), runtime);
    ctx.ui.notify(rows.map((row) => `${row.enabled ? "[on]" : "[off]"} ${row.id} — ${row.name}${row.source === "user" ? "（用户配置）" : ""}`).join("\n"), "info");
    return;
  }

  while (true) {
    const rows = await mcpManagerRows(ctx.cwd, await readRecommendationState(ctx.cwd), runtime);
    const action = await openMcpManager(ctx, rows);
    if (action.type === "close") return;
    if (action.type === "toggle-all") {
      for (const row of rows) {
        if (row.source === "user" && row.userEntry) await setUserMcpEnabled(row.userEntry, action.enabled);
        else await setRecommendedMcpEnabled(ctx.cwd, row.id, action.enabled);
      }
      ctx.ui.notify(`已批量${action.enabled ? "开启" : "关闭"}全部 MCP 配置；重启后重新检查运行时可用性`, "info");
      continue;
    }
    const row = rows.find((candidate) => candidate.id === action.id);
    if (!row) continue;
    if (action.type === "install") {
      if (row.source !== "recommended") {
        ctx.ui.notify(`${row.name} 已是用户配置，无需再次安装`, "info");
        continue;
      }
      await queueModelMcpInstall(pi, ctx, row, catalog.installPrep.find((candidate) => candidate.id === row.id));
      return;
    }
    if (action.type === "toggle") {
      if (row.source === "user" && row.userEntry) await setUserMcpEnabled(row.userEntry, action.enabled);
      else await setRecommendedMcpEnabled(ctx.cwd, row.id, action.enabled);
      ctx.ui.notify(`${row.name} 已${action.enabled ? "开启" : "关闭"}；重启后重新检查运行时可用性`, "info");
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
    "用户已通过 Skill 管理页授权本次安装。请使用当前会话的联网、文件和命令工具读取来源仓库，并直接下载、安装所需依赖和完成 Skill 安装；不要再次要求安装权限。不要写入其他 Skill 目录，不要修改 .psyclaw/data/raw、data/raw、.git 或研究产物。",
    row.collection
      ? "这是多 Skill 套件：目标目录自身无需 SKILL.md，但其子目录必须包含一个或多个有效 SKILL.md。保留套件内共享目录和相对路径，不得包含 .git、符号链接或凭据。"
      : "目标目录最终必须直接包含有效 SKILL.md（YAML frontmatter 至少包含 name 和 description），不得包含 .git、符号链接、凭据或二进制大文件。",
    "如果仓库包含多个 Skill，只安装与此推荐项相符的部分；如果它不是 Skill 或无法合理适配，停止并说明原因，不要伪造 SKILL.md。",
    "安装完成后检查目标目录结构，并提醒用户执行 /skill 启用该项，再执行 /reload。",
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
  ctx.ui.notify(`已将 ${row.name} 的安装任务交给当前模型，目标为${skillScopeLabel(scope)}。安装完成后请在 /skill 中启用，再执行 /reload。`, "info");
}

async function showSkillManager(pi: ExtensionAPI, args: string, ctx: ExtensionCommandContext): Promise<void> {
  const action = args.trim().split(/\s+/).filter(Boolean);
  const verb = action[0];
  const id = action[1];
  if (verb && !["status", "enable", "disable", "enable-all", "disable-all", "install"].includes(verb)) {
    throw new Error("Usage: /skill [status|enable <id>|disable <id>|enable-all|disable-all]");
  }
  if ((verb === "enable" || verb === "disable" || verb === "install") && !id) {
    throw new Error(`Usage: /skill ${verb} <id>`);
  }
  if (verb === "install") {
    const row = (await skillManagerRows(ctx.cwd, await readRecommendationState(ctx.cwd))).find((candidate) => candidate.id === normalizeRecommendedSkillId(id!));
    if (!row) throw new Error(`未找到推荐 Skill: ${id}`);
    await queueModelSkillInstall(pi, ctx, row);
    return;
  }
  if (verb === "enable-all" || verb === "disable-all") {
    const enabled = verb === "enable-all";
    const state = await readRecommendationState(ctx.cwd);
    const rows = await skillManagerRows(ctx.cwd, state);
    const managed = rows.filter((row) => row.source === "recommended" && row.installed && !row.blocked);
    const locals = rows.filter((row) => row.source === "local");
    const failed: string[] = [];
    for (const row of managed) {
      try { await setRecommendedSkillEnabled(ctx.cwd, row.id, enabled); }
      catch { if (enabled) failed.push(row.name); }
    }
    if (locals.length > 0) {
      await setLocalSkillsEnabled(ctx.cwd, locals.map((row) => row.name), enabled);
    }
    ctx.ui.notify(
      enabled && failed.length > 0
        ? `已批量启用（${failed.join("、")} 启用失败）。请运行 /reload 重新加载。`
        : `已批量${enabled ? "启用" : "停用"}可管理的 Skill。请运行 /reload 重新加载。`,
      enabled && failed.length > 0 ? "warning" : "info",
    );
    return;
  }
  if (verb === "enable" || verb === "disable") {
    const requested = normalizeRecommendedSkillId(id!);
    const state = await readRecommendationState(ctx.cwd);
    const rows = await skillManagerRows(ctx.cwd, state);
    const row = rows.find((candidate) => candidate.id === requested || candidate.name === requested || candidate.id === userSkillId(requested));
    if (!row) throw new Error(`未找到 Skill: ${id}`);
    if (row.source === "local") {
      await setLocalSkillEnabled(ctx.cwd, row.name, verb === "enable");
    } else {
      await setRecommendedSkillEnabled(ctx.cwd, row.id, verb === "enable");
    }
    ctx.ui.notify(`${verb === "enable" ? "已启用" : "已停用"} ${row.name}。请运行 /reload 重新加载。`, "info");
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
    if (action.type === "toggle-all") {
      const managed = rows.filter((row) => row.source === "recommended" && row.installed && !row.blocked);
      const locals = rows.filter((row) => row.source === "local");
      if (action.enabled) {
        const failed: string[] = [];
        for (const row of managed) {
          try { await setRecommendedSkillEnabled(ctx.cwd, row.id, true); }
          catch { failed.push(row.name); }
        }
        if (locals.length > 0) {
          const ids = locals.map((row) => row.name);
          await setLocalSkillsEnabled(ctx.cwd, ids, true);
        }
        ctx.ui.notify(
          failed.length > 0
            ? `已启用全部可管理的 Skill（${failed.join("、")} 启用失败：可能未通过来源、许可或依赖预检）。请运行 /reload 重新加载。`
            : `已启用全部可管理的 Skill。请运行 /reload 重新加载。`,
          failed.length > 0 ? "warning" : "info",
        );
      } else {
        for (const row of managed) {
          try { await setRecommendedSkillEnabled(ctx.cwd, row.id, false); }
          catch { /* already disabled */ }
        }
        if (locals.length > 0) {
          const ids = locals.map((row) => row.name);
          await setLocalSkillsEnabled(ctx.cwd, ids, false);
        }
        ctx.ui.notify("已停用全部可管理的 Skill。请运行 /reload 重新加载。", "info");
      }
      continue;
    }
    const row = rows.find((candidate) => candidate.id === action.id);
    if (!row) continue;
    if (action.type === "install") {
      await queueModelSkillInstall(pi, ctx, row);
      return;
    }
    if (action.type === "toggle") {
      if (row.source === "local") {
        await setLocalSkillEnabled(ctx.cwd, row.name, action.enabled);
        ctx.ui.notify(`已${action.enabled ? "启用" : "停用"}本地 Skill ${row.name}。请运行 /reload 重新加载。`, "info");
      } else {
        await setRecommendedSkillEnabled(ctx.cwd, row.id, action.enabled);
        ctx.ui.notify(`已${action.enabled ? "启用" : "停用"} ${row.name}。请运行 /reload 重新加载。`, "info");
      }
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
  if (!legacyTestApi && typeof pi.on === "function") pi.on("resources_discover", async (event) => {
    const enabled = await enabledRecommendedSkillPaths(event.cwd);
    const local = await enabledLocalSkillPaths(event.cwd, {
      excludedNames: [...coreSkillNames(), ...await skillNamesInPaths(enabled.paths)],
    });
    // Return only existing Skill directories. Same-name local/core candidates
    // are resolved before Pi sees them. Discovery warnings belong in /skill;
    // they should not interrupt every startup.
    return {
      skillPaths: [...enabled.paths, ...local.paths],
      promptPaths: await enabledLocalPromptPaths(event.cwd),
    };
  });
  if (!legacyTestApi && typeof pi.on === "function") pi.on("session_shutdown", () => runtimeMcps.close());
  if (!legacyTestApi && typeof pi.on === "function") pi.on("tool_call", async (event, ctx) => {
    const run = await readControlledRun(ctx.cwd);
    if (!run || !toolNeedsApproval(event.toolName, event.input)) return;
    const summary = toolApprovalSummary(event.toolName, event.input);
    if (run.mode === "auto") {
      const blockedReason = autoApprovalBlocked(event.toolName, event.input);
      await appendApproval(ctx.cwd, {
        kind: "tool",
        nodeId: event.toolCallId,
        decision: blockedReason ? "rejected" : "auto-approved",
        actor: "auto",
        runId: run.runId,
        sha256: approvalInputDigest({ toolName: event.toolName, input: event.input }),
        summary: blockedReason ?? summary,
      });
      return blockedReason ? { block: true, terminate: true, reason: blockedReason } : undefined;
    }
    if (!ctx.hasUI) return { block: true, terminate: true, reason: "该步骤需要人在环路审批，但当前没有交互界面" };
    const choice = await ctx.ui.select(`审批执行步骤\n${summary}`, ["批准本次执行", "拒绝并停止"], { timeout: 120_000 });
    const approved = choice === "批准本次执行";
    await appendApproval(ctx.cwd, {
      kind: "tool",
      nodeId: event.toolCallId,
      decision: approved ? "approved" : "rejected",
      actor: "human",
      runId: run.runId,
      sha256: approvalInputDigest({ toolName: event.toolName, input: event.input }),
      summary,
    });
    return approved ? undefined : { block: true, terminate: true, reason: "用户拒绝该执行步骤或审批超时" };
  });
  if (!legacyTestApi && typeof pi.on === "function") pi.on("agent_end", async (_event, ctx) => {
    if (!pendingInitApprovals.has(ctx.cwd) || !(await planDocumentsReady(ctx.cwd))) return;
    pendingInitApprovals.delete(ctx.cwd);
    await reviewPrimaryDocuments(ctx);
  });
  pi.registerCommand("init", {
    description: "初始化可追溯的研究项目",
    handler: async (args, ctx) => {
      try {
        const parsed = parseInitArgs(args);
        const project = await bootstrapProject({ root: ctx.cwd, ...parsed });
        if (typeof pi.sendUserMessage === "function") {
          pendingInitApprovals.add(ctx.cwd);
          pi.sendUserMessage(academicGrillRequest(project.goal, "init"), ctx.isIdle() ? {} : { deliverAs: "followUp" });
          ctx.ui.notify(`研究项目已初始化：${project.id}（${project.paradigm}）。学术追问完成并生成主要计划文档后会进入审批；全部批准后才能 /run。`, "info");
        } else {
          ctx.ui.notify(`研究项目已初始化：${project.id}（${project.paradigm}）。使用 /run 启动受控研究流程。`, "info");
        }
      } catch (error) {
        await notifyError(ctx, error);
      }
    },
  });

  if (!legacyTestApi) pi.registerCommand("approve", {
    description: "审批 /init 生成的主要研究计划文档",
    handler: async (_args, ctx) => {
      try { await reviewPrimaryDocuments(ctx); } catch (error) { await notifyError(ctx, error); }
    },
  });

  if (!legacyTestApi) pi.registerCommand("run", {
    description: "启动受控研究流程，可用 --skills a,b 选择本次优化 Skill",
    handler: async (args, ctx) => {
      try {
        const parsed = parseRunArgs(args);
        let project;
        try {
          project = await readProject(ctx.cwd);
        } catch (error) {
          // No `.psyclaw/project.json` (or it is corrupt): fall back to the
          // compliant analysis documents when present, so a project prepared
          // outside the /init flow can be analyzed directly.
          const { bootstrapProjectFromAnalysisDocs } = await import("../../project/bootstrap.js");
          try {
            project = await bootstrapProjectFromAnalysisDocs(ctx.cwd);
          } catch (bootstrapError) {
            ctx.ui.notify(bootstrapError instanceof Error ? bootstrapError.message : String(bootstrapError), "warning");
            return;
          }
          ctx.ui.notify("检测到合规的分析文档，已自动补齐研究项目记录并启动受控流程。", "info");
        }
        const planApproval = await primaryPlanApprovalStatus(ctx.cwd);
        if (!planApproval.ok) {
          const missing = planApproval.documents.filter((item) => !item.approved).map((item) => item.path);
          ctx.ui.notify(`主要计划尚未批准或批准后已修改：${missing.join("、")}。请运行 /approve。`, "warning");
          return;
        }
        const available = await selectableRunSkills(ctx.cwd);
        let requestedSkills = parsed.requestedSkills;
        if (parsed.mode === "auto" && requestedSkills === undefined) requestedSkills = [];
        if (requestedSkills === undefined && ctx.hasUI && typeof ctx.ui.input === "function") {
          const answer = await ctx.ui.input(
            "选择本次 Run 使用的 Skill（逗号分隔，可留空）",
            available.map((skill) => skill.name).join(", "),
          );
          if (answer === undefined) {
            ctx.ui.notify("已取消启动受控研究流程", "info");
            return;
          }
          requestedSkills = answer.split(",").map((item) => item.trim()).filter(Boolean);
        }
        const selectedSkills = resolveRunSkills(requestedSkills ?? [], available);
        const objective = parsed.objective || project.goal;
        const runId = `run_${Date.now()}`;
        await appendApproval(ctx.cwd, {
          kind: "run-mode",
          nodeId: "run-mode",
          decision: parsed.mode === "auto" ? "auto-approved" : "approved",
          actor: parsed.mode === "auto" ? "auto" : "human",
          runId,
          sha256: approvalInputDigest({ projectId: project.id, objective, selectedSkills, mode: parsed.mode }),
          summary: parsed.mode === "auto" ? "用户选择自动运行模式" : "用户选择人在环路模式",
        });
        if (!(await approveRunNodes(ctx, runId, parsed.mode))) {
          ctx.ui.notify("运行审批被拒绝或超时，未启动。", "warning");
          return;
        }
        await activateControlledRun(ctx.cwd, runId, project.id, objective, selectedSkills, parsed.mode);
        pi.appendEntry("psyclaw:controlled-run", { runId, projectId: project.id, objective, selectedSkills, mode: parsed.mode, activatedAt: new Date().toISOString() });
        pi.sendUserMessage(controlledRunRequest(objective, selectedSkills, parsed.mode), ctx.isIdle() ? {} : { deliverAs: "followUp" });
        ctx.ui.notify(`${parsed.mode === "auto" ? "自动" : "人在环路"}研究流程已启动${selectedSkills.length > 0 ? `；本次使用 Skill：${selectedSkills.join(", ")}` : "；使用默认 Skill"}。`, "info");
      } catch (error) {
        await notifyError(ctx, error);
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

  if (!legacyTestApi) pi.registerCommand("skill", {
    description: "管理和安装 Skill",
    handler: async (args, ctx) => {
      const [name, ...rest] = args.trim().split(/\s+/).filter(Boolean);
      if (!name) {
        try { await showSkillManager(pi, "", ctx); } catch (error) { await notifyError(ctx, error); }
        return;
      }
      if (name === "install") {
        const source = rest.join(" ").trim();
        if (!source) {
          ctx.ui.notify("Usage: /skill install <local-directory>", "info");
          return;
        }
        try {
          const installed = await installLocalSkill(source, ctx.cwd);
          ctx.ui.notify(`已安装本地 Skill ${installed.name}：${installed.target}。请执行 /reload。`, "info");
        } catch (error) {
          await notifyError(ctx, error);
        }
        return;
      }
      if (["status", "enable", "disable", "enable-all", "disable-all"].includes(name)) {
        try { await showSkillManager(pi, args, ctx); } catch (error) { await notifyError(ctx, error); }
        return;
      }
      ctx.ui.notify("Usage: /skill [status|enable <id>|disable <id>|enable-all|disable-all|install <local-directory>]", "info");
    },
  });

  if (!legacyTestApi) pi.registerCommand("plugin", {
    description: "管理 Plugin / Extension",
    handler: async (args, ctx) => {
      try {
        const [action, ...rest] = args.trim().split(/\s+/).filter(Boolean);
        if (!action) {
          ctx.ui.notify("Usage: /plugin list | install <source> [-l] | remove <source> [-l]", "info");
          return;
        }
        if (!["list", "install", "remove"].includes(action)) {
          throw new Error("Usage: /plugin list | install <source> [-l] | remove <source> [-l]");
        }
        if (action !== "list" && rest.length === 0) throw new Error(`Usage: /plugin ${action} <source> [-l]`);
        if (action !== "list") {
          const approved = await ctx.ui.confirm(
            `${action === "install" ? "安装" : "移除"} Plugin？`,
            `${rest.join(" ")}\nPlugin 与宿主进程同权限，操作完成后需要重启 PsyClaw。`,
          );
          if (!approved) return;
        }
        await runPluginCommand([action, ...rest]);
        if (action !== "list") ctx.ui.notify("Plugin 配置已更新，请重启 PsyClaw。", "info");
      } catch (error) { await notifyError(ctx, error); }
    },
  });

  if (!legacyTestApi) pi.registerCommand("mcp", {
    description: "打开 MCP 安装与配置管理页",
    handler: async (args, ctx) => {
      try { await showMcpManager(pi, args, ctx, runtimeMcps); } catch (error) { await notifyError(ctx, error); }
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
          ctx.ui.notify(["推荐安装入口", "", ...skillLines, ...mcpLines, "", ...toolLines, "", "安装：/install skill|mcp <id>", "管理：/skill 或 /mcp", "外部工具不通过 Skill 安装器安装", "也可以打开 /panel 查看推荐页面"].join("\n"), "info");
          return;
        }
        if (kind !== "skill" && kind !== "mcp") throw new Error("Usage: /install skill|mcp <id>");
        if (!id) {
          if (kind === "skill") await showSkillManager(pi, "", ctx);
          else await showMcpManager(pi, "", ctx, runtimeMcps);
          return;
        }
        if (kind === "skill") await showSkillManager(pi, `install ${id}`, ctx);
        else await showMcpManager(pi, `install ${id}`, ctx, runtimeMcps);
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
          const credential = await providerCredentialSource(preset);
          const key = credential === "missing" ? await promptProviderKey(ctx, preset.name, preset.apiKeyEnv) : "";
          if (key === undefined) return;
          await saveProviderConfig({ ...preset, ...(key ? { apiKey: key } : {}) });
          const refreshed = await Promise.race([
            ctx.modelRegistry.refresh().then(() => true),
            new Promise<false>((resolve) => setTimeout(() => resolve(false), 5_000)),
          ]);
          if (!refreshed) {
            ctx.ui.notify("Provider 配置已保存；模型目录刷新超时，请重新启动 PsyClaw 后使用。", "warning");
            return;
          }
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
    description: "导出包含正文与工具参数的完整使用路径，供 Langfuse 或 LangSmith 分析",
    handler: async (args: string, ctx: ExtensionCommandContext) => {
      try {
        if (args.trim()) throw new Error("Usage: /export");
        const result = await exportTraces({ root: ctx.cwd });
        ctx.ui.notify([
          "使用路径已导出（未上传）",
          `文件：${result.output}`,
          `轨迹：${result.traces}`,
          `步骤：${result.spans}`,
          "包含对话正文、工具参数、原始 ID 与绝对路径，便于排查各环节问题；请勿将导出文件提交到公开仓库。",
        ].join("\n"), "info");
      } catch (error) {
        await notifyError(ctx, error);
      }
    },
  };
  pi.registerCommand("export", traceCommand);

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
        "The worker runs in a separate PsyClaw process with extensions, skills, context files, and mutating tools disabled.",
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
