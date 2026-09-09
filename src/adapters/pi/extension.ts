import { DefaultPackageManager, getAgentDir, SettingsManager, type ExtensionAPI, type ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { appendApproval, approvalInputDigest, assertResearchDecision, bootstrapProject, resolveResearchDecision, runInstitutionalFulltext, runLiteratureReview, runExpertReview, runAnalysisDelegation, runWritingReview, runMetaAnalysis, createStageRunner, exportAcademicDocument, recordCitationUse, runParallelLiteratureResearch, runParallelPeerReview } from "../../index.js";
import type { ResearchDecisionImpact } from "../../research/decision.js";
import type { ResearchParadigm } from "../../core/contracts.js";
import { runPlanWithPi } from "../../orchestration/pi-executor.js";
import { formatEffects, hasElevatedEffects, normalizeEffects, toolsForEffects } from "../../orchestration/effects.js";
import { agentManagerRows } from "../../agents/recommended-personas.js";
import type { Plan } from "../../orchestration/contracts.js";
import { atomicWriteFile } from "../../project/jsonl.js";
import { applyCreation, previewCreation, runArsMultiAgentBridge, type ArsPanelRequest, type CreationKind, type CreationRequest } from "../../index.js";
import { loadUserRules, userRulesPrompt } from "../../rules/user-rules.js";
import { RunEventLog } from "../../panel/events.js";
import { readProject } from "../../research/ledger.js";
import { join } from "node:path";
import { lstat, mkdir, readFile, writeFile } from "node:fs/promises";
import { PROVIDER_PRESETS, providerCredentialSource, saveProviderConfig } from "../../setup.js";
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
import { WakeOptionsComponent } from "../../tui/wake-options.js";
import {
  applyWakeVerifySync,
  buildWakePrompt,
  createWakeVerifyChecklist,
  formatWakeResult,
  labelsFor,
  waitForPanelWakeAnswer,
  type WakeOptionsResult,
} from "../../wake-options/runtime.js";
import { panelHub } from "../../panel/hub.js";
import { appendChoiceRecord, type ChoiceRecordSource } from "../../research/choice.js";
import type { WakeOptionsAnswer } from "../../panel/hub.js";
import {
  enabledLocalSkillPaths,
  enabledLocalPromptPaths,
  readUserSkillState,
  scanLocalSkills,
  setLocalSkillEnabled,
  setLocalSkillsEnabled,
  skillNamesInPaths,
  userSkillId,
} from "../../skills/user-skills.js";
import {
  RuntimeMcpRegistry,
  setUserMcpConfigEnabled,
  type UserMcpConfigEntry,
} from "../../integrations/mcp-runtime.js";
import {
  SecretInputComponent,
  ProviderPickerComponent,
  type ProviderPickerItem,
  type ProviderPickerResult,
  type SecretInputResult,
} from "../../tui/provider-picker.js";
import {
  ARS_UPSTREAM_COMMIT,
  ARS_UPSTREAM_REF,
  isArsPiActive,
  isArsPiTurn,
  psyclawArsPatch,
  setArsPiSessionActive,
} from "../../ars/profile.js";
import { buildArsDoctorReport, ensurePdfEngineForExport } from "../../ars/doctor.js";
import {
  formatAcademicSoftRouteInvocation,
  rankAcademicSoftRoutes,
  resolveAcademicSoftRoute,
} from "../../ars/academic-router.js";
import {
  advanceAnalysisPlan,
  createAnalysisPlan,
  formatAnalysisPlanStatus,
  readActiveAnalysisPlan,
  syncHandoffFromAnalysisPlan,
  writeAnalysisPlan,
} from "../../analysis/plan.js";
import {
  formatAnalysisPlanTakeover,
  resolveStatsIntent,
} from "../../analysis/stats-router.js";
import { arsRoot } from "../../ars/pi-panel-executor.js";
import { ArsModeEditor, ARS_MODE_STATUS, isArsModeEditorText } from "../../ars/mode-editor.js";
import {
  MODE_STATUS,
  type PsyClawSessionMode,
  detectChatModeMismatch,
  formatChatModeMismatchNotice,
  nextSessionMode,
  parseSessionMode,
  sessionModePrompt,
} from "../../session/modes.js";
import {
  continuouslyWorkWarningText,
  isContinuouslyWorkEnabled,
} from "../../session/continuously-work.js";
import { assertHumanVerifyGate, formatVerifyChecklist, isNaturalPlanConfirm, ensureDefaultVerifyChecklist, loadVerifyChecklist } from "../../verify/checklist.js";
import { formatSessionHelp, formatSessionHelpBrief } from "../../session/help.js";
import { openResearchWorkbench } from "../../panel/workbench.js";
import {
  captureAgentError,
  initNodeObservability,
  readTelemetryPreference,
  shutdownObservability,
  trackGateWaiting,
  writeTelemetryPreference,
} from "../../observability/index.js";

/** Codex-style slash surface: bare command, or command + trailing free text. No subcommand trees. */
function parseInitArgs(args: string): { goal?: string; paradigm?: ResearchParadigm } {
  const goal = args.trim();
  if (!goal) return {};
  return { paradigm: "survey-observational", goal };
}

async function notifyError(ctx: ExtensionCommandContext, error: unknown): Promise<void> {
  await captureAgentError(error, { phase: "extension" });
  ctx.ui.notify(error instanceof Error ? error.message : String(error), "error");
}

const activeAgentRuns = new Set<string>();
const CORE_SKILLS = new Set(["academic-grill", "research-intake", "evidence-capture", "citation-audit", "analysis-plan"]);

function findLastMatching<T>(items: readonly T[], predicate: (item: T) => boolean): T | undefined {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index];
    if (item !== undefined && predicate(item)) return item;
  }
  return undefined;
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
  if (typeof ctx.ui.custom !== "function") {
    const labels = items.map((item) => `${item.current ? "* " : ""}${item.label} (${item.id})`);
    const selected = await ctx.ui.select(title, labels, { timeout: 60_000 });
    const index = selected === undefined ? -1 : labels.indexOf(selected);
    return index < 0 ? undefined : items[index]!.id;
  }
  const selected = await ctx.ui.custom<ProviderPickerResult>((tui, theme, keybindings, done) =>
    new ProviderPickerComponent(title, items, tui, theme, keybindings, done));
  return selected.type === "select" ? selected.id : undefined;
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

function creationCommandPrompt(kind: CreationKind, request: string): string {
  return [
    `The user explicitly requested /create-${kind}.`,
    "Call the psyclaw_create tool exactly once. Convert the request into the narrow structured fields accepted by that tool.",
    "Do not add permissions, shell commands, network access, credential access, gate bypasses, or external publication authority.",
    `Requested ${kind}: ${request || "Ask the user for the missing name, description, and instructions."}`,
  ].join("\n");
}

function academicGrillRequest(subject: string, mode: "init" | "review"): string {
  return [
    "先调用 psyclaw_skill 工具加载 PsyClaw 内置的 academic-grill Skill，然后严格遵循该 Skill 对我的学术研究进行追问。",
    subject
      ? `本次要讨论的研究主题或方案：${subject}`
      : "从当前对话、当前项目文件和已有研究状态中确定要讨论的研究主题或方案；能从这些材料查到的信息不要反问我。",
    "先根据研究主题、数据字段和已有材料提出 2-4 个有理论意义、可由现有材料回答的研究问题或假设，简述价值、可行性和边界，并推荐一个；不要把本应由你完成的研究构思全部反问给用户。",
    "随后从最上游、影响最大的未决问题开始。只有真正影响分析或解释且无法从现有材料判断时才提问；每轮只问一个问题，同时给出你的推荐答案或推荐决策及主要取舍。",
    "明确区分探索性与确证性研究。用户直接提供数据并要求分析时，默认按探索性、假设生成性工作处理，除非用户明确说明方案在看数据前已经确定。只有明确的确证性研究才询问哪些内容事先确定；不要求提供预注册链接。不把规划内容当作已有证据。直到关键分支已经解决或明确交由研究者决定后，再整理研究规格。",
    mode === "init"
      ? "持久化模式：init。追问完成后直接更新 academic-grill Skill 规定的全部项目文档，不再询问是否更新；写入后列出实际更新的文件。能依据研究目标、数据和通行方法明确处理的内容由你提出方案并写入，状态标为 ready-for-run。只有存在两个以上均合理、且会实质改变研究问题、样本处理、估计目标、方法或结果解释的方案时，才把该项写入 notes/decision_request.md 并请求研究者取舍。"
      : "持久化模式：review。追问完成后先展示拟更新摘要和受影响文件，并询问我是否写回；得到明确确认前不得修改项目文档。",
  ].join("\n");
}

/** Lightweight ideation path — never routes through academic-grill / /grill. */
function academicBrainstormRequest(subject: string): string {
  return [
    "这是 /brainstorm，不是 /grill：不要加载 academic-grill Skill，不要进入逐题压力测试或研究规格访谈。",
    subject
      ? `头脑风暴主题：${subject}`
      : "根据当前对话与项目材料确定头脑风暴主题；已有信息不要重复询问。",
    "请完成一次选题向的头脑风暴：",
    "1. 提出 2-4 个有理论意义、可由现有或可获取材料回答的研究方向 / 研究问题 / 假设。",
    "2. 简要比较各自的价值、可行性、数据需求与推断边界。",
    "3. 明确推荐其中一个，并说明推荐理由与主要取舍。",
    "4. 最多再问 1-2 个真正影响选题的澄清问题（可一次给出）；不要展开完整的设计/测量/估计量审讯。",
    "不要执行分析、不要写论文、不要伪造文献或结果。若用户接下来需要严格压力测试，请提示他们另用 /grill。",
  ].join("\n");
}

/** Initialized project context; replaces the removed `/run` controlled-run gate. */
interface ActiveProjectContext {
  projectId: string;
  runId: string;
  objective: string;
}

async function readActiveProject(root: string): Promise<ActiveProjectContext | null> {
  try {
    const project = await readProject(root);
    return {
      projectId: project.id,
      runId: `project_${project.id}`,
      objective: project.goal,
    };
  } catch {
    return null;
  }
}

function contextProjectTrusted(ctx: unknown): boolean {
  const candidate = ctx as { isProjectTrusted?: () => boolean };
  return typeof candidate.isProjectTrusted === "function" && candidate.isProjectTrusted();
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

function requiresSeparateOperationConfirmation(toolName: string, input: unknown): boolean {
  const text = `${toolName} ${JSON.stringify(input ?? {})}`;
  return /submit\s+(?:manuscript|paper|form)|投稿(?:到|至)|发布到(?:外部|期刊|会议|网站)|send\s+(?:email|message)|邮件发送/i.test(text);
}

async function recommendedItems(kind: "skills" | "mcp"): Promise<{ items: Array<Record<string, unknown>>; plugins: Array<Record<string, unknown>>; externalTools: Array<Record<string, unknown>>; installPrep: Array<Record<string, unknown>> }> {
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
      const value = JSON.parse(await readFile(path, "utf8")) as { items?: unknown; plugins?: unknown; externalTools?: unknown; installPrep?: unknown };
      return {
        items: Array.isArray(value.items) ? value.items.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object")) : [],
        plugins: Array.isArray(value.plugins) ? value.plugins.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object")) : [],
        externalTools: Array.isArray(value.externalTools) ? value.externalTools.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object")) : [],
        installPrep: Array.isArray(value.installPrep) ? value.installPrep.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object")) : [],
      };
    } catch { /* try next candidate */ }
  }
  return { items: [], plugins: [], externalTools: [], installPrep: [] };
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

interface PluginManagerRow {
  id: string;
  name: string;
  description: string;
  sourceRef: string;
  installed: boolean;
  scope?: "project" | "user";
  stage?: string;
  installable: boolean;
  reason?: string;
  local: boolean;
  filtered?: boolean;
}

function pluginSourceIdentity(source: string): string {
  return source.trim()
    .replace(/^git:/, "")
    .replace(/^https?:\/\//i, "")
    .replace(/^git@([^:]+):/i, "$1/")
    .replace(/@[^/]+$/, "")
    .replace(/\.git$/i, "")
    .replace(/\/$/, "")
    .toLocaleLowerCase();
}

function nativePluginManager(ctx: ExtensionCommandContext): DefaultPackageManager {
  const settingsManager = SettingsManager.create(ctx.cwd, getAgentDir(), { projectTrusted: ctx.isProjectTrusted() });
  return new DefaultPackageManager({ cwd: ctx.cwd, agentDir: getAgentDir(), settingsManager });
}

function pluginDisplayName(source: string): string {
  const normalized = source.replace(/^git:/, "").replace(/[?#].*$/, "").replace(/\.git$/i, "").replace(/\/$/, "");
  const tail = normalized.split(/[\\/]/).filter(Boolean).at(-1) ?? normalized;
  return tail.replace(/^npm:/, "") || "Local Plugin";
}

async function pluginManagerRows(ctx: ExtensionCommandContext): Promise<PluginManagerRow[]> {
  const catalog = await recommendedItems("skills");
  const configuredBySource = new Map<string, ReturnType<DefaultPackageManager["listConfiguredPackages"]>[number]>();
  for (const entry of nativePluginManager(ctx).listConfiguredPackages()) {
    const key = pluginSourceIdentity(entry.source);
    const previous = configuredBySource.get(key);
    if (!previous || entry.scope === "project") configuredBySource.set(key, entry);
  }
  const matched = new Set<string>();
  const recommended = catalog.plugins.map((item) => {
    const sourceRef = String(item.sourceRef ?? "").trim();
    const sourceKey = pluginSourceIdentity(sourceRef);
    const installed = configuredBySource.get(sourceKey);
    if (installed) matched.add(sourceKey);
    return {
      id: String(item.id ?? ""),
      name: String(item.name ?? item.id ?? "Plugin"),
      description: String(item.description ?? ""),
      sourceRef,
      installed: installed?.installedPath !== undefined,
      installable: item.installable !== false,
      local: false,
      ...(installed === undefined ? {} : { scope: installed.scope }),
      ...(installed?.filtered === undefined ? {} : { filtered: installed.filtered }),
      ...(typeof item.stage === "string" ? { stage: item.stage } : {}),
      ...(item.installable === false
        ? { reason: String(item.installHint ?? "尚未提供 Pi 可安装的 Plugin package") }
        : installed && installed.installedPath === undefined
          ? { reason: "Pi 配置中已有该 Plugin，但本地安装目录不存在；请重新安装。" }
          : {}),
    };
  });
  const local = [...configuredBySource.entries()]
    .filter(([key]) => !matched.has(key))
    .map(([, entry], index): PluginManagerRow => ({
      id: `local-plugin-${index + 1}`,
      name: pluginDisplayName(entry.source),
      description: "由 Pi 原生包管理器识别的本地已安装 Plugin。",
      sourceRef: entry.source,
      installed: entry.installedPath !== undefined,
      installable: true,
      local: true,
      scope: entry.scope,
      filtered: entry.filtered,
      stage: "本地 Plugin",
      ...(entry.installedPath === undefined ? { reason: "Pi 配置中已有该 Plugin，但对应的本地安装目录不存在；请重新安装。" } : {}),
    }));
  return [...recommended, ...local];
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
      // once the install is repaired through /skill.
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

function pluginManagerItems(rows: PluginManagerRow[]): SkillManagerItem[] {
  return rows.map((row) => ({
    id: row.id,
    name: row.name,
    description: row.description,
    status: !row.installable ? "blocked" as const : row.installed ? "enabled" as const : "missing" as const,
    sourceRef: row.sourceRef,
    details: [
      `类别：${row.stage ?? "研究扩展"}`,
      ...(row.scope ? [`安装位置：${row.scope === "project" ? "项目目录（仅当前项目）" : "系统目录（所有项目）"}`] : []),
      ...(row.filtered ? ["资源范围：使用了 Pi package 过滤配置"] : []),
    ],
    ...(row.reason ? { reason: row.reason } : {}),
  }));
}

async function openPluginManager(ctx: ExtensionCommandContext, rows: PluginManagerRow[]): Promise<SkillManagerAction> {
  return ctx.ui.custom((tui, theme, keybindings, done) => (
    new SkillManagerComponent(pluginManagerItems(rows), tui, theme, keybindings, done, {
      title: "Plugin 推荐",
      itemLabel: "Plugin",
      footer: "↑/↓ 移动 · Enter 安装或重新安装 · Esc 关闭",
      enterAction: "install",
      toggleEnabled: false,
      enabledText: "已由 Pi 原生 Plugin 管理器安装；Enter 可重新安装",
      missingMessage: "按 Enter 安装到当前项目。",
    })
  ));
}

function agentManagerItems(rows: Awaited<ReturnType<typeof agentManagerRows>>): SkillManagerItem[] {
  return rows.map((row) => ({
    id: row.id,
    name: row.name,
    description: row.description,
    status: row.status,
    sourceRef: row.sourceRef,
    details: [
      `类别：${row.stage}`,
      `角色：${row.role}`,
      `来源：${row.source === "bundled" ? "内置 Subagent（类似 Claude Explore/Plan）" : "项目 .psyclaw/agents/custom"}`,
      `运行：/agents <只读研究任务>`,
    ],
  }));
}

async function openAgentManager(ctx: ExtensionCommandContext, rows: Awaited<ReturnType<typeof agentManagerRows>>): Promise<SkillManagerAction> {
  return ctx.ui.custom((tui, theme, keybindings, done) => (
    new SkillManagerComponent(agentManagerItems(rows), tui, theme, keybindings, done, {
      title: "Subagent（对齐 Claude Code）",
      itemLabel: "Subagent",
      footer: "↑/↓ 移动 · Enter 查看用法 · Esc 关闭 · 运行: /agents <任务>",
      enterAction: "details",
      toggleEnabled: false,
      enabledText: "已可选用",
      lockedMessage: "内置 Subagent 始终可用。运行：/agents <只读研究任务>",
    })
  ));
}

async function showAgentManager(ctx: ExtensionCommandContext, statusOnly = false): Promise<void> {
  const rows = await agentManagerRows(ctx.cwd);
  if (!ctx.hasUI || typeof ctx.ui.custom !== "function" || statusOnly) {
    ctx.ui.notify(
      rows.map((row) => `${row.status === "core" ? "◆" : "●"} ${row.id} — ${row.name}（${row.stage}）`).join("\n")
        || "暂无 Subagent。可用 /create-subagent 创建（类似 Claude Code）。",
      "info",
    );
    return;
  }
  while (true) {
    const action = await openAgentManager(ctx, await agentManagerRows(ctx.cwd));
    if (action.type === "close") return;
    // Enter/Space only show inline notices; keep the manager open.
  }
}

async function installRecommendedPlugin(ctx: ExtensionCommandContext, row: PluginManagerRow): Promise<void> {
  if (!row.installable) throw new Error(row.reason ?? `${row.name} 尚未提供可安装的 Plugin package`);
  if (!row.sourceRef) throw new Error(`推荐 Plugin 没有来源网址: ${row.id}`);
  await nativePluginManager(ctx).installAndPersist(row.sourceRef, { local: true });
  ctx.ui.notify(`${row.name} 已安装到项目目录（仅当前项目）。请执行 /reload 载入 Plugin。`, "info");
}

async function showPluginManager(ctx: ExtensionCommandContext): Promise<void> {
  const rows = await pluginManagerRows(ctx);
  if (!ctx.hasUI || typeof ctx.ui.custom !== "function") {
    ctx.ui.notify(rows.map((row) => `${row.installed ? "[on]" : "[off]"} ${row.id} — ${row.name}${row.scope ? `（${row.scope === "project" ? "项目" : "系统"}）` : ""}`).join("\n"), "info");
    return;
  }
  while (true) {
    const currentRows = await pluginManagerRows(ctx);
    const action = await openPluginManager(ctx, currentRows);
    if (action.type === "close") return;
    if (action.type !== "install") continue;
    const row = currentRows.find((candidate) => candidate.id === action.id);
    if (!row) continue;
    await installRecommendedPlugin(ctx, row);
    return;
  }
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

async function showMcpManager(pi: ExtensionAPI, ctx: ExtensionCommandContext, runtime: RuntimeMcpRegistry): Promise<void> {
  const catalog = await recommendedItems("mcp");
  if (!ctx.hasUI || typeof ctx.ui.custom !== "function") {
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

async function showSkillManager(pi: ExtensionAPI, ctx: ExtensionCommandContext): Promise<void> {
  if (!ctx.hasUI || typeof ctx.ui.custom !== "function") {
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
  void initNodeObservability();
  const developerCommands = process.env.PSYCLAW_DEVELOPER_COMMANDS === "1";
  const legacyTestApi = typeof pi.registerTool !== "function";
  const runtimeMcps = new RuntimeMcpRegistry();
  let arsModeEditor: ArsModeEditor | undefined;
  let arsUiContext: { sessionManager: Parameters<typeof isArsPiActive>[0]; isIdle: () => boolean; hasUI: boolean; ui: { setStatus: (key: string, text: string | undefined) => void } } | undefined;
  let sessionMode: PsyClawSessionMode = "chat";

  const applySessionMode = (mode: PsyClawSessionMode, opts?: { syncSession?: boolean }) => {
    sessionMode = mode;
    arsModeEditor?.setMode(mode);
    arsUiContext?.ui.setStatus("mode", MODE_STATUS[mode]);
    // Clear legacy ars status key so it never duplicates with "mode".
    arsUiContext?.ui.setStatus("ars", undefined);
    if (opts?.syncSession === false || !arsUiContext) return;
    setArsPiSessionActive(
      typeof (pi as { appendEntry?: unknown }).appendEntry === "function"
        ? (pi as { appendEntry: (type: string, data: { active: boolean }) => void }).appendEntry.bind(pi)
        : undefined,
      mode === "academic",
    );
    if (typeof (pi as { appendEntry?: unknown }).appendEntry === "function") {
      (pi as { appendEntry: (type: string, data: { mode: PsyClawSessionMode }) => void }).appendEntry("psyclaw-session-mode", { mode });
    }
  };

  const cycleSessionMode = () => {
    const next = nextSessionMode(arsModeEditor?.getMode() ?? sessionMode);
    applySessionMode(next);
    arsUiContext?.ui.setStatus("mode", MODE_STATUS[next] ?? "chat");
  };

  if (!legacyTestApi && typeof pi.registerShortcut === "function") {
    pi.registerShortcut("shift+tab", {
      description: "Cycle chat → analysis → academic",
      handler: () => {
        cycleSessionMode();
      },
    });
  }
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
  if (!legacyTestApi && typeof pi.on === "function") pi.on("session_shutdown", () => {
    runtimeMcps.close();
    void shutdownObservability();
  });
  if (!legacyTestApi && typeof pi.on === "function") pi.on("before_agent_start", async (event, ctx) => {
    if (!(await readActiveProject(ctx?.cwd ?? process.cwd()))) return;
    const prompt = userRulesPrompt(await loadUserRules(ctx?.cwd ?? process.cwd()));
    if (prompt) return { systemPrompt: `${event.systemPrompt}\n\n${prompt}` };
  });
  if (!legacyTestApi && typeof pi.on === "function") pi.on("before_agent_start", (event, ctx) => {
    const modeEntry = [...(ctx?.sessionManager?.getBranch?.() ?? [])].reverse().find((entry) =>
      entry.type === "custom" && (entry as { customType?: string }).customType === "psyclaw-session-mode");
    const restored = parseSessionMode((modeEntry as { data?: { mode?: unknown } } | undefined)?.data?.mode)
      ?? (isArsPiActive(ctx?.sessionManager) ? "academic" : sessionMode);
    sessionMode = restored;
    const modeBlock = sessionModePrompt(restored);
    if (restored === "academic" || isArsPiTurn(event.systemPrompt) || isArsPiActive(ctx?.sessionManager)) {
      return {
        systemPrompt: `${event.systemPrompt}\n\n${modeBlock}\n\n${psyclawArsPatch({
          skills: event.systemPromptOptions?.skills,
          systemPrompt: event.systemPrompt,
        })}`,
      };
    }
    return { systemPrompt: `${event.systemPrompt}\n\n${modeBlock}` };
  });
  if (!legacyTestApi && typeof pi.on === "function") pi.on("session_start", (_event, ctx) => {
    arsUiContext = ctx;
    if (isContinuouslyWorkEnabled() && ctx.hasUI) {
      ctx.ui.setStatus("cw", "continuously-work");
      ctx.ui.notify(continuouslyWorkWarningText(), "error");
    }
    if (!ctx.hasUI || typeof ctx.ui.setEditorComponent !== "function") return;

    ctx.ui.setEditorComponent((tui, theme, keybindings) => {
      const editor = new ArsModeEditor(tui, theme, keybindings);
      arsModeEditor = editor;
      editor.onModeChange = (mode) => {
        sessionMode = mode;
        ctx.ui.setStatus("mode", MODE_STATUS[mode]);
        ctx.ui.setStatus("ars", undefined);
      };
      editor.onCycleMode = () => {
        cycleSessionMode();
      };
      const modeEntry = [...ctx.sessionManager.getBranch()].reverse().find((entry) =>
        entry.type === "custom" && (entry as { customType?: string }).customType === "psyclaw-session-mode");
      const restore = parseSessionMode((modeEntry as { data?: { mode?: unknown } } | undefined)?.data?.mode)
        ?? (isArsPiActive(ctx.sessionManager) ? "academic" : "chat");
      editor.setMode(restore);
      sessionMode = restore;
      ctx.ui.setStatus("mode", MODE_STATUS[restore]);
      ctx.ui.setStatus("ars", undefined);
      return editor;
    });
  });
  if (!legacyTestApi && typeof pi.on === "function") pi.on("input", async (event, ctx) => {
    if (event.source === "extension") return;
    if (/^\/(?:login|logout)(?:\s|$)/i.test(event.text.trim())) {
      ctx.ui.notify("PsyClaw 已统一隐藏底层登录命令。请使用 /provider 配置、切换或更新模型凭据。", "info");
      return { action: "handled" };
    }
    if (/^\/help(?:\s|$)/i.test(event.text.trim())) {
      try {
        const { url, opened } = await openResearchWorkbench({
          cwd: ctx.cwd,
          isProjectTrusted: () => ctx.isProjectTrusted(),
          isIdle: () => ctx.isIdle(),
          sendUserMessage: (message, options) => pi.sendUserMessage(message, options ?? {}),
        }, { view: "help" });
        ctx.ui.notify(formatSessionHelpBrief(url) + (opened ? "" : "\n（未能自动打开浏览器时请手动访问）"), opened ? "info" : "warning");
      } catch (error) {
        ctx.ui.notify(`${formatSessionHelp()}\n\n（Panel 未启动：${error instanceof Error ? error.message : String(error)}）`, "info");
      }
      return { action: "handled" };
    }

    const mode = arsModeEditor?.getMode() ?? sessionMode;
    const trimmed = event.text.trim();

    // Chat must not soft-takeover; when intent fits analysis/academic, remind only.
    if (mode === "chat") {
      const mismatch = detectChatModeMismatch(trimmed);
      if (mismatch) {
        ctx.ui.notify(mismatch.notify, "warning");
        return {
          action: "transform",
          text: formatChatModeMismatchNotice(mismatch, trimmed),
        };
      }
    }

    // Natural-language plan confirm: reply「可以」instead of forcing /plan confirm.
    if (mode === "analysis" && isNaturalPlanConfirm(trimmed)) {
      const plan = await readActiveAnalysisPlan(ctx.cwd);
      if (plan && (plan.status === "awaiting-confirm" || plan.status === "ready" || plan.status === "reviewing")) {
        const method = plan.confirmedMethod || plan.primaryAnalysis || plan.proposedMethods[0] || "按当前方案执行";
        let next = plan.status === "awaiting-confirm"
          ? advanceAnalysisPlan(plan, { type: "confirm", method, backend: "local-script" })
          : plan;
        if (next.status === "reviewing" || next.status === "awaiting-confirm") {
          next = advanceAnalysisPlan(next, { type: "review" });
        }
        next = advanceAnalysisPlan(next, { type: "run-now" });
        next = await writeAnalysisPlan(ctx.cwd, next);
        ctx.ui.notify(`${formatAnalysisPlanStatus(next)}\n已按自然语言确认并开始执行。`, "info");
        return {
          action: "transform",
          text: [
            "/skill:analysis-plan",
            "",
            `User confirmed with natural language ("${trimmed}"). Execute plan ${next.id} now.`,
            `Confirmed method: ${next.confirmedMethod ?? method}`,
            next.approvalMode === "auto" ? "approvalMode=auto: label outputs as 未经人审批." : "Human confirmed this step.",
            "Before and after analysis, open Panel checklist or /crosscheck; skipping must mark 未经核对.",
          ].join("\n"),
        };
      }
    }

    const wantsStats = mode === "analysis" && Boolean(resolveStatsIntent(trimmed));
    const wantsAcademic = mode === "academic" && Boolean(resolveAcademicSoftRoute(trimmed));
    if ((wantsStats || wantsAcademic) && !(await readActiveProject(ctx.cwd))) {
      if (!ctx.hasUI) {
        return {
          action: "transform",
          text: [
            "尚未 /init。请先提醒用户初始化工作区；若用户确认可无仓继续，再处理其请求。",
            "User request:",
            trimmed,
          ].join("\n"),
        };
      }
      const choice = await ctx.ui.select(
        "尚未 /init。统计/写作建议先建仓，否则交接与核对清单不完整。",
        ["先执行 /init", "本次继续（稍后 init）", "取消"],
        { timeout: 120_000 },
      );
      if (choice === "取消" || choice === undefined) return { action: "handled" };
      if (choice === "先执行 /init") {
        return { action: "transform", text: `/init\n\n（用户选择先初始化，完成后再继续：${trimmed}）` };
      }
      ctx.ui.notify("继续本次请求；建议随后 /init。关键结果请做交叉核验。", "warning");
    }

    if (mode === "academic") {
      const match = resolveAcademicSoftRoute(event.text);
      if (!match) return;
      const ranked = rankAcademicSoftRoutes(event.text, 3);
      return {
        action: "transform",
        text: formatAcademicSoftRouteInvocation(match, event.text, ranked.slice(1)),
      };
    }
    if (mode === "analysis") {
      const match = resolveStatsIntent(event.text);
      if (!match) return;
      return {
        action: "transform",
        text: formatAnalysisPlanTakeover(event.text),
      };
    }
  });
  if (!legacyTestApi && typeof pi.on === "function") pi.on("tool_call", async (event, ctx) => {
    const run = await readActiveProject(ctx.cwd);
    if (!run || !toolNeedsApproval(event.toolName, event.input)) return;
    const summary = toolApprovalSummary(event.toolName, event.input);
    if (requiresSeparateOperationConfirmation(event.toolName, event.input)) {
      if (!ctx.hasUI) return { block: true, terminate: true, reason: "外部发布需要用户在交互界面中明确确认" };
      void trackGateWaiting("tool_approval");
      const choice = await ctx.ui.select(`确认外部操作\n${summary}`, ["确认执行", "取消"], { timeout: 120_000 });
      const approved = choice === "确认执行";
      await appendApproval(ctx.cwd, {
        kind: "tool",
        nodeId: event.toolCallId,
        decision: approved ? "approved" : "rejected",
        actor: "human",
        runId: run.runId,
        sha256: approvalInputDigest({ toolName: event.toolName, input: event.input }),
        summary,
      });
      return approved ? undefined : { block: true, terminate: true, reason: "用户取消了外部操作" };
    }
    await appendApproval(ctx.cwd, {
      kind: "tool",
      nodeId: event.toolCallId,
      decision: "auto-approved",
      actor: "auto",
      runId: run.runId,
      sha256: approvalInputDigest({ toolName: event.toolName, input: event.input }),
      summary,
    });
    return undefined;
  });
  pi.registerCommand("init", {
    description: "搭建干净工作仓库（目录 + psyclaw.md），不自动追问",
    handler: async (args, ctx) => {
      try {
        const parsed = parseInitArgs(args);
        const project = await bootstrapProject({ root: ctx.cwd, ...parsed });
        ctx.ui.notify(
          [
            `工作仓库已初始化：${project.id}`,
            "已创建 data/raw|clean、analysis/、literature/、paper/、psyclaw.md、.psyclaw/",
            "Shift+Tab：chat → analysis → academic",
            "Thinking：Ctrl+Shift+T",
            "澄清与分析请切到 analysis；写作审稿请切到 academic。输入 /help 查看速览。",
          ].join("\n"),
          "info",
        );
      } catch (error) {
        await notifyError(ctx, error);
      }
    },
  });

  const handleCrosscheck = async (args: string, ctx: ExtensionCommandContext): Promise<void> => {
    try {
      await ensureDefaultVerifyChecklist(ctx.cwd);
      const focus = args.trim();
      if (!focus) {
        ctx.ui.notify(
          [
            formatVerifyChecklist(await loadVerifyChecklist(ctx.cwd)),
            "/crosscheck：过程性核对（数据、引文是否真实存在、格式/报告要求等）。",
            "人审不经斜杠命令：收尾门禁会要求 Panel「核实」或唤醒选项。",
          ].join("\n"),
          "info",
        );
        return;
      }
      pi.sendUserMessage(
        [
          "/crosscheck — 过程性交叉核对（AI）。",
          `焦点：${focus}`,
          "范围重点：",
          "1) 数据与表：字段、N、表内数值与脚本/输出是否过程一致；",
          "2) 引文真实性：DOI/题录能否解析，是否指向真实文献（存在性，不在此阶段裁决引用是否“该不该引”）；",
          "3) 格式与报告要求：APA/三线表/必备报告字段、清单项是否齐；",
          "4) 过程产物：脚本入口、中间文件、可复现痕迹是否齐全。",
          "执行方式：派出至少两个独立审查视角（例如：数据一致性；引文存在性；格式/报告合同），各自给出发现后再合并为一份报告；标出一致项与冲突项。",
          "不得自称已过人审。人审由系统在交接/定稿门禁自动要求，经 Panel「核实」或唤醒选项完成。",
        ].join("\n"),
        ctx.isIdle() ? {} : { deliverAs: "followUp" },
      );
      ctx.ui.notify(`已启动过程性 /crosscheck（焦点：${focus}）。人审由收尾门禁自动要求。`, "info");
    } catch (error) {
      await notifyError(ctx, error);
    }
  };

  const handleVerify = async (args: string, ctx: ExtensionCommandContext): Promise<void> => {
    try {
      await ensureDefaultVerifyChecklist(ctx.cwd);
      const focus = args.trim();
      if (!focus) {
        ctx.ui.notify(
          [
            formatVerifyChecklist(await loadVerifyChecklist(ctx.cwd)),
            "/verify：整体性验证（分析结果是否属实/成立、引文是否合理、方法是否合理）。",
            "人审不经斜杠命令：Panel「核实」或唤醒选项。",
          ].join("\n"),
          "info",
        );
        return;
      }
      pi.sendUserMessage(
        [
          "/verify — 整体性实质验证（AI）。",
          `焦点：${focus}`,
          "范围重点：",
          "1) 分析结果是否属实、是否成立：效应方向/量级、不确定性、与脚本输出是否支持正文主张；",
          "2) 引文是否合理：是否支撑该主张、有无断章取义或装饰性引用（不仅是 DOI 能否解析）；",
          "3) 方法是否合理：设计、估计目标、检验/模型选择与研究问题是否匹配；",
          "4) 解释边界：相关≠因果、探索/确证区分、过度声称。",
          "给出可核对的判断（成立 / 存疑 / 不成立）及依据；不得自称已过人审。",
          "人审由交接/定稿门禁自动要求，经 Panel「核实」或唤醒选项完成。",
        ].join("\n"),
        ctx.isIdle() ? {} : { deliverAs: "followUp" },
      );
      ctx.ui.notify(`已启动整体性 /verify（焦点：${focus}）。人审由收尾门禁自动要求。`, "info");
    } catch (error) {
      await notifyError(ctx, error);
    }
  };

  pi.registerCommand("crosscheck", {
    description: "过程性 AI 核对：数据/引文真实性/格式要求；可附带焦点",
    handler: async (args, ctx) => handleCrosscheck(args, ctx),
  });
  pi.registerCommand("verify", {
    description: "整体性 AI 验证：结果是否成立、引文与方法是否合理；可附带焦点",
    handler: async (args, ctx) => handleVerify(args, ctx),
  });

  pi.registerCommand("help", {
    description: "打开 Panel 使用速览",
    handler: async (_args, ctx) => {
      try {
        const { url, opened } = await openResearchWorkbench({
          cwd: ctx.cwd,
          isProjectTrusted: () => ctx.isProjectTrusted(),
          isIdle: () => ctx.isIdle(),
          sendUserMessage: (message, options) => pi.sendUserMessage(message, options ?? {}),
        }, { view: "help" });
        ctx.ui.notify(formatSessionHelpBrief(url) + (opened ? "" : "\n（未能自动打开浏览器时请手动访问）"), opened ? "info" : "warning");
      } catch (error) {
        ctx.ui.notify(`${formatSessionHelp()}\n\n（Panel 未启动：${error instanceof Error ? error.message : String(error)}）`, "info");
      }
    },
  });
  pi.registerCommand("plan", {
    description: "分析方案：单独查看状态，或附带目标文本新建方案",
    handler: async (args, ctx) => {
      try {
        const goal = args.trim();
        if (goal) {
          const plan = await writeAnalysisPlan(ctx.cwd, createAnalysisPlan({ goal }));
          ctx.ui.notify(`${formatAnalysisPlanStatus(plan)}\n已按目标创建。用自然语言确认方法（如「可以」）；完成后用 /handoff 交接。`, "info");
          pi.sendUserMessage(
            [
              "/skill:analysis-plan",
              "",
              `Active plan ${plan.id} created for goal: ${goal}`,
              "Clarify methods with the researcher; prefer natural-language confirmation. Do not invent numbers.",
            ].join("\n"),
            ctx.isIdle() ? {} : { deliverAs: "followUp" },
          );
          return;
        }
        const plan = await readActiveAnalysisPlan(ctx.cwd);
        if (!plan) {
          ctx.ui.notify("没有活跃分析 Plan。用 /plan <目标> 创建，或在 analysis 模式用自然语言触发 soft takeover。", "info");
          return;
        }
        ctx.ui.notify(`${formatAnalysisPlanStatus(plan)}\n确认与执行请用自然语言；交接用 /handoff。`, "info");
      } catch (error) {
        await notifyError(ctx, error);
      }
    },
  });

  pi.registerCommand("handoff", {
    description: "人审通过后写入 analysis/HANDOFF.md 交接",
    handler: async (_args, ctx) => {
      try {
        const gate = await assertHumanVerifyGate(ctx.cwd, "analysis-complete");
        if (!gate.ok) {
          ctx.ui.notify(gate.message, "error");
          return;
        }
        let plan = await readActiveAnalysisPlan(ctx.cwd);
        if (!plan) {
          ctx.ui.notify("没有活跃分析 Plan，无法交接。先 /plan <目标> 或在 analysis 模式推进。", "warning");
          return;
        }
        const path = await syncHandoffFromAnalysisPlan(ctx.cwd, plan);
        if (plan.status === "running") {
          plan = advanceAnalysisPlan(
            plan,
            plan.scriptEntrypoint
              ? { type: "complete", scriptEntrypoint: plan.scriptEntrypoint }
              : { type: "complete" },
          );
          plan = await writeAnalysisPlan(ctx.cwd, plan);
        }
        ctx.ui.notify(`${formatAnalysisPlanStatus(plan)}\n已写入 ${path}。可切到 academic 模式。`, "info");
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

  if (!legacyTestApi) pi.registerCommand("brainstorm", {
    description: "研究方向头脑风暴：提出并比较可选问题，不做压力测试",
    handler: async (args, ctx) => {
      const subject = args.trim();
      pi.sendUserMessage(academicBrainstormRequest(subject), ctx.isIdle() ? {} : { deliverAs: "followUp" });
      ctx.ui.notify("已启动研究方向头脑风暴（不经过 /grill）。若要严格压力测试，请另开 /grill。", "info");
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
        if (!(await readActiveProject(ctx.cwd))) {
          ctx.ui.notify("请先使用 /init 初始化研究项目；未建仓时不会自动执行同行评审。", "warning");
          return;
        }
        const reviewSkill = _args.trim();
        activeAgentRuns.add(ctx.cwd);
        ctx.ui.notify(`正在使用${reviewSkill?.trim() ? ` Skill“${reviewSkill.trim()}”辅助的` : "默认"} 4 角色并发模拟评审；不会自动改稿。`, "info");
        const result = await runParallelPeerReview({
          root: ctx.cwd,
          project,
          ...(ctx.model?.provider === undefined ? {} : { provider: ctx.model.provider }),
          ...(ctx.model?.id === undefined ? {} : { model: ctx.model.id }),
          env: providerEnvironment(ctx.model?.provider),
          ...(reviewSkill ? { skillGuidance: reviewSkill } : {}),
          onEvent: async (event) => { await new RunEventLog(ctx.cwd, event.runId).append(event); },
        });
        pi.appendEntry("psyclaw:multi-agent-review", {
          runId: result.runId,
          status: result.status,
          outputPath: result.outputPath,
          adoption: "review-output-only",
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
      if (!(await readActiveProject(ctx.cwd))) {
        ctx.ui.notify("请先使用 /init 初始化研究项目，再运行 /loop。", "warning");
        return;
      }
      const objective = requested || project.goal;
      const request = [
        "运行一个有边界的 PsyClaw 研究循环，采用计划、执行、检查、修正的顺序推进当前研究阶段。",
        `本轮目标：${objective}`,
        "开始前读取 .psyclaw/project.json、notes/goal.md 和 notes/plan.md；如果当前对话或项目中存在经研究者确认的 /grill 研究规格，以该规格细化初始计划，但不得违反系统规则、AGENTS.md 或研究门禁。",
        "先识别当前最高优先级且前提已满足的一个任务，再使用可用工具实际推进。不要只描述准备做什么。普通项目文件写入、脚本和可恢复工具调用在已 /init 的项目中连续推进；原始数据覆盖、凭据、外部发布、破坏性操作仍遵守单独的安全边界。",
        "每完成一个实质步骤就检查产物、证据和计划是否一致。缺失信息若能检索、计算、重跑、改写或明确标注，应先自行修复。只有存在会改变研究问题、样本处理、操作化、估计目标、方法或解释的实质分歧时才请求研究者取舍；权限边界、不可恢复错误或当前阶段完成时停止。不得为了继续循环而虚构输入或结论。",
        "本次最多推进一个可验收的研究阶段。结束时简要报告已完成、已核验、阻塞、计划变化和下一步；规划内容不得表述为已有研究证据。",
      ].join("\n");
      pi.sendUserMessage(request, ctx.isIdle() ? {} : { deliverAs: "followUp" });
      ctx.ui.notify("已启动有界研究循环；使用 /loop stop 可请求中止", "info");
    },
  });

  for (const kind of ["skill", "hook", "rule", "subagent"] as const) {
    if (!legacyTestApi) pi.registerCommand(`create-${kind}`, {
      description: `预览并创建项目级 ${kind}（附带名称与需求文本）`,
      handler: async (args, ctx) => {
        const requirements = args.trim();
        if (!requirements) {
          ctx.ui.notify(`请使用 /create-${kind} <名称与需求描述>`, "info");
          return;
        }
        pi.sendUserMessage(creationCommandPrompt(kind, requirements), ctx.isIdle() ? {} : { deliverAs: "followUp" });
      },
    });
  }

  if (!legacyTestApi) pi.registerCommand("skill", {
    description: "打开 Skill 管理页",
    handler: async (_args, ctx) => {
      try { await showSkillManager(pi, ctx); } catch (error) { await notifyError(ctx, error); }
    },
  });

  if (!legacyTestApi) pi.registerCommand("ars", {
    description: "学术模式：单独开启，或附带任务文本启动完整流程",
    handler: async (args, ctx) => {
      try {
        const trailing = args.trim();
        if (!trailing) {
          if (!ctx.hasUI) {
            ctx.ui.notify("当前环境无编辑器；请改用 Shift+Tab 切换 academic。", "info");
            return;
          }
          arsUiContext = ctx;
          applySessionMode("academic");
          return;
        }
        const lower = trailing.toLowerCase();
        if (lower === "stop") {
          arsUiContext = ctx;
          applySessionMode("chat");
          if (ctx.hasUI && isArsModeEditorText(ctx.ui.getEditorText?.() ?? "")) {
            ctx.ui.setEditorText("");
          }
          ctx.ui.notify("已回到 chat 模式", "info");
          return;
        }
        if (lower === "doctor") {
          const activeTools = typeof pi.getActiveTools === "function" ? pi.getActiveTools() : [];
          const commands = typeof pi.getCommands === "function"
            ? pi.getCommands().map((command: { name: string }) => command.name)
            : [];
          const toolNames = [...new Set([
            ...activeTools.map((name: string) => String(name)),
            "psyclaw_ars_multi_agent",
          ])];
          const commandNames = [...new Set([...commands.map(String), "agents", "create-subagent"])];
          const report = await buildArsDoctorReport({
            repositoryRoot: arsRoot(),
            activeTools: toolNames,
            commands: commandNames,
            projectActive: Boolean(await readActiveProject(ctx.cwd)),
          });
          if (typeof pi.sendMessage === "function") {
            pi.sendMessage({ customType: "psyclaw-ars-doctor", content: report, display: true });
          } else {
            ctx.ui.notify(report, "info");
          }
          return;
        }
        // Any other trailing text is the academic full-pipeline task.
        if (!ctx.isIdle()) await ctx.waitForIdle();
        pi.sendUserMessage(`/ars-full ${trailing}`, {
          ...(!ctx.isIdle() ? { deliverAs: "followUp" as const } : {}),
          expandPromptTemplates: true,
        });
      } catch (error) {
        await notifyError(ctx, error);
      }
    },
  });

  if (!legacyTestApi) pi.registerCommand("plugin", {
    description: "打开 Plugin 推荐与管理页",
    handler: async (_args, ctx) => {
      try { await showPluginManager(ctx); } catch (error) { await notifyError(ctx, error); }
    },
  });

  if (!legacyTestApi) pi.registerCommand("mcp", {
    description: "打开 MCP 安装与配置管理页",
    handler: async (_args, ctx) => {
      try { await showMcpManager(pi, ctx, runtimeMcps); } catch (error) { await notifyError(ctx, error); }
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
        if (!/^[A-Za-z0-9._:-]+$/.test(requested)) throw new Error("请使用 /provider 打开选择，或 /provider <provider-id>");
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
          // Always show the credential step when switching a built-in
          // provider. An empty submission deliberately keeps an existing
          // environment/auth-store credential; this makes the flow explicit
          // and avoids silently skipping the key screen on another machine.
          const key = await promptProviderKey(ctx, preset.name, preset.apiKeyEnv);
          if (key === undefined) return;
          if (!key && credential === "missing") {
            throw new Error(`未找到 ${preset.apiKeyEnv}；请输入 API Key 后再继续`);
          }
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
    description: "启动横幅宠物：单独查看状态，或附带 on/off",
    handler: async (args, ctx) => {
      const action = args.trim().toLowerCase() || "status";
      if (action === "status") {
        ctx.ui.notify(`启动横幅宠物：${await petPreference() ? "已开启" : "已关闭（默认）"}`, "info");
        return;
      }
      if (action !== "on" && action !== "off") {
        ctx.ui.notify("请使用 /pet，或 /pet on|off", "error");
        return;
      }
      await setPetPreference(action === "on");
      ctx.ui.notify(`启动横幅宠物已${action === "on" ? "开启" : "关闭"}，下次启动生效`, "info");
    },
  });

  if (!legacyTestApi) pi.registerCommand("telemetry", {
    description: "查看或关闭匿名产品遥测",
    handler: async (args, ctx) => {
      const action = args.trim().toLowerCase() || "status";
      if (action === "status") {
        const preference = await readTelemetryPreference();
        ctx.ui.notify(
          preference.enabled
            ? "匿名产品遥测：开启（默认）。采集粗粒度使用与错误，不含研究正文。关闭：/telemetry off"
            : "匿名产品遥测：已关闭。重新开启：/telemetry on",
          "info",
        );
        return;
      }
      if (action !== "on" && action !== "off") {
        ctx.ui.notify("Usage: /telemetry on|off|status", "error");
        return;
      }
      await writeTelemetryPreference({ enabled: action === "on", noticeAcknowledged: true });
      ctx.ui.notify(action === "on" ? "已开启匿名产品遥测。下次启动生效。" : "已关闭匿名产品遥测。下次启动不再发送。", "info");
    },
  });

  if (typeof pi.registerTool === "function") {
  pi.registerTool({
    name: "psyclaw_research_decision",
    label: "Research decision",
    description: "Request researcher input only for an unresolved substantive research trade-off. Never use this for software, formatting, missing reporting fields, recoverable errors, evidence collection, credentials, publication, or other operational authorization.",
    parameters: Type.Object({
      id: Type.String({ minLength: 1 }),
      question: Type.String({ minLength: 1 }),
      options: Type.Array(Type.Object({
        id: Type.String({ minLength: 1 }),
        label: Type.String({ minLength: 1 }),
        rationale: Type.String({ minLength: 1 }),
        consequences: Type.Array(Type.String()),
        evidenceRefs: Type.Array(Type.String()),
      }), { minItems: 2 }),
      affectedAreas: Type.Array(Type.Union([
        Type.Literal("research-question"),
        Type.Literal("sample-treatment"),
        Type.Literal("operationalization"),
        Type.Literal("estimand"),
        Type.Literal("analysis-method"),
        Type.Literal("interpretation"),
      ]), { minItems: 1 }),
      evidenceCannotResolve: Type.Boolean(),
      evidenceReviewed: Type.Array(Type.String({ minLength: 1 }), { minItems: 1 }),
      methodsChecked: Type.Array(Type.String({ minLength: 1 }), { minItems: 1 }),
      unresolvedReason: Type.String({ minLength: 1 }),
      recommendation: Type.String({ minLength: 1 }),
    }),
    executionMode: "sequential",
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const run = await readActiveProject(ctx.cwd);
      if (!run) {
        return {
          content: [{ type: "text", text: "当前目录尚未 /init，不能进入研究决策状态。请先执行 /init。" }],
          details: { status: "general-mode" },
          isError: true,
        };
      }
      const request = {
        schemaVersion: "psyclaw/research-decision/v1" as const,
        id: params.id,
        question: params.question,
        options: params.options,
        affectedAreas: params.affectedAreas as ResearchDecisionImpact[],
        evidenceCannotResolve: params.evidenceCannotResolve,
        evidenceReviewed: params.evidenceReviewed,
        methodsChecked: params.methodsChecked,
        unresolvedReason: params.unresolvedReason,
        recommendation: params.recommendation,
      };
      try {
        assertResearchDecision(request);
      } catch (error) {
        return {
          content: [{ type: "text", text: `该事项不符合研究取舍条件：${error instanceof Error ? error.message : String(error)}。请继续检索、计算、修复，或按单独的安全授权边界处理。` }],
          details: { status: "not-a-research-decision", runId: run.runId },
          isError: true,
        };
      }
      const eventLog = new RunEventLog(ctx.cwd, run.runId);
      const events = await eventLog.snapshot();
      const resolvedIds = new Set(events
        .filter((event) => event.type === "decision-resolved" && event.researchDecisionResolution)
        .map((event) => event.researchDecisionResolution!.decisionId));
      const pending = findLastMatching(events, (event) =>
        event.type === "awaiting-human" && Boolean(event.researchDecision && !resolvedIds.has(event.researchDecision.id)));
      if (pending?.researchDecision) {
        return {
          content: [{ type: "text", text: `当前已有一项待研究者取舍的问题：${pending.researchDecision.question}。请先处理该问题，不能同时创建第二项。` }],
          details: { status: "research-decision-already-pending", runId: run.runId, decisionId: pending.researchDecision.id },
          isError: true,
        };
      }
      if (events.some((event) => event.researchDecision?.id === request.id || event.researchDecisionResolution?.decisionId === request.id)) {
        return {
          content: [{ type: "text", text: `研究取舍编号已使用：${request.id}` }],
          details: { status: "duplicate-research-decision", runId: run.runId, decisionId: request.id },
          isError: true,
        };
      }
      await eventLog.append({
        type: "awaiting-human",
        at: new Date().toISOString(),
        researchDecision: request,
        message: request.question,
      });
      return {
        content: [{ type: "text", text: JSON.stringify({ status: "需要研究者取舍", runId: run.runId, decision: request }, null, 2) }],
        details: { status: "awaiting-human", runId: run.runId, decisionId: request.id },
      };
    },
  });

  pi.registerTool({
    name: "psyclaw_resolve_research_decision",
    label: "Resolve research decision",
    description: "Record the researcher's answer to the current substantive research trade-off and resume the controlled workflow. This is not an operational approval tool.",
    parameters: Type.Object({
      decisionId: Type.String({ minLength: 1 }),
      selectedOption: Type.String({ minLength: 1 }),
      rationale: Type.String({ minLength: 1 }),
    }),
    executionMode: "sequential",
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const run = await readActiveProject(ctx.cwd);
      if (!run) {
        return { content: [{ type: "text", text: "当前目录尚未 /init，没有有效的研究项目。" }], details: { status: "general-mode" }, isError: true };
      }
      const eventLog = new RunEventLog(ctx.cwd, run.runId);
      const events = await eventLog.snapshot();
      const resolvedIds = new Set(events
        .filter((event) => event.type === "decision-resolved" && event.researchDecisionResolution)
        .map((event) => event.researchDecisionResolution!.decisionId));
      const pending = findLastMatching(events, (event) =>
        event.type === "awaiting-human" && event.researchDecision?.id === params.decisionId && !resolvedIds.has(params.decisionId));
      if (!pending?.researchDecision) {
        return { content: [{ type: "text", text: `未找到待处理的研究取舍：${params.decisionId}` }], details: { status: "not-found", runId: run.runId }, isError: true };
      }
      try {
        const resolution = resolveResearchDecision(pending.researchDecision, {
          selectedOption: params.selectedOption,
          rationale: params.rationale,
        });
        await eventLog.append({ type: "decision-resolved", at: resolution.resolvedAt, researchDecisionResolution: resolution });
        return {
          content: [{ type: "text", text: JSON.stringify({ status: "executing", runId: run.runId, resolution }, null, 2) }],
          details: { status: "executing", runId: run.runId, decisionId: resolution.decisionId },
        };
      } catch (error) {
        return { content: [{ type: "text", text: error instanceof Error ? error.message : String(error) }], details: { status: "invalid-resolution", runId: run.runId }, isError: true };
      }
    },
  });

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
        if (!(await readActiveProject(ctx.cwd))) {
          return {
            content: [{ type: "text", text: "当前目录尚未 /init。可以查看 MCP 工具，但实际调用需先运行 /init。" }],
            details: { action: "call", status: "general-mode" },
            isError: true,
          };
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
    name: "psyclaw_ars_multi_agent",
    label: "ARS multi-agent review bridge",
    description: "Run ARS reviewer_full Stage 3 as five process-separated read-only reviewer seats, or Stage 3 re-review as three ordered fenced calls. This is a parallel-agent / multi-agent / subagent workflow capability; it preserves ARS checkpoints and never claims independent error processes.",
    parameters: Type.Object({
      mode: Type.Union([Type.Literal("reviewer_full"), Type.Literal("reviewer_re_review")]),
      manuscriptPath: Type.Optional(Type.String()),
      originalManuscriptPath: Type.Optional(Type.String()),
      roadmapPath: Type.Optional(Type.String()),
      authorAdjudicationPath: Type.Optional(Type.String()),
      revisionEvidenceBundlePath: Type.Optional(Type.String()),
      responseLetterPath: Type.Optional(Type.String()),
      editorialDecisionPath: Type.Optional(Type.String()),
      round1FindingsPath: Type.Optional(Type.String()),
      reviewerCardsPath: Type.Optional(Type.String()),
      revisionPatchPaths: Type.Optional(Type.Array(Type.String(), { maxItems: 50 })),
      applyReportPaths: Type.Optional(Type.Array(Type.String(), { maxItems: 50 })),
      resumeRunId: Type.Optional(Type.String()),
      reviewerCards: Type.Optional(Type.String({ maxLength: 40000 })),
      title: Type.Optional(Type.String()), field: Type.Optional(Type.String()), passportDigest: Type.Optional(Type.String()),
    }),
    executionMode: "sequential",
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      try {
        if (!isArsPiActive(ctx.sessionManager)) throw new Error("ARS mode is not active");
        if (!contextProjectTrusted(ctx)) throw new Error("project is not trusted");
        if (!ctx.hasUI || typeof ctx.ui?.confirm !== "function") throw new Error("ARS external model dispatch requires interactive confirmation");
        const paths = [params.manuscriptPath, params.originalManuscriptPath, params.roadmapPath, params.authorAdjudicationPath, params.revisionEvidenceBundlePath, params.responseLetterPath, params.editorialDecisionPath, params.round1FindingsPath, params.reviewerCardsPath, ...(params.revisionPatchPaths ?? []), ...(params.applyReportPaths ?? [])].filter((value): value is string => typeof value === "string");
        const approved = await ctx.ui.confirm("将研究材料发送给当前模型 Provider？", `模式：${params.mode}\nProvider/Model：${ctx.model?.provider ?? "unknown"}/${ctx.model?.id ?? "unknown"}\n文件：\n${paths.map((path) => `- ${path}`).join("\n")}\n\nStage 3 可能至少产生 11 次模型调用；进程隔离不代表误差独立。`);
        if (!approved) throw new Error("ARS dispatch cancelled; no material was sent");
        const result = await runArsMultiAgentBridge(params as ArsPanelRequest, { root: ctx.cwd, ...(ctx.model?.provider ? { provider: ctx.model.provider } : {}), ...(ctx.model?.id ? { model: ctx.model.id } : {}), env: providerEnvironment(ctx.model?.provider), agentDir: join(ctx.cwd, ".psyclaw", "ars-agent") });
        return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }], details: result, ...(result.status === "blocked" ? { isError: true } : {}) };
      } catch (error) {
        return { content: [{ type: "text", text: `ARS multi-agent bridge failed: ${error instanceof Error ? error.message : String(error)}` }], details: { status: "blocked" }, isError: true };
      }
    },
  });

  pi.registerTool({
    name: "psyclaw_ensure_pdf_engine",
    label: "Ensure PDF engine",
    description: "Install or locate a PDF engine (tectonic/xelatex) only when the user explicitly asked to export PDF. Do not call during /ars doctor or ordinary startup checks.",
    parameters: Type.Object({}),
    executionMode: "sequential",
    async execute() {
      const result = await ensurePdfEngineForExport();
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
        details: result,
        ...(result.status === "missing" || result.status === "unsupported-platform" ? { isError: true } : {}),
      };
    },
  });

  pi.registerTool({
    name: "psyclaw_create",
    label: "Create project capability",
    description: "Preview and, after an explicit UI confirmation, create one PsyClaw-native project Skill, declarative analysis Hook, additive Rule, or Subagent (Claude-style). Elevated subagent effects require confirmation at create and again at each /agents run.",
    parameters: Type.Object({
      kind: Type.Union([Type.Literal("skill"), Type.Literal("hook"), Type.Literal("rule"), Type.Literal("subagent")]),
      id: Type.String({ minLength: 1, maxLength: 64 }),
      description: Type.String({ minLength: 1, maxLength: 1024 }),
      instructions: Type.Optional(Type.String({ maxLength: 8000 })),
      event: Type.Optional(Type.Union([Type.Literal("before-plan"), Type.Literal("before-analysis"), Type.Literal("before-delegation"), Type.Literal("before-write"), Type.Literal("after-analysis"), Type.Literal("before-report"), Type.Literal("after-report")])),
      severity: Type.Optional(Type.Union([Type.Literal("warn"), Type.Literal("block")])),
      pattern: Type.Optional(Type.String({ maxLength: 500 })),
      pathPrefix: Type.Optional(Type.String({ maxLength: 200 })),
      role: Type.Optional(Type.Union([Type.Literal("planner"), Type.Literal("researcher"), Type.Literal("analyst"), Type.Literal("critic"), Type.Literal("writer"), Type.Literal("verifier")])),
      allowedEffects: Type.Optional(Type.Array(Type.Union([
        Type.Literal("read"),
        Type.Literal("write"),
        Type.Literal("network"),
        Type.Literal("destructive"),
      ]), { maxItems: 4 })),
    }),
    executionMode: "sequential",
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      try {
        if (!contextProjectTrusted(ctx)) throw new Error("project is not trusted");
        const request = params as CreationRequest;
        const preview = await previewCreation(ctx.cwd, request);
        if (!ctx.hasUI || typeof ctx.ui?.confirm !== "function") {
          return { content: [{ type: "text", text: JSON.stringify({ ...preview, status: "preview-only", reason: "interactive confirmation unavailable" }, null, 2) }], details: preview };
        }
        const effects = request.kind === "subagent" ? normalizeEffects(request.allowedEffects) : ["read" as const];
        const elevated = request.kind === "subagent" && hasElevatedEffects(effects);
        const title = elevated
          ? `创建 Subagent “${preview.id}”（含提升权限）？`
          : `创建 ${params.kind} “${preview.id}”？`;
        const body = elevated
          ? `目标：${preview.path}\n声明 effects：${formatEffects(effects)}\n将开放工具：${toolsForEffects(effects).join(", ")}\nSHA-256：${preview.sha256}\n\n每次 /agents 运行仍会再次确认。凭据读取与绕过门禁仍被禁止。\n\n${preview.contents}`
          : `目标：${preview.path}\nSHA-256：${preview.sha256}\n\n${preview.contents}`;
        const approved = await ctx.ui.confirm(title, body);
        if (!approved) return { content: [{ type: "text", text: "Creation cancelled; no file was written." }], details: { status: "cancelled", preview } };
        const result = await applyCreation(ctx.cwd, request, preview.sha256, true);
        return { content: [{ type: "text", text: JSON.stringify({ status: "created", path: result.preview.path, sha256: result.preview.sha256, receipt: result.receipt }, null, 2) }], details: result };
      } catch (error) {
        return { content: [{ type: "text", text: `Creation failed: ${error instanceof Error ? error.message : String(error)}` }], details: { status: "failed" }, isError: true };
      }
    },
  });

  pi.registerTool({
    name: "psyclaw_skill",
    label: "Research skill",
    description: "Load one trusted bundled psyclaw core skill and make its use visible to the user. Use this instead of directly reading a core SKILL.md file.",
    parameters: Type.Object({
      name: Type.String({ description: "Core skill name: academic-grill, research-intake, evidence-capture, citation-audit, or analysis-plan" }),
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
    description: "Primary psyclaw workbench for durable research state, evidence tracking, academic analysis/report contracts, separate operational authorization, and recoverable workflows. Infer the workflow from natural language, or pass an explicit `workflow` id to run it directly. Workflows: meta-analysis (real OpenAlex literature search, effect-size dataset contract at data/clean/effects.csv, R metafor delegation for REML / I² / Egger / forest — psyclaw never fabricates statistics), literature-review, analysis-delegation, writing-review, expert-review, institutional-fulltext. For paper/full-text requests call this first; for data analysis or academic reports route through research-intake -> evidence-capture -> citation-audit and record figure/document deliverables. Use psyclaw_research_decision only for qualifying substantive research trade-offs. Do not handle credentials.",
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
        // Soft gate for missing /init only. Analysis/academic completion still requires human verify.
        const project = await readActiveProject(ctx.cwd);
        const softNote = project
          ? undefined
          : "尚未 /init（软门禁）：继续执行；收尾前须 AI /crosscheck 后人审。建议先 /init 建仓。";
        const request = params.request.trim();
        const combined = `${request} ${params.identifier ?? ""}`;
        const explicitWorkflow = params.workflow?.trim();
        if (explicitWorkflow) {
          const result = await runWorkflowTool(ctx.cwd, explicitWorkflow, params.target, params.nStudies);
          if (softNote && result && typeof result === "object" && "content" in result) {
            const text = Array.isArray(result.content) ? result.content.map((part: { text?: string }) => part.text ?? "").join("\n") : "";
            return {
              ...result,
              content: [{ type: "text", text: `${softNote}\n${text}` }],
            };
          }
          return result;
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
            const gate = await assertHumanVerifyGate(ctx.cwd, "academic-finalize");
            if (!gate.ok) {
              return {
                content: [{ type: "text", text: gate.message }],
                details: { workflow: "publish-manuscript", blocked: true, reason: "human-verify-gate" },
              };
            }
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
              requiredSkills: ["research-intake", "evidence-capture", "citation-audit"],
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
              message: "Proceed through the four core skills. Before presenting the report as final, resolve or plainly disclose outstanding citations, figures, and document-format requirements; keep internal workflow status labels out of reader-facing prose.",
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
            status: "awaiting-access-confirmation",
            verdict: result.verdict,
            runId: result.runId,
            outputs: result.outputPaths,
            next: "Ask the user to complete institutional login in the visible browser and confirm the exact article before any download. This is an access-control confirmation, not a research-method decision.",
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
    name: "psyclaw_record_choice",
    label: "记录选择",
    description: "记录研究者对选项的回应。结构化唤醒选项或直接文本回应都必须记录；直接回应需保留原文并填写解析后的选项。",
    parameters: Type.Object({
      prompt: Type.String({ minLength: 1, description: "当时向研究者提出的问题或选择提示" }),
      originalResponse: Type.String({ minLength: 1, description: "研究者的原始回应，不能改写或省略" }),
      selectedIds: Type.Array(Type.String(), { description: "解析后的选项 ID；无法明确解析时为空" }),
      selectedLabels: Type.Array(Type.String(), { description: "解析后的选项名称" }),
      source: Type.Union([Type.Literal("tool"), Type.Literal("free-text")]),
      context: Type.Optional(Type.String({ description: "选择发生时的研究或任务上下文" })),
    }),
    executionMode: "sequential",
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      try {
        const record = await appendChoiceRecord(ctx.cwd, {
          prompt: params.prompt,
          originalResponse: params.originalResponse,
          selectedIds: params.selectedIds,
          selectedLabels: params.selectedLabels,
          source: params.source as ChoiceRecordSource,
          ...(params.context === undefined ? {} : { context: params.context }),
        });
        return { content: [{ type: "text", text: JSON.stringify(record, null, 2) }], details: record };
      } catch (error) {
        return { content: [{ type: "text", text: `选择记录失败：${error instanceof Error ? error.message : String(error)}` }], details: { status: "failed" }, isError: true };
      }
    },
  });

  pi.registerTool({
    name: "psyclaw_wake_options",
    label: "唤醒选项",
    description: "向研究者弹出结构化选择或核对清单勾选（唤醒选项）。当用户在 Panel 中交互时优先弹窗；同时在 CLI 渲染同等选项。适用于：单选/多选决策、核对清单勾选、确认下一步。不要用自由文本「请回复选项编号」替代本工具。",
    parameters: Type.Object({
      title: Type.String({ minLength: 1, description: "弹窗标题，例如「选择下一步」或「分析前核对」" }),
      prompt: Type.Optional(Type.String({ description: "可选说明文字" })),
      mode: Type.Union([Type.Literal("choice"), Type.Literal("checklist")], {
        description: "choice=单选弹窗；checklist=可多选勾选（可同步到核对清单）",
      }),
      options: Type.Array(Type.Object({
        id: Type.String({ minLength: 1 }),
        label: Type.String({ minLength: 1 }),
        description: Type.Optional(Type.String()),
        checked: Type.Optional(Type.Boolean()),
      }), { minItems: 1 }),
      allowMultiple: Type.Optional(Type.Boolean()),
      minSelections: Type.Optional(Type.Number()),
      syncVerify: Type.Optional(Type.Boolean({ description: "checklist 模式下是否写入 .psyclaw/verify-checklist.json（默认 true）" })),
      timeoutMs: Type.Optional(Type.Number()),
    }),
    executionMode: "sequential",
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      try {
        const wakePrompt = buildWakePrompt({
          title: params.title,
          mode: params.mode,
          options: params.options.map((option) => ({
            id: option.id,
            label: option.label,
            ...(option.description === undefined ? {} : { description: option.description }),
            ...(option.checked === undefined ? {} : { checked: option.checked }),
          })),
          ...(params.prompt === undefined ? {} : { prompt: params.prompt }),
          ...(params.allowMultiple === undefined ? {} : { allowMultiple: params.allowMultiple }),
          ...(params.minSelections === undefined ? {} : { minSelections: params.minSelections }),
          ...(params.syncVerify === undefined ? {} : { syncVerify: params.syncVerify }),
          ...(params.timeoutMs === undefined ? {} : { timeoutMs: params.timeoutMs }),
        });
        if (wakePrompt.mode === "checklist") {
          await createWakeVerifyChecklist(ctx.cwd, wakePrompt);
        }
        const timeoutMs = Math.max(5_000, new Date(wakePrompt.expiresAt).getTime() - Date.now());
        const panelClients = panelHub.subscriberCount();
        if (ctx.hasUI) {
          ctx.ui.notify(
            panelClients > 0
              ? `唤醒选项已推送到 Panel（${wakePrompt.title}）；CLI 也可作答`
              : `唤醒选项：${wakePrompt.title}（Panel 未连接时仅 CLI）`,
            "info",
          );
        }

        const panelPromise = waitForPanelWakeAnswer(wakePrompt, timeoutMs).then((answer) => ({ ...answer, raced: "panel" as const }));

        const cliPromise = (async (): Promise<WakeOptionsAnswer & { raced: "cli" }> => {
          if (!ctx.hasUI || typeof ctx.ui.custom !== "function") {
            if (panelClients === 0) {
              return { promptId: wakePrompt.id, selectedIds: [], source: "cancel", raced: "cli" };
            }
            await new Promise<void>((resolve) => {
              if (signal?.aborted) resolve();
              else signal?.addEventListener("abort", () => resolve(), { once: true });
            });
            return { promptId: wakePrompt.id, selectedIds: [], source: "cancel", raced: "cli" };
          }
          const uiResult = await ctx.ui.custom((tui, theme, keybindings, done) => new WakeOptionsComponent(
            wakePrompt.title,
            wakePrompt.prompt,
            wakePrompt.mode,
            wakePrompt.options,
            Boolean(wakePrompt.allowMultiple),
            wakePrompt.minSelections ?? 0,
            tui,
            theme,
            keybindings,
            done,
          ), { overlay: true });
          if (!uiResult || (uiResult as { type?: string }).type === "cancel") {
            return { promptId: wakePrompt.id, selectedIds: [], source: "cancel", raced: "cli" };
          }
          const selectedIds = (uiResult as { selectedIds?: string[] }).selectedIds ?? [];
          return { promptId: wakePrompt.id, selectedIds, source: "cli", raced: "cli" };
        })();

        const winner = await Promise.race([panelPromise, cliPromise]);
        // If CLI answered first, close the Panel waiter so the SSE prompt dismisses.
        if (winner.raced === "cli") {
          panelHub.resolveWake({
            promptId: wakePrompt.id,
            selectedIds: winner.selectedIds,
            source: winner.source === "cancel" ? "cancel" : "cli",
          });
        }

        if (signal?.aborted) {
          return {
            content: [{ type: "text", text: formatWakeResult({
              status: "cancelled",
              source: "cancel",
              selectedIds: [],
              selectedLabels: [],
              panelClients,
            }) }],
            details: { status: "cancelled" },
            isError: true,
          };
        }

        let status: WakeOptionsResult["status"] = "answered";
        if (winner.source === "timeout") status = "timeout";
        else if (winner.source === "cancel") status = "cancelled";

        const verifySynced = status === "answered"
          ? await applyWakeVerifySync(ctx.cwd, wakePrompt, winner.selectedIds)
          : false;

        const result: WakeOptionsResult = {
          status,
          source: winner.source,
          selectedIds: winner.selectedIds,
          selectedLabels: labelsFor(wakePrompt, winner.selectedIds),
          panelClients,
          verifySynced,
          ...(winner.notes ? { notes: winner.notes } : {}),
        };

        if (result.status !== "answered") {
          return {
            content: [{ type: "text", text: formatWakeResult(result) }],
            details: result,
            isError: true,
          };
        }
        return {
          content: [{ type: "text", text: formatWakeResult(result) }],
          details: result,
        };
      } catch (error) {
        return {
          content: [{ type: "text", text: `唤醒选项失败：${error instanceof Error ? error.message : String(error)}` }],
          details: { status: "failed" },
          isError: true,
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
        if (!(await readActiveProject(ctx.cwd))) {
          return {
            content: [{ type: "text", text: "当前目录尚未 /init；请先运行 /init，之后才会启用引用归档与论文证据门禁。" }],
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

  // Read-only multi-agent research is a user-facing capability.  Keep the
  // destructive/developer commands gated, but do not hide the bounded agent
  // runner behind PSYCLAW_DEVELOPER_COMMANDS in published builds.
  if (!legacyTestApi) pi.registerCommand("agents", {
    description: "浏览 Subagent，或附带任务文本运行",
    handler: async (args, ctx) => {
      const objective = args.trim();
      if (!objective) {
        try { await showAgentManager(ctx, false); }
        catch (error) { await notifyError(ctx, error); }
        return;
      }
      if (objective.length > 4_000) {
        ctx.ui.notify("Agent task is too long; split it into smaller bounded tasks", "error");
        return;
      }
      try {
        await readProject(ctx.cwd);
      } catch {
        ctx.ui.notify("请先使用 /init 初始化研究项目，再运行 /agents", "warning");
        return;
      }
      if (activeAgentRuns.has(ctx.cwd)) {
        ctx.ui.notify("A psyclaw agent run is already active for this project", "warning");
        return;
      }
      activeAgentRuns.add(ctx.cwd);
      try {
        const runId = `pi_agent_${Date.now()}`;
        const plan: Plan = researchTaskPlan(runId, objective);
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
