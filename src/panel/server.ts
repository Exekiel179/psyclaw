import { createServer, type Server } from "node:http";
import { randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import { lstat, mkdir, readFile, readdir, unlink, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import { listRuns, projectRunSnapshot } from "./projection.js";
import { readSessionUsage } from "./usage.js";
import { buildClaimLiteratureMap } from "./literature-map.js";
import { discoverAgents } from "../agents/discover.js";
import { KNOWN_AGENTS } from "../agents/catalog.js";
import { planAgentInstall } from "../install/installer.js";
import { deepSeekProviderSpec, PiModelGateway, type ModelDescriptor } from "../adapters/pi/model.js";
import { PROVIDER_PRESETS, saveProviderConfig } from "../setup.js";
import { readHitlWorkspace } from "../project/hitl.js";
import { assertSafeProjectPath, projectPaths } from "../project/paths.js";
import { readManuscript } from "../project/manuscript.js";
import { appendJsonlIfMissing, atomicWriteFile, readJsonl } from "../project/jsonl.js";
import { appendClaim, appendClaimEvidenceLink, appendEvidence, loadLedger, type LedgerSnapshot } from "../research/ledger.js";
import { publishManuscript } from "../workflows/publish.js";
import type { Claim, ClaimKind, ClaimStatus, Evidence } from "../core/contracts.js";
import { sha256File, sha256Text } from "../core/hash.js";
import { docxToMarkdown } from "../core/docx.js";
import { verifyDoi, lookupOaPdfUrl } from "../core/doi.js";
import { checkCitations, listReferences, referenceFromVerification, upsertReference } from "../core/references.js";
import { listCitationUses, recordCitationUse } from "../core/citations.js";
import { readPublishedVersions } from "../workflows/publish.js";
// Backward-compatible re-export: existing tests import verifyDoi from the panel server.
export { verifyDoi } from "../core/doi.js";
import { resumePlanWithPi } from "../orchestration/pi-executor.js";
import { RunEventLog } from "./events.js";
import { PSYCLAW_IDENTITY_PROMPT } from "../branding.js";

const activePanelRuns = new Set<string>();

interface RecommendationState { schemaVersion: "psyclaw/recommendation-state/v1"; skills: string[]; mcp: string[]; }

async function readRecommendationState(root: string): Promise<RecommendationState> {
  try {
    const value = JSON.parse(await readFile(join(root, ".psyclaw", "recommendations.json"), "utf8")) as Partial<RecommendationState>;
    return { schemaVersion: "psyclaw/recommendation-state/v1", skills: Array.isArray(value.skills) ? value.skills.filter((id): id is string => typeof id === "string") : [], mcp: Array.isArray(value.mcp) ? value.mcp.filter((id): id is string => typeof id === "string") : [] };
  } catch { return { schemaVersion: "psyclaw/recommendation-state/v1", skills: [], mcp: [] }; }
}

async function writeRecommendationState(root: string, state: RecommendationState): Promise<void> {
  await atomicWriteFile(await assertSafeProjectPath(root, ".psyclaw/recommendations.json"), `${JSON.stringify({ ...state, skills: [...new Set(state.skills)].sort(), mcp: [...new Set(state.mcp)].sort() }, null, 2)}\n`);
}

/** The bundled core skills, always listed so the user can disable (not uninstall) them. */
const CORE_SKILLS = [
  { id: "research-intake", name: "研究入口" },
  { id: "evidence-capture", name: "证据登记" },
  { id: "citation-audit", name: "引用审计" },
  { id: "research-brief", name: "研究简报" },
] as const;

interface DisabledCapabilities { coreSkills: string[] }

async function readDisabledCapabilities(root: string): Promise<DisabledCapabilities> {
  try {
    const value = JSON.parse(await readFile(join(root, ".psyclaw", "disabled-capabilities.json"), "utf8")) as Partial<DisabledCapabilities>;
    return { coreSkills: Array.isArray(value.coreSkills) ? value.coreSkills.filter((id): id is string => typeof id === "string") : [] };
  } catch { return { coreSkills: [] }; }
}

async function writeDisabledCapabilities(root: string, state: DisabledCapabilities): Promise<void> {
  await atomicWriteFile(await assertSafeProjectPath(root, ".psyclaw/disabled-capabilities.json"), `${JSON.stringify({ ...state, coreSkills: [...new Set(state.coreSkills)].sort() }, null, 2)}\n`);
}

/** Persist a manuscript to a real project file under notes/ or outputs/ with a receipt. */
async function writeManuscript(root: string, relative: string, content: string): Promise<{ path: string; bytes: number; receiptPath: string }> {
  const rel = relative.replaceAll("\\", "/");
  if (rel.split("/").some((part) => part === ".." || part === "")) throw new Error("a relative manuscript path is required");
  if (!/\.(md|markdown|doc|docx|txt)$/i.test(rel)) throw new Error("manuscript must be .md/.markdown/.doc/.docx/.txt");
  if (!rel.startsWith("notes/") && !rel.startsWith("outputs/")) throw new Error("manuscript must be under notes/ or outputs/");
  const target = await assertSafeProjectPath(root, rel);
  const stat = await lstat(target).catch(() => undefined);
  if (stat !== undefined && (stat.isSymbolicLink() || !stat.isFile())) throw new Error("manuscript must be a regular file");
  await atomicWriteFile(target, content.endsWith("\n") ? content : `${content}\n`);
  const runId = `panel_${randomUUID().replaceAll("-", "")}`;
  const receipt = {
    schemaVersion: "psyclaw/tool-receipt/v1",
    runId,
    taskId: "panel.manuscript.save",
    tool: "panel.manuscript.save",
    effect: "write",
    approval: "approved",
    idempotencyKey: `panel:manuscript:${sha256Text(`${rel}\u0000${content}`).slice(0, 24)}`,
    ok: true,
    startedAt: new Date().toISOString(),
    finishedAt: new Date().toISOString(),
  };
  const receiptPath = await assertSafeProjectPath(root, `.psyclaw/manifests/${runId}.receipt.json`);
  await atomicWriteFile(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`);
  return { path: rel, bytes: Buffer.byteLength(content, "utf8"), receiptPath };
}

const CLAIM_KINDS = new Set<ClaimKind>(["existence", "definition", "method", "result", "interpretation"]);
const CLAIM_STATUSES = new Set<ClaimStatus>(["supported", "uncertain", "unsupported"]);

/** Append a claim to the real `.psyclaw/claims.jsonl` ledger (append-only). */
async function appendLedgerClaim(root: string, body: Record<string, unknown>): Promise<Claim> {
  const text = String(body.text ?? "").trim();
  const kind = String(body.kind ?? "result") as ClaimKind;
  const status = String(body.status ?? "uncertain") as ClaimStatus;
  const uncertainty = body.uncertainty === undefined ? undefined : String(body.uncertainty).trim();
  if (!text) throw new Error("claim text is required");
  if (!CLAIM_KINDS.has(kind)) throw new Error(`unsupported claim kind: ${kind}`);
  if (!CLAIM_STATUSES.has(status)) throw new Error(`unsupported claim status: ${status}`);
  const claim: Claim = {
    id: `claim_${sha256Text(text).slice(0, 16)}`,
    text,
    kind,
    evidenceIds: [],
    status,
    ...(uncertainty === undefined || uncertainty === "" ? {} : { uncertainty }),
  };
  await appendClaim(root, claim);
  return claim;
}

/** Append evidence to the real `.psyclaw/evidence.jsonl` and link it to a claim. */
async function appendLedgerEvidence(root: string, body: Record<string, unknown>): Promise<{ evidence: Evidence; link: { claimId: string; evidenceId: string; relation: "supports" } }> {
  const claimId = String(body.claimId ?? "").trim();
  const title = String(body.title ?? "").trim();
  const doi = String(body.doi ?? "").trim();
  const quote = String(body.quote ?? "").trim();
  if (!claimId) throw new Error("claimId is required to attach evidence");
  if (!title && !doi && !quote) throw new Error("at least one of title / doi / quote is required");
  const locator = doi || title || quote.slice(0, 80);
  const id = `evidence_${sha256Text(`${locator}\u0000${quote}`).slice(0, 16)}`;
  const evidence: Evidence = {
    id,
    source: { kind: doi ? "doi" : "url", locator, ...(title === "" ? {} : { title }) },
    level: "snippet",
    ...(quote === "" ? {} : { quote }),
    retrievedAt: new Date().toISOString(),
    // The panel records provenance, never independent verification: the
    // accessStatus stays "partial" until a separate audit approves it.
    accessStatus: "partial",
    locators: doi ? [{ kind: "doi", value: doi }] : [],
  };
  await appendEvidence(root, evidence);
  await appendClaimEvidenceLink(root, { claimId, evidenceId: evidence.id, relation: "supports", rationale: "panel evidence auditor binding" });
  return { evidence, link: { claimId, evidenceId: evidence.id, relation: "supports" } };
}

/**
 * Standardized document locations (see docs/文档规范.md):
 *   paper/  → manuscripts (.md editable source, .docx/.pdf exports)
 *   docs/   → supplementary documentation
 *   data/   → raw + clean datasets
 *   outputs/→ workflow artifacts / reports
 * Any root-level document (questionnaire exports etc.) is listed as well.
 */
const DOCUMENT_EXTENSIONS = new Set(["md", "markdown", "docx", "doc", "pdf", "xlsx", "xls", "csv", "txt"]);
const DOCUMENT_SKIP_DIRS = [".psyclaw", ".git", "node_modules", "analysis/scripts", "analysis/results", "analysis/configs", "artifacts", "logs", "paper/archive"];

export interface ProjectDocument {
  path: string;
  format: string;
  kind: "manuscript" | "reference" | "data" | "report" | "document";
  bytes: number;
  sha256: string;
  imported: boolean;
  isManuscript: boolean;
}

/** Classify a document by its location and extension (shared by scan + import). */
function classifyDocumentKind(relative: string, extension: string): ProjectDocument["kind"] {
  return relative.startsWith("paper/") || relative.startsWith("docs/")
    ? (extension === "md" || extension === "markdown" || extension === "docx" || extension === "doc" ? "manuscript" : "reference")
    : relative.startsWith("data/")
      ? "data"
      : relative.startsWith("outputs/")
        ? "report"
        : "document";
}

async function scanDocuments(root: string): Promise<Array<Omit<ProjectDocument, "sha256" | "imported" | "isManuscript">>> {
  const found: Array<{ path: string; format: string; kind: ProjectDocument["kind"]; bytes: number }> = [];
  const walk = async (directory: string, prefix: string, depth: number): Promise<void> => {
    if (depth > 4) return;
    let entries: import("node:fs").Dirent[] = [];
    try { entries = await readdir(directory, { withFileTypes: true }); } catch { return; }
    for (const entry of entries) {
      const relative = prefix ? `${prefix}/${entry.name}` : entry.name;
      const normalized = relative.replaceAll("\\", "/");
      if (DOCUMENT_SKIP_DIRS.some((blocked) => normalized === blocked || normalized.startsWith(`${blocked}/`))) continue;
      if (/credential|secret|\.env|session-[^/]*\.html/i.test(entry.name)) continue;
      const absolute = join(directory, entry.name);
      if (entry.isDirectory()) {
        await walk(absolute, normalized, depth + 1);
        continue;
      }
      const extension = entry.name.split(".").pop()?.toLowerCase() ?? "";
      if (!DOCUMENT_EXTENSIONS.has(extension)) continue;
      const stat = await lstat(absolute).catch(() => undefined);
      if (!stat?.isFile()) continue;
      found.push({ path: normalized, format: extension, kind: classifyDocumentKind(normalized, extension), bytes: stat.size });
    }
  };
  await walk(root, "", 0);
  return found.sort((left, right) => left.path.localeCompare(right.path));
}

interface ImportRecord {
  schemaVersion: "psyclaw/import/v1";
  path: string;
  format: string;
  kind: string;
  bytes: number;
  sha256: string;
  converted: boolean;
  markdownLength: number;
  evidenceId: string;
  importedAt: string;
}

async function importsPath(root: string): Promise<string> {
  return assertSafeProjectPath(root, ".psyclaw/imports.jsonl");
}

/** Import a document: convert docx→md, register evidence, dedupe by sha256. */
async function importDocument(root: string, relative: string): Promise<{ record: ImportRecord; markdown: string | null }> {
  const rel = relative.replaceAll("\\", "/");
  if (rel.split("/").some((part) => part === ".." || part === "")) throw new Error("a relative document path is required");
  const target = await assertSafeProjectPath(root, rel);
  const stat = await lstat(target);
  if (stat.isSymbolicLink() || !stat.isFile()) throw new Error("document must be a regular file");
  const extension = rel.split(".").pop()?.toLowerCase() ?? "";
  if (!DOCUMENT_EXTENSIONS.has(extension)) throw new Error(`unsupported document format: ${extension}`);
  const bytes = stat.size;
  const sha256 = await sha256File(target);
  const existing = (await readJsonl<ImportRecord>(await importsPath(root))).find((record) => record.sha256 === sha256);
  if (existing) return { record: existing, markdown: null };

  let markdown: string | null = null;
  if (extension === "md" || extension === "markdown") {
    markdown = await readFile(target, "utf8");
  } else if (extension === "docx") {
    markdown = await docxToMarkdown(target);
  }

  const kind = classifyDocumentKind(rel, extension);
  const evidenceId = `evidence_${sha256.slice(0, 16)}`;
  const evidence = {
    id: evidenceId,
    source: { kind: "file" as const, locator: target, title: rel.split("/").pop() ?? rel },
    level: kind === "data" ? "user" as const : markdown !== null ? "fulltext" as const : "metadata" as const,
    retrievedAt: new Date().toISOString(),
    sha256,
    accessStatus: "partial" as const,
    locators: [{ kind: "file" as const, value: target }],
  };
  // Idempotent by evidence id so re-importing (or importing a file that was
  // published through /api/publish) never duplicates ledger entries.
  await appendJsonlIfMissing(projectPaths(root).evidence, evidence, (item) => item.id);

  const record: ImportRecord = {
    schemaVersion: "psyclaw/import/v1",
    path: rel,
    format: extension,
    kind,
    bytes,
    sha256,
    converted: markdown !== null,
    markdownLength: markdown?.length ?? 0,
    evidenceId,
    importedAt: new Date().toISOString(),
  };
  await appendJsonlIfMissing(await importsPath(root), record, (item) => item.sha256);
  return { record, markdown };
}

/**
 * Download the open-access PDF for a DOI into literature/<slug>.pdf. Only
 * https/http URLs returned by OpenAlex are accepted; size is capped at 40 MB.
 */
export async function downloadReferencePdf(
  root: string,
  doi: string,
  fetchFn: typeof fetch = fetch,
): Promise<{ ok: true; path: string; bytes: number; oaUrl: string; evidenceId: string } | { ok: false; reason: string; doi: string }> {
  const lookup = await lookupOaPdfUrl(doi, fetchFn);
  if (!lookup.isOa || !lookup.oaPdfUrl) return { ok: false, reason: "not-open-access", doi };
  let url: URL;
  try { url = new URL(lookup.oaPdfUrl); } catch { return { ok: false, reason: "invalid-oa-url", doi }; }
  if (url.protocol !== "https:" && url.protocol !== "http:") return { ok: false, reason: "unsafe-url", doi };
  const response = await fetchFn(url.toString(), { signal: AbortSignal.timeout(30_000) });
  if (!response.ok) return { ok: false, reason: `download-failed-${response.status}`, doi };
  const buffer = Buffer.from(await response.arrayBuffer());
  if (buffer.length === 0 || buffer.length > 40 * 1024 * 1024) return { ok: false, reason: "size-rejected", doi };

  const slug = doi.replace(/[^A-Za-z0-9._-]+/g, "_").slice(0, 80);
  const rel = `literature/${slug}.pdf`;
  const target = await assertSafeProjectPath(root, rel);
  await mkdir(dirname(target), { recursive: true });
  await writeFile(target, buffer);

  const sha256 = await sha256File(target);
  const evidenceId = `evidence_${sha256.slice(0, 16)}`;
  await appendJsonlIfMissing(projectPaths(root).evidence, {
    id: evidenceId,
    source: { kind: "url", locator: url.toString(), title: slug },
    level: "fulltext",
    retrievedAt: new Date().toISOString(),
    sha256,
    accessStatus: "partial",
    locators: [{ kind: "url", value: url.toString() }, { kind: "file", value: target }],
  }, (item) => item.id);

  const runId = `panel_${randomUUID().replaceAll("-", "")}`;
  const receipt = {
    schemaVersion: "psyclaw/tool-receipt/v1",
    runId,
    taskId: "panel.reference.download",
    tool: "panel.reference.download",
    effect: "write",
    approval: "approved",
    idempotencyKey: `panel:download:${sha256.slice(0, 24)}`,
    ok: true,
    startedAt: new Date().toISOString(),
    finishedAt: new Date().toISOString(),
  };
  await atomicWriteFile(await assertSafeProjectPath(root, `.psyclaw/manifests/${runId}.receipt.json`), `${JSON.stringify(receipt, null, 2)}\n`);
  return { ok: true, path: rel, bytes: buffer.length, oaUrl: url.toString(), evidenceId };
}

async function listProjectFiles(root: string): Promise<string[]> {
  const result: string[] = [];
  const walk = async (directory: string, prefix: string): Promise<void> => {
    if (result.length >= 500) return;
    let entries: import("node:fs").Dirent[] = [];
    try { entries = await readdir(directory, { withFileTypes: true }); } catch { return; }
    for (const entry of entries) {
      const relative = prefix ? `${prefix}/${entry.name}` : entry.name;
      const normalized = relative.replaceAll("\\", "/");
      if ([".git", "node_modules", "data/raw"].some((blocked) => normalized === blocked || normalized.startsWith(`${blocked}/`))) continue;
      if (/credential|secret|auth\.json|\.env/i.test(entry.name)) continue;
      const absolute = join(directory, entry.name);
      if (entry.isDirectory()) await walk(absolute, normalized); else if (entry.isFile()) result.push(normalized);
      if (result.length >= 500) return;
    }
  };
  await walk(root, "");
  return result.sort();
}

async function panelHistory(root: string): Promise<unknown> {
  const runs = await listRuns(root);
  const files = (await listProjectFiles(root)).filter((path) => path.startsWith("psyclaw-session-") || path.startsWith("notes/") || path.startsWith("outputs/") || path.startsWith(".psyclaw/runs/"));
  return { schemaVersion: "psyclaw/panel-history/v1", runs, files };
}

/** Infer an artifact format from its file extension. */
function inferArtifactFormat(path: string): string {
  const lower = path.toLowerCase();
  if (lower.endsWith(".svg")) return "svg";
  if (lower.endsWith(".png")) return "png";
  if (lower.endsWith(".jpg") || lower.endsWith(".jpeg")) return "jpg";
  if (lower.endsWith(".gif")) return "gif";
  if (lower.endsWith(".pdf")) return "pdf";
  if (lower.endsWith(".csv")) return "csv";
  if (lower.endsWith(".json")) return "json";
  if (lower.endsWith(".md") || lower.endsWith(".markdown")) return "markdown";
  return "file";
}

/** Artifact-shaped entries for figure/table files dropped directly in outputs/. */
async function figureTableArtifacts(root: string): Promise<Array<Record<string, unknown>>> {
  const files = await listProjectFiles(root);
  return files
    .filter((path) => /^(outputs|analysis\/outputs)\/(figures|tables)\//.test(path) && /\.(svg|png|jpe?g|gif|pdf|csv|json|md)$/i.test(path))
    .map((path) => ({ path, format: inferArtifactFormat(path), status: "generated" }));
}

async function panelStats(root: string): Promise<unknown> {
  const paths = projectPaths(root);
  const countLines = async (path: string): Promise<number> => { try { return (await readFile(path, "utf8")).split(/\r?\n/).filter(Boolean).length; } catch { return 0; } };
  const files = await listProjectFiles(root);
  return { schemaVersion: "psyclaw/panel-stats/v1", runs: (await listRuns(root)).length, evidence: await countLines(paths.evidence), claims: await countLines(paths.claims), auditEvents: await countLines(paths.audit), trackedFiles: files.length, outputs: files.filter((path) => path.startsWith("outputs/")).length, generatedAt: new Date().toISOString() };
}

function publicInstallPlan(plan: ReturnType<typeof planAgentInstall>): Record<string, unknown> {
  // `projectRoot` is an internal containment anchor. It is not needed by a
  // read-only browser and would disclose a local filesystem path.
  const { projectRoot: _projectRoot, ...publicFields } = plan;
  return publicFields;
}

export interface PanelServerOptions {
  /** Absolute or cwd-relative path to the panel HTML file. */
  panelHtmlPath?: string;
  /** Optional browser assistant. The callback owns the Pi/model boundary. */
  assistant?: (message: string) => Promise<{ text: string }>;
}

/** Metadata-only catalog for the optional panel. No install or credential read. */
async function panelCatalog(root: string): Promise<unknown> {
  const scans = await discoverAgents();
  const byId = new Map(scans.map((scan) => [scan.id, scan]));
  const agents = KNOWN_AGENTS.map((agent) => {
    const scan = byId.get(agent.id);
    const install = agent.install;
    const plan = planAgentInstall(agent, { projectRoot: root });
    return {
      id: agent.id,
      kind: "agent" as const,
      name: agent.name,
      source: install?.sourceRef ?? "builtin",
      ref: install?.ref ?? "unknown",
      version: install?.ref ?? "unknown",
      license: "unknown",
      sha256: null,
      risk: install?.installCommand ? "high" : "unknown",
      configured: scan?.found ?? false,
      skills: (scan?.skills ?? []).map((skill) => ({
        id: `${agent.id}:${skill.name}`,
        kind: "skill" as const,
        name: skill.name,
        source: agent.id,
        ref: "local",
        version: "unknown",
        license: "unknown",
        sha256: null,
        risk: "unknown",
        configured: true,
      })),
      installPlan: {
        id: plan.id,
        effect: plan.effect,
        approval: "required",
        status: "plan-only",
        command: plan.command,
      },
    };
  });
  const spec = deepSeekProviderSpec();
  const envForProvider = (provider: string): string | undefined => ({
    deepseek: "DEEPSEEK_API_KEY",
    openai: "OPENAI_API_KEY",
    anthropic: "ANTHROPIC_API_KEY",
    google: "GEMINI_API_KEY",
  }[provider] ?? PROVIDER_PRESETS.find((preset) => preset.id === provider)?.apiKeyEnv);
  const configured = (provider: string): boolean => {
    const envName = envForProvider(provider);
    return envName === undefined ? false : Boolean(process.env[envName]);
  };
  const helperModels = spec.models.map((model) => ({
    id: `${spec.id}/${model.id}`,
    kind: "model" as const,
    name: model.name ?? model.id,
    provider: spec.id,
    source: "builtin:psyclaw",
    ref: "deepseek-provider-v1",
    version: model.id,
    license: "provider-terms",
    sha256: null,
    risk: "network",
    configured: configured(spec.id),
    endpoint: spec.baseUrl,
    apiKeyEnv: spec.apiKeyEnv,
    configSource: "environment-presence" as const,
  }));
  const presetModels = PROVIDER_PRESETS.flatMap((preset) => preset.models.map((model) => ({
    id: `${preset.id}/${model.id}`,
    kind: "model" as const,
    name: model.name ?? model.id,
    provider: preset.id,
    source: "builtin:psyclaw-sync",
    ref: "psyclaw/providers/__init__.py",
    version: model.id,
    license: "provider-terms",
    sha256: null,
    risk: preset.baseUrl.startsWith("http") ? "network" : "local",
    configured: configured(preset.id) || Boolean(process.env[preset.apiKeyEnv]),
    endpoint: preset.baseUrl,
    apiKeyEnv: preset.apiKeyEnv,
    configSource: "preset" as const,
  })));
  let registered: readonly ModelDescriptor[] = [];
  try {
    // Pi's runtime is the source of truth for user/provider model catalogs. It
    // is explicitly cache-only here so opening the panel never triggers a
    // network refresh or an authentication flow.
    const gateway = await PiModelGateway.create({ allowModelNetwork: false, refreshOnCreate: false });
    registered = gateway.list();
  } catch {
    registered = [];
  }
  const registeredModels = registered.map((model) => {
    const apiKeyEnv = envForProvider(model.provider);
    return {
      id: `${model.provider}/${model.id}`,
      kind: "model" as const,
      name: model.name,
      provider: model.provider,
      source: "pi:model-runtime",
      ref: "models.json",
      version: model.id,
      license: "provider-terms",
      sha256: null,
      risk: "network",
      configured: configured(model.provider),
      endpoint: model.baseUrl,
      apiKeyEnv: apiKeyEnv ?? "Pi auth/config",
      configSource: "environment-presence" as const,
    };
  });
  // A real Pi registry entry wins over the helper template for the same
  // provider/model id. Helpers fill only gaps, so a local custom endpoint is
  // never silently replaced by psyclaw defaults.
  // Curated presets are presented first so stale local catalog entries do not
  // hide the synchronized provider list. Local-only models are retained below.
  const models = [...presetModels, ...registeredModels];
  const seenModelIds = new Set(models.map((model) => model.id));
  for (const model of [...presetModels, ...helperModels]) {
    if (seenModelIds.has(model.id)) continue;
    models.push(model);
    seenModelIds.add(model.id);
  }
  return { schemaVersion: "psyclaw/panel-catalog/v1", agents, models };
}

async function recommendedSkills(): Promise<unknown> {
  const moduleDir = dirname(fileURLToPath(import.meta.url));
  const candidates = [
    join(moduleDir, "..", "..", "..", "skills", "recommended", "catalog.json"),
    join(moduleDir, "..", "..", "..", "..", "skills", "recommended", "catalog.json"),
    join(moduleDir, "..", "..", "skills", "recommended", "catalog.json"),
    join(process.cwd(), "skills", "recommended", "catalog.json"),
  ];
  for (const path of candidates) {
    try {
      const catalog = JSON.parse(await readFile(path, "utf8")) as { items?: Array<Record<string, unknown>> };
      return { ...catalog, items: (catalog.items ?? []).map((item) => ({ ...item, slashCommand: `/skills enable ${String(item.id ?? "")}`, installCommand: `/install skill ${String(item.id ?? "")}` })) };
    } catch { /* try package layout */ }
  }
  return { schemaVersion: "psyclaw/recommended-skills/v1", documentVersion: "0.1.0", items: [] };
}

async function recommendedMcps(): Promise<unknown> {
  const moduleDir = dirname(fileURLToPath(import.meta.url));
  const candidates = [
    join(moduleDir, "..", "..", "..", "skills", "recommended", "mcp-catalog.json"),
    join(moduleDir, "..", "..", "..", "..", "skills", "recommended", "mcp-catalog.json"),
    join(moduleDir, "..", "..", "skills", "recommended", "mcp-catalog.json"),
    join(process.cwd(), "skills", "recommended", "mcp-catalog.json"),
  ];
  for (const path of candidates) {
    try {
      const catalog = JSON.parse(await readFile(path, "utf8")) as { items?: Array<Record<string, unknown>> };
      return { ...catalog, items: (catalog.items ?? []).map((item) => ({ ...item, slashCommand: `/mcp enable ${String(item.id ?? "")}`, installCommand: `/install mcp ${String(item.id ?? "")}` })) };
    } catch { /* try package layout */ }
  }
  return { schemaVersion: "psyclaw/recommended-mcp/v1", documentVersion: "0.1.0", items: [] };
}

async function recommendedInstallPrep(): Promise<unknown> {
  const [skills, mcps] = await Promise.all([recommendedSkills(), recommendedMcps()]);
  const skillPrep = skills && typeof skills === "object" && Array.isArray((skills as { installPrep?: unknown }).installPrep)
    ? (skills as { installPrep: unknown[] }).installPrep.map((item) => ({ ...(item as Record<string, unknown>), kind: "skill" })) : [];
  const mcpPrep = mcps && typeof mcps === "object" && Array.isArray((mcps as { installPrep?: unknown }).installPrep)
    ? (mcps as { installPrep: unknown[] }).installPrep.map((item) => ({ ...(item as Record<string, unknown>), kind: "mcp" })) : [];
  return { schemaVersion: "psyclaw/recommended-install-prep/v1", documentVersion: "0.1.0", items: [...skillPrep, ...mcpPrep] };
}

async function readAgentSettings(): Promise<Record<string, unknown>> {
  try {
    const parsed = JSON.parse(await readFile(join(getAgentDir(), "settings.json"), "utf8")) as unknown;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed as Record<string, unknown>;
  } catch { /* start empty */ }
  return {};
}

async function writeAgentSettings(patch: Record<string, unknown>): Promise<void> {
  const next = { ...(await readAgentSettings()), ...patch };
  await atomicWriteFile(join(getAgentDir(), "settings.json"), `${JSON.stringify(next, null, 2)}\n`);
}

async function findRecommendedItem(kind: "skill" | "mcp", id: string): Promise<{ item: Record<string, unknown>; prep?: Record<string, unknown> } | undefined> {
  const catalog = await (kind === "skill" ? recommendedSkills() : recommendedMcps()) as { items?: Array<Record<string, unknown>>; installPrep?: Array<Record<string, unknown>> };
  const item = (catalog.items ?? []).find((candidate) => candidate.id === id);
  if (!item) return undefined;
  const prep = (catalog.installPrep ?? []).find((candidate) => candidate.id === id);
  return { item, ...(prep === undefined ? {} : { prep }) };
}

function runShellCommand(command: string, cwd: string): Promise<{ exitCode: number; output: string }> {
  return new Promise((resolve) => {
    const child = spawn(command, { shell: true, cwd, stdio: ["ignore", "pipe", "pipe"] });
    let output = "";
    const append = (chunk: Buffer): void => {
      output += String(chunk);
      if (output.length > 24_000) output = output.slice(-24_000);
    };
    child.stdout?.on("data", append);
    child.stderr?.on("data", append);
    child.on("error", (error) => resolve({ exitCode: 1, output: `spawn error: ${error.message}` }));
    child.on("close", (code) => resolve({ exitCode: code ?? 1, output }));
  });
}

const USER_HOOK_ID = /^u-[a-z0-9][a-z0-9._-]{0,40}$/i;
const HOOK_EVENTS = new Set(["before-analysis", "before-write", "after-analysis"]);

function sanitizeUserHooks(body: Record<string, unknown>): Record<string, unknown> {
  const raw = Array.isArray(body.hooks) ? body.hooks : [];
  const hooks = raw.filter((value): value is Record<string, unknown> => Boolean(value) && typeof value === "object" && !Array.isArray(value));
  const cleaned: Array<Record<string, unknown>> = [];
  for (const hook of hooks) {
    const id = String(hook.id ?? "");
    if (!USER_HOOK_ID.test(id)) throw new Error(`hook id must be user-managed (u- prefix): ${id || "(empty)"}`);
    if (!HOOK_EVENTS.has(String(hook.event ?? ""))) throw new Error("hook event must be before-analysis, before-write or after-analysis");
    if (hook.severity !== "block" && hook.severity !== "warn") throw new Error("hook severity must be block or warn");
    if (typeof hook.message !== "string" || hook.message.trim().length < 1) throw new Error("hook message is required");
    if (hook.pattern !== undefined && (typeof hook.pattern !== "string" || hook.pattern.length > 500)) throw new Error("hook pattern must be a short string");
    if (hook.pathPrefix !== undefined && (typeof hook.pathPrefix !== "string" || hook.pathPrefix.length > 200)) throw new Error("hook pathPrefix must be a short string");
    const item: Record<string, unknown> = { id, event: hook.event, severity: hook.severity, message: hook.message.trim() };
    if (typeof hook.pattern === "string" && hook.pattern.trim()) item.pattern = hook.pattern.trim();
    if (typeof hook.pathPrefix === "string" && hook.pathPrefix.trim()) item.pathPrefix = hook.pathPrefix.trim();
    if (hook.enabled === false) item.enabled = false;
    cleaned.push(item);
  }
  return { schemaVersion: "psyclaw/user-analysis-hooks/v1", hooks: cleaned };
}

async function readJsonBody(request: import("node:http").IncomingMessage): Promise<Record<string, unknown>> {
  let body = "";
  for await (const chunk of request) {
    body += String(chunk);
    if (body.length > 128_000) throw new Error("request body too large");
  }
  const parsed: unknown = JSON.parse(body || "{}");
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("request body must be an object");
  return parsed as Record<string, unknown>;
}

/**
 * Run a panel write handler and surface the real validation error back to the
 * frontend (the outer handler intentionally hides internal failure details).
 */
async function runPanelWrite(response: import("node:http").ServerResponse, fn: () => Promise<void>): Promise<void> {
  try {
    await fn();
  } catch (error) {
    response.writeHead(400, { "content-type": "application/json" });
    response.end(JSON.stringify({ error: error instanceof Error ? error.message : String(error) }));
  }
}

/**
 * When the panel message references claims by id (e.g. the 追问此论断 flow),
 * attach the real ledger context (.psyclaw) so the spawned read-only assistant
 * answers grounded instead of fumbling for the claim.
 */
export async function enrichAssistantMessage(root: string, message: string): Promise<string> {
  const ids = [...new Set([...message.matchAll(/claim_[a-f0-9]{16}/gi)].map((match) => match[0]))];
  if (ids.length === 0) return message;
  let ledger: LedgerSnapshot;
  try { ledger = await loadLedger(root); } catch { return message; }
  const lines: string[] = [];
  for (const id of ids) {
    const claim = ledger.claims.find((candidate) => candidate.id === id);
    if (!claim) {
      lines.push(`- ${id}：项目账本（.psyclaw/claims.jsonl）中不存在该论断。`);
      continue;
    }
    const links = ledger.links.filter((link) => link.claimId === id);
    const evidence = links.map((link) => ledger.evidence.find((item) => item.id === link.evidenceId)).filter((item): item is Evidence => Boolean(item));
    lines.push(
      `- 论断 ${id}：文本="${claim.text}"；类型=${claim.kind}；状态=${claim.status}${claim.uncertainty === undefined ? "" : `；不确定说明="${claim.uncertainty}"`}；关联证据 ${evidence.length} 条。`,
      ...(evidence.length === 0
        ? ["  （该论断尚未登记任何证据/数据——无法核验样本量或效应量。诚实做法：说明需要先登记证据、核验 DOI 或下载全文，再要求方法学复核。）"]
        : []),
      ...evidence.slice(0, 5).map((item) =>
        `  - 证据 ${item.id}：来源=${item.source.kind}:${item.source.locator.slice(0, 80)}；级别=${item.level}；accessStatus=${item.accessStatus}${item.sha256 === undefined ? "" : `；sha256=${item.sha256.slice(0, 16)}…`}`,
      ),
    );
  }
  return `${message}\n\n[项目证据上下文（panel 自动附加，来自 .psyclaw 账本，只读）]\n${lines.join("\n")}`;
}

/**
 * Narrow local panel server. Run facts and catalog endpoints are read-only;
 * provider configuration is the one explicit POST action and delegates key
 * persistence to Pi's auth storage.
 */
export function createPanelServer(root: string, options: PanelServerOptions = {}): Server {
  // Resolve against the package rather than the process cwd, so `the PsyClaw /panel extension`
  // works from any project directory. The build step copies `apps/panel` into
  // `dist/apps/panel`, keeping the same relative layout in src and dist.
  const panelHtmlPath = options.panelHtmlPath ??
    join(dirname(fileURLToPath(import.meta.url)), "..", "..", "apps", "panel", "index.html");

  return createServer(async (request, response) => {
    const url = new URL(request.url ?? "/", "http://localhost");
    // Read-only surface: any write method is rejected before routing.
    const runAction = /^\/api\/runs\/[A-Za-z0-9][A-Za-z0-9._-]{0,127}\/(pause|resume)$/.test(url.pathname);
    if (request.method !== "GET" && request.method !== "HEAD" && !(request.method === "POST" && (["/api/provider-config", "/api/hitl/decision", "/api/assistant", "/api/system-prompt", "/api/hooks", "/api/recommendation-state", "/api/install/execute", "/api/active-provider", "/api/artifact/save", "/api/manuscript", "/api/claim", "/api/evidence", "/api/doi/verify", "/api/documents/import", "/api/publish", "/api/references/verify", "/api/references/check", "/api/references/download", "/api/citations"].includes(url.pathname) || runAction))) {
      response.writeHead(405, { "content-type": "application/json", allow: "GET, HEAD" });
      response.end(JSON.stringify({ error: "method not allowed" }));
      return;
    }
    try {
      if (url.pathname === "/api/runs") {
        const runs = await listRuns(root);
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ schemaVersion: "psyclaw/run-listing/v1", runs, projectRoot: root }));
        return;
      }
      if (url.pathname === "/api/snapshot") {
        const runId = url.searchParams.get("runId");
        if (!runId) {
          response.writeHead(400, { "content-type": "application/json" });
          response.end(JSON.stringify({ error: "runId query parameter is required" }));
          return;
        }
        const snapshot = await projectRunSnapshot(root, runId);
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify(snapshot));
        return;
      }
      if (url.pathname === "/api/catalog") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify(await panelCatalog(root)));
        return;
      }
      if (url.pathname === "/api/install-plan") {
        const agentId = url.searchParams.get("agentId");
        const agent = KNOWN_AGENTS.find((candidate) => candidate.id === agentId);
        if (!agent) {
          response.writeHead(404, { "content-type": "application/json" });
          response.end(JSON.stringify({ error: "unknown agent" }));
          return;
        }
        const plan = planAgentInstall(agent, { projectRoot: root });
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({
          schemaVersion: "psyclaw/install-plan-view/v1",
          plan: publicInstallPlan(plan),
          approval: "required",
          status: "plan-only",
        }));
        return;
      }
      if (url.pathname === "/api/import-plan") {
        const agentId = url.searchParams.get("agentId");
        const scan = (await discoverAgents()).find((candidate) => candidate.id === agentId && candidate.found);
        if (!scan) {
          response.writeHead(404, { "content-type": "application/json" });
          response.end(JSON.stringify({ error: "agent is not configured" }));
          return;
        }
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({
          schemaVersion: "psyclaw/import-plan-view/v1",
          agentId: scan.id,
          status: "plan-only",
          approval: "required",
          skills: scan.skills.map((skill) => ({ id: `${scan.id}:${skill.name}`, name: skill.name, kind: skill.kind, configured: true })),
        }));
        return;
      }
      if (url.pathname === "/api/history") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify(await panelHistory(root)));
        return;
      }
      if (url.pathname === "/api/stats") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify(await panelStats(root)));
        return;
      }
      if (url.pathname === "/api/files") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ schemaVersion: "psyclaw/panel-files/v1", files: await listProjectFiles(root) }));
        return;
      }
      if (url.pathname === "/api/config") {
        const promptPath = await assertSafeProjectPath(root, ".psyclaw/system-prompt.md");
        let supplement = "";
        try { supplement = await readFile(promptPath, "utf8"); } catch { /* no user supplement */ }
        const hooksText = await readFile(projectPaths(root).analysisHooks, "utf8").catch(() => "{\n  \"schemaVersion\": \"psyclaw/user-analysis-hooks/v1\",\n  \"hooks\": []\n}\n");
        let hooks: unknown;
        try { hooks = JSON.parse(hooksText); } catch { hooks = { schemaVersion: "psyclaw/user-analysis-hooks/v1", hooks: [], invalid: true }; }
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ schemaVersion: "psyclaw/panel-config/v1", systemPromptBase: PSYCLAW_IDENTITY_PROMPT, systemPromptSupplement: supplement, hooks }));
        return;
      }
      if (url.pathname === "/api/token-usage") {
        const report = await readSessionUsage(join(getAgentDir(), "sessions"));
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify(report));
        return;
      }
      if (url.pathname === "/api/literature-map") {
        const ledger = await loadLedger(root);
        const map = buildClaimLiteratureMap(ledger.claims, ledger.evidence, ledger.links);
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify(map));
        return;
      }
      if (url.pathname === "/api/enabled-capabilities") {
        const state = await readRecommendationState(root);
        const disabled = await readDisabledCapabilities(root);
        const [skills, mcps] = await Promise.all([recommendedSkills(), recommendedMcps()]);
        const nameOf = (kind: "skill" | "mcp", id: string): string => {
          const catalog = kind === "skill" ? skills : mcps;
          const item = ((catalog as { items?: Array<Record<string, unknown>> }).items ?? []).find((candidate) => candidate.id === id);
          return typeof item?.name === "string" ? item.name : id;
        };
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({
          schemaVersion: "psyclaw/enabled-capabilities/v1",
          coreSkills: CORE_SKILLS.map((skill) => ({ id: skill.id, name: skill.name, enabled: !disabled.coreSkills.includes(skill.id) })),
          skills: state.skills.map((id) => ({ id, name: nameOf("skill", id), enabled: true })),
          mcp: state.mcp.map((id) => ({ id, name: nameOf("mcp", id), enabled: true })),
        }));
        return;
      }
      if (url.pathname === "/api/active-provider") {
        if (request.method === "GET") {
          const settings = await readAgentSettings();
          response.writeHead(200, { "content-type": "application/json" });
          response.end(JSON.stringify({
            schemaVersion: "psyclaw/active-provider/v1",
            provider: typeof settings.defaultProvider === "string" ? settings.defaultProvider : undefined,
            model: typeof settings.defaultModel === "string" ? settings.defaultModel : undefined,
          }));
          return;
        }
        const body = await readJsonBody(request);
        const provider = String(body.provider ?? "").trim();
        const model = String(body.model ?? "").trim();
        if (!/^[a-z0-9][a-z0-9._/-]{0,127}$/i.test(provider)) throw new Error("provider is required and may contain letters, digits, . _ / -");
        if (!/^[a-z0-9][a-z0-9._:/()-]{0,127}$/i.test(model)) throw new Error("model is required and may contain letters, digits, . _ : / ( ) -");
        await writeAgentSettings({ defaultProvider: provider, defaultModel: model });
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ schemaVersion: "psyclaw/active-provider-receipt/v1", ok: true, provider, model, note: "重启 Pi 会话后生效" }));
        return;
      }
      if (url.pathname === "/api/install/execute") {
        if (request.method !== "POST") {
          response.writeHead(405, { "content-type": "application/json", allow: "POST" });
          response.end(JSON.stringify({ error: "method not allowed" }));
          return;
        }
        const body = await readJsonBody(request);
        const kind = body.kind === "skill" || body.kind === "mcp" ? body.kind : undefined;
        const id = String(body.id ?? "").trim();
        const approved = body.approved === true;
        const actor = String(body.actor ?? "researcher").trim();
        if (!kind || !id || !approved || actor.length < 1) throw new Error("kind, id, approved and actor are required");
        const found = await findRecommendedItem(kind, id);
        if (!found) {
          response.writeHead(404, { "content-type": "application/json" });
          response.end(JSON.stringify({ error: "unknown recommended item" }));
          return;
        }
        const command = typeof found.prep?.command === "string" && found.prep.command.trim() ? found.prep.command.trim() : undefined;
        if (!command) {
          response.writeHead(400, { "content-type": "application/json" });
          response.end(JSON.stringify({ error: "no install command is available for this item", blockedReason: found.prep?.blockedReason ?? null }));
          return;
        }
        const startedAt = new Date().toISOString();
        const runId = `panel_${randomUUID().replaceAll("-", "")}`;
        const idempotencyKey = `panel:install:${sha256Text(`${kind}\u0000${id}\u0000${actor}`).slice(0, 24)}`;
        const receipt: Record<string, unknown> = {
          schemaVersion: "psyclaw/tool-receipt/v1",
          runId,
          taskId: `install:${kind}:${id}`,
          tool: "panel.install.execute",
          effect: "write",
          approval: "approved",
          idempotencyKey,
          ok: false,
          command,
          startedAt,
        };
        const { exitCode, output } = await runShellCommand(command, root);
        receipt.ok = exitCode === 0;
        receipt.exitCode = exitCode;
        receipt.finishedAt = new Date().toISOString();
        const receiptPath = await assertSafeProjectPath(root, `.psyclaw/manifests/${runId}.receipt.json`);
        await atomicWriteFile(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`);
        if (receipt.ok) {
          const state = await readRecommendationState(root);
          const key = kind === "skill" ? "skills" : "mcp";
          state[key] = [...new Set([...state[key], id])];
          await writeRecommendationState(root, state);
        }
        await appendJsonlIfMissing(projectPaths(root).audit, {
          schemaVersion: "psyclaw/audit-event/v1",
          at: new Date().toISOString(),
          actor,
          action: `panel.install.${kind}`,
          targetId: id,
          ok: receipt.ok,
          runId,
          idempotencyKey,
        }, (item) => item.runId);
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({
          schemaVersion: "psyclaw/install-execution-receipt/v1",
          ok: receipt.ok,
          exitCode,
          command,
          output: output.slice(-2000),
          reloadHint: "/reload",
          ...(typeof found.prep?.blockedReason === "string" ? { blockedReason: found.prep.blockedReason } : {}),
        }));
        return;
      }
      if (url.pathname === "/api/recommendation-state") {
        if (request.method === "GET") {
          response.writeHead(200, { "content-type": "application/json" });
          response.end(JSON.stringify(await readRecommendationState(root)));
          return;
        }
        const body = await readJsonBody(request);
        const kind = body.kind === "skill" || body.kind === "skills" ? "skills" : body.kind === "mcp" ? "mcp" : body.kind === "core-skill" ? "core-skill" : undefined;
        const id = String(body.id ?? "").trim();
        if (!kind || !/^[a-z0-9][a-z0-9._-]{0,63}$/i.test(id) || typeof body.enabled !== "boolean") throw new Error("kind, id and enabled are required");
        if (kind === "core-skill") {
          if (!CORE_SKILLS.some((skill) => skill.id === id)) throw new Error(`unknown core skill: ${id}`);
          const disabled = await readDisabledCapabilities(root);
          const values = new Set(disabled.coreSkills);
          if (body.enabled) values.delete(id); else values.add(id);
          disabled.coreSkills = [...values];
          await writeDisabledCapabilities(root, disabled);
          response.writeHead(200, { "content-type": "application/json" });
          response.end(JSON.stringify({ schemaVersion: "psyclaw/capability-state-receipt/v1", ok: true, coreSkills: disabled.coreSkills }));
          return;
        }
        const state = await readRecommendationState(root);
        const values = new Set(state[kind]);
        if (body.enabled) values.add(id); else values.delete(id);
        state[kind] = [...values];
        await writeRecommendationState(root, state);
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ schemaVersion: "psyclaw/recommendation-state-receipt/v1", ok: true, state }));
        return;
      }
      if (url.pathname === "/api/system-prompt" || url.pathname === "/api/hooks") {
        const body = await readJsonBody(request);
        if (url.pathname === "/api/system-prompt") {
          const prompt = String(body.systemPrompt ?? "").trim();
          if (!prompt || prompt.length > 40_000) throw new Error("systemPrompt is required and must be under 40000 characters");
          await atomicWriteFile(await assertSafeProjectPath(root, ".psyclaw/system-prompt.md"), `${prompt}\n`);
        } else {
          const cleaned = sanitizeUserHooks(body);
          await atomicWriteFile(await assertSafeProjectPath(root, ".psyclaw/analysis-hooks.json"), `${JSON.stringify(cleaned, null, 2)}\n`);
        }
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ schemaVersion: "psyclaw/panel-config-receipt/v1", ok: true, updated: url.pathname.slice(5) }));
        return;
      }
      if (url.pathname === "/api/assistant") {
        if (request.method !== "POST") {
          response.writeHead(405, { "content-type": "application/json", allow: "POST" });
          response.end(JSON.stringify({ error: "method not allowed" }));
          return;
        }
        if (options.assistant === undefined) {
          response.writeHead(503, { "content-type": "application/json" });
          response.end(JSON.stringify({
            error: "面板聊天未连接智能体：请从 psyclaw 对话中执行 /panel 打开工作台（智能体通道随 /panel 建立）；当前为独立 serve，只能查看项目、无法回复。也可直接到 psyclaw 对话中提问。",
            reasonCode: "panel.assistant-unavailable",
          }));
          return;
        }
        const body = await readJsonBody(request);
        const message = String(body.message ?? "").trim();
        if (!message || message.length > 12_000) {
          response.writeHead(400, { "content-type": "application/json" });
          response.end(JSON.stringify({ error: "message is required and must be under 12000 characters" }));
          return;
        }
        try {
          const enriched = await enrichAssistantMessage(root, message);
          const answer = await options.assistant(enriched);
          response.writeHead(200, { "content-type": "application/json" });
          response.end(JSON.stringify({ schemaVersion: "psyclaw/workbench-message/v1", ...answer }));
        } catch (error) {
          response.writeHead(502, { "content-type": "application/json" });
          response.end(JSON.stringify({ error: error instanceof Error ? error.message : "assistant request failed", reasonCode: "panel.assistant-failed" }));
        }
        return;
      }
      if (runAction) {
        const match = url.pathname.match(/^\/api\/runs\/([A-Za-z0-9][A-Za-z0-9._-]{0,127})\/(pause|resume)$/);
        const runId = match?.[1] ?? "";
        const action = match?.[2] ?? "";
        const body = await readJsonBody(request);
        const approved = body.approved === true;
        const actor = String(body.actor ?? "").trim();
        const reason = String(body.reason ?? "").trim();
        if (!approved || !actor || reason.length < 3) {
          response.writeHead(400, { "content-type": "application/json" });
          response.end(JSON.stringify({ error: "approved=true, actor, and reason (3+ chars) are required" }));
          return;
        }
        const pausePath = await assertSafeProjectPath(root, `.psyclaw/runs/${runId}.pause`);
        const planPath = await assertSafeProjectPath(root, `.psyclaw/plans/${runId}.json`);
        if (action === "pause") {
          await atomicWriteFile(pausePath, `${JSON.stringify({ schemaVersion: "psyclaw/pause-request/v1", runId, actor, reason, requestedAt: new Date().toISOString() }, null, 2)}\n`);
          response.writeHead(200, { "content-type": "application/json" });
          response.end(JSON.stringify({ schemaVersion: "psyclaw/run-action-receipt/v1", action, runId, status: "pause-requested", actor }));
          return;
        }
        if (activePanelRuns.has(runId)) {
          response.writeHead(409, { "content-type": "application/json" });
          response.end(JSON.stringify({ error: "run is already being resumed" }));
          return;
        }
        let plan: unknown;
        try { plan = JSON.parse(await readFile(planPath, "utf8")); }
        catch { response.writeHead(404, { "content-type": "application/json" }); response.end(JSON.stringify({ error: "run plan not found" })); return; }
        await unlink(pausePath).catch(() => undefined);
        activePanelRuns.add(runId);
        try {
          const eventLog = new RunEventLog(root, runId);
          const result = await resumePlanWithPi(plan, {
            cwd: root,
            root,
            pauseRequested: async () => {
              try { await lstat(pausePath); return true; } catch { return false; }
            },
            onEvent: async (event) => { await eventLog.append(event); },
          });
          response.writeHead(200, { "content-type": "application/json" });
          response.end(JSON.stringify({ schemaVersion: "psyclaw/run-action-receipt/v1", action, runId, status: result.status, diagnostics: result.diagnostics, actor }));
        } finally {
          activePanelRuns.delete(runId);
        }
        return;
      }
      if (url.pathname === "/api/hitl") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify(await readHitlWorkspace(root, url.searchParams.get("contents") === "1")));
        return;
      }
      if (url.pathname === "/api/artifacts") {
        const indexPath = projectPaths(root).outputs + "/index.json";
        let indexedArtifacts: Array<Record<string, unknown>> = [];
        let rest: Record<string, unknown> = {};
        try {
          const index = JSON.parse(await readFile(indexPath, "utf8")) as Record<string, unknown>;
          if (Array.isArray(index.artifacts)) {
            indexedArtifacts = index.artifacts.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object");
          }
          const { artifacts: _artifacts, ...remaining } = index;
          rest = remaining;
        } catch { /* no index.json yet */ }
        const figureFiles = await figureTableArtifacts(root);
        const indexedPaths = new Set(indexedArtifacts.map((item) => String(item.path ?? "")).filter(Boolean));
        const merged = [...indexedArtifacts, ...figureFiles.filter((item) => !indexedPaths.has(String(item.path)))];
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ schemaVersion: "psyclaw/artifact-listing/v1", ...rest, artifacts: merged }));
        return;
      }
      if (url.pathname === "/api/artifact") {
        const relative = url.searchParams.get("path")?.trim() ?? "";
        if (!relative || relative.replaceAll("\\", "/").split("/").some((part) => part === ".." || part === "")) {
          response.writeHead(400, { "content-type": "application/json" });
          response.end(JSON.stringify({ error: "a relative artifact path is required" }));
          return;
        }
        // Resolve the path as-is first (paper/archive/, literature/, ...),
        // then fall back to outputs/<path> for legacy relative artifact entries.
        let target = await assertSafeProjectPath(root, relative);
        let stat = await lstat(target).catch(() => undefined);
        if (!stat?.isFile()) {
          const fallback = await assertSafeProjectPath(root, `outputs/${relative}`);
          const fallbackStat = await lstat(fallback).catch(() => undefined);
          if (fallbackStat?.isFile()) { target = fallback; stat = fallbackStat; }
        }
        if (!stat?.isFile() || stat.isSymbolicLink()) throw new Error("artifact must be a regular file");
        const body = await readFile(target);
        const lower = target.toLowerCase();
        const contentType =
          lower.endsWith(".svg") ? "image/svg+xml; charset=utf-8" :
          lower.endsWith(".png") ? "image/png" :
          lower.endsWith(".jpg") || lower.endsWith(".jpeg") ? "image/jpeg" :
          lower.endsWith(".gif") ? "image/gif" :
          lower.endsWith(".pdf") ? "application/pdf" :
          lower.endsWith(".json") ? "application/json" :
          lower.endsWith(".md") ? "text/markdown; charset=utf-8" :
          "text/plain; charset=utf-8";
        const fileName = relative.split(/[\\/]/).at(-1) ?? "file";
        // Node rejects non-ASCII header values; use RFC 5987 for CJK names.
        const contentDisposition = /[^\x20-\x7E]/.test(fileName)
          ? `inline; filename="${fileName.replace(/[^\x20-\x7E]/g, "_")}"; filename*=UTF-8''${encodeURIComponent(fileName)}`
          : `inline; filename="${fileName}"`;
        response.writeHead(200, { "content-type": contentType, "content-disposition": contentDisposition });
        response.end(body);
        return;
      }
      if (url.pathname === "/api/artifact/save") {
        if (request.method !== "POST") {
          response.writeHead(405, { "content-type": "application/json", allow: "POST" });
          response.end(JSON.stringify({ error: "method not allowed" }));
          return;
        }
        const body = await readJsonBody(request);
        const relative = String(body.path ?? "").trim();
        const content = typeof body.content === "string" ? body.content : "";
        if (!relative || !/\.svg$/i.test(relative)) throw new Error("only SVG artifacts can be edited");
        const rel = relative.replaceAll("\\", "/");
        if (rel.split("/").some((part) => part === ".." || part === "")) throw new Error("a relative artifact path is required");
        if (!rel.startsWith("outputs/") && !rel.startsWith("analysis/outputs/")) throw new Error("artifact must be under outputs/ or analysis/outputs/");
        const target = await assertSafeProjectPath(root, rel);
        const stat = await lstat(target).catch(() => undefined);
        if (stat !== undefined && (stat.isSymbolicLink() || !stat.isFile())) throw new Error("artifact must be a regular file");
        await atomicWriteFile(target, content.endsWith("\n") ? content : `${content}\n`);
        const receipt = {
          schemaVersion: "psyclaw/tool-receipt/v1",
          runId: `panel_${randomUUID().replaceAll("-", "")}`,
          taskId: "panel.artifact.save",
          tool: "panel.artifact.save",
          effect: "write",
          approval: "approved",
          idempotencyKey: `panel:artifact:${sha256Text(`${rel}\u0000${content}`).slice(0, 24)}`,
          ok: true,
          startedAt: new Date().toISOString(),
          finishedAt: new Date().toISOString(),
        };
        await atomicWriteFile(await assertSafeProjectPath(root, `.psyclaw/manifests/${receipt.runId}.receipt.json`), `${JSON.stringify(receipt, null, 2)}\n`);
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ schemaVersion: "psyclaw/artifact-save-receipt/v1", ok: true, path: rel, bytes: Buffer.byteLength(content, "utf8") }));
        return;
      }
      if (url.pathname === "/api/ledger") {
        const ledger = await loadLedger(root);
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ schemaVersion: "psyclaw/ledger/v1", ...ledger, projectRoot: root }));
        return;
      }
      if (url.pathname === "/api/manuscript") {
        if (request.method === "POST") {
          await runPanelWrite(response, async () => {
            const body = await readJsonBody(request);
            const relative = String(body.path ?? "notes/manuscript.md").trim();
            const content = typeof body.content === "string" ? body.content : "";
            if (!content.trim()) throw new Error("manuscript content is required");
            const saved = await writeManuscript(root, relative, content);
            response.writeHead(200, { "content-type": "application/json" });
            response.end(JSON.stringify({ schemaVersion: "psyclaw/manuscript-save/v1", ok: true, ...saved }));
          });
          return;
        }
        const manuscript = await readManuscript(root);
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ schemaVersion: "psyclaw/manuscript/v1", ...manuscript }));
        return;
      }
      if (url.pathname === "/api/claim") {
        if (request.method !== "POST") {
          response.writeHead(405, { "content-type": "application/json", allow: "POST" });
          response.end(JSON.stringify({ error: "method not allowed" }));
          return;
        }
        await runPanelWrite(response, async () => {
          const body = await readJsonBody(request);
          const claim = await appendLedgerClaim(root, body);
          const runId = `panel_${randomUUID().replaceAll("-", "")}`;
          const receipt = {
            schemaVersion: "psyclaw/tool-receipt/v1",
            runId,
            taskId: "panel.claim.append",
            tool: "panel.claim.append",
            effect: "write",
            approval: "approved",
            idempotencyKey: `panel:claim:${claim.id}`,
            ok: true,
            startedAt: new Date().toISOString(),
            finishedAt: new Date().toISOString(),
          };
          await atomicWriteFile(await assertSafeProjectPath(root, `.psyclaw/manifests/${runId}.receipt.json`), `${JSON.stringify(receipt, null, 2)}\n`);
          response.writeHead(200, { "content-type": "application/json" });
          response.end(JSON.stringify({ schemaVersion: "psyclaw/claim-append/v1", ok: true, claim }));
        });
        return;
      }
      if (url.pathname === "/api/evidence") {
        if (request.method !== "POST") {
          response.writeHead(405, { "content-type": "application/json", allow: "POST" });
          response.end(JSON.stringify({ error: "method not allowed" }));
          return;
        }
        await runPanelWrite(response, async () => {
          const body = await readJsonBody(request);
          const { evidence, link } = await appendLedgerEvidence(root, body);
          const runId = `panel_${randomUUID().replaceAll("-", "")}`;
          const receipt = {
            schemaVersion: "psyclaw/tool-receipt/v1",
            runId,
            taskId: "panel.evidence.append",
            tool: "panel.evidence.append",
            effect: "write",
            approval: "approved",
            idempotencyKey: `panel:evidence:${evidence.id}`,
            ok: true,
            startedAt: new Date().toISOString(),
            finishedAt: new Date().toISOString(),
          };
          await atomicWriteFile(await assertSafeProjectPath(root, `.psyclaw/manifests/${runId}.receipt.json`), `${JSON.stringify(receipt, null, 2)}\n`);
          response.writeHead(200, { "content-type": "application/json" });
          response.end(JSON.stringify({ schemaVersion: "psyclaw/evidence-append/v1", ok: true, evidence, link }));
        });
        return;
      }
      if (url.pathname === "/api/doi/verify") {
        if (request.method !== "POST") {
          response.writeHead(405, { "content-type": "application/json", allow: "POST" });
          response.end(JSON.stringify({ error: "method not allowed" }));
          return;
        }
        await runPanelWrite(response, async () => {
          const body = await readJsonBody(request);
          const doi = typeof body.doi === "string" ? body.doi : "";
          response.writeHead(200, { "content-type": "application/json" });
          response.end(JSON.stringify(await verifyDoi(doi)));
        });
        return;
      }
      if (url.pathname === "/api/documents") {
        const documents = await scanDocuments(root);
        const imported = await readJsonl<ImportRecord>(await importsPath(root));
        const importedBySha = new Set(imported.map((record) => record.sha256));
        const manuscript = await readManuscript(root);
        const enriched = await Promise.all(documents.map(async (doc) => {
          let sha256 = "";
          try { sha256 = await sha256File(await assertSafeProjectPath(root, doc.path)); } catch { /* unreadable */ }
          return { ...doc, sha256, imported: importedBySha.has(sha256), isManuscript: manuscript.path === doc.path };
        }));
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ schemaVersion: "psyclaw/documents/v1", projectRoot: root, documents: enriched }));
        return;
      }
      if (url.pathname === "/api/documents/import") {
        if (request.method !== "POST") {
          response.writeHead(405, { "content-type": "application/json", allow: "POST" });
          response.end(JSON.stringify({ error: "method not allowed" }));
          return;
        }
        await runPanelWrite(response, async () => {
          const body = await readJsonBody(request);
          const relative = typeof body.path === "string" ? body.path : "";
          const { record, markdown } = await importDocument(root, relative);
          const runId = `panel_${randomUUID().replaceAll("-", "")}`;
          const receipt = {
            schemaVersion: "psyclaw/tool-receipt/v1",
            runId,
            taskId: "panel.document.import",
            tool: "panel.document.import",
            effect: "write",
            approval: "approved",
            idempotencyKey: `panel:import:${record.sha256}`,
            ok: true,
            startedAt: new Date().toISOString(),
            finishedAt: new Date().toISOString(),
          };
          await atomicWriteFile(await assertSafeProjectPath(root, `.psyclaw/manifests/${runId}.receipt.json`), `${JSON.stringify(receipt, null, 2)}\n`);
          response.writeHead(200, { "content-type": "application/json" });
          response.end(JSON.stringify({
            schemaVersion: "psyclaw/import/v1",
            ok: true,
            imported: true,
            alreadyImported: markdown === null,
            path: record.path,
            format: record.format,
            kind: record.kind,
            bytes: record.bytes,
            sha256: record.sha256,
            evidenceId: record.evidenceId,
            markdown,
          }));
        });
        return;
      }
      if (url.pathname === "/api/publish") {
        if (request.method !== "POST") {
          response.writeHead(405, { "content-type": "application/json", allow: "POST" });
          response.end(JSON.stringify({ error: "method not allowed" }));
          return;
        }
        await runPanelWrite(response, async () => {
          const body = await readJsonBody(request);
          const result = await publishManuscript(root, {
            ...(typeof body.name === "string" && body.name.trim() ? { name: body.name } : {}),
            ...(typeof body.content === "string" ? { markdown: body.content } : {}),
            ...(body.exportDocx === undefined ? {} : { exportDocx: body.exportDocx !== false }),
          });
          response.writeHead(200, { "content-type": "application/json" });
          response.end(JSON.stringify({ ok: true, ...result }));
        });
        return;
      }
      if (url.pathname === "/api/versions") {
        const versions = await readPublishedVersions(root);
        const current = versions.at(-1) ?? null;
        const withLoadPaths = versions.map((version) => {
          const isCurrent = current !== null && version.version === current.version;
          return {
            ...version,
            markdownLoadPath: isCurrent ? version.markdownPath : `paper/archive/${version.name}_v${version.version}.md`,
            ...(version.docxPath === null ? {} : { docxLoadPath: isCurrent ? version.docxPath : `paper/archive/${version.name}_v${version.version}_APA7.docx` }),
          };
        });
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ schemaVersion: "psyclaw/versions/v1", versions: withLoadPaths, current }));
        return;
      }
      if (url.pathname === "/api/references") {
        const references = await listReferences(root);
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ schemaVersion: "psyclaw/references/v1", references }));
        return;
      }
      if (url.pathname === "/api/references/verify") {
        if (request.method !== "POST") {
          response.writeHead(405, { "content-type": "application/json", allow: "POST" });
          response.end(JSON.stringify({ error: "method not allowed" }));
          return;
        }
        await runPanelWrite(response, async () => {
          const body = await readJsonBody(request);
          const doi = typeof body.doi === "string" ? body.doi.trim() : "";
          if (!doi) throw new Error("doi is required");
          const [verification, oa] = await Promise.all([verifyDoi(doi), lookupOaPdfUrl(doi)]);
          const record = referenceFromVerification(verification);
          if (!record) {
            response.writeHead(200, { "content-type": "application/json" });
            response.end(JSON.stringify({ schemaVersion: "psyclaw/reference-verify/v1", ok: false, verification, reason: "no-metadata" }));
            return;
          }
          if (oa.isOa && oa.oaPdfUrl) record.oaPdfUrl = oa.oaPdfUrl;
          const { appended } = await upsertReference(root, record);
          response.writeHead(200, { "content-type": "application/json" });
          response.end(JSON.stringify({ schemaVersion: "psyclaw/reference-verify/v1", ok: true, appended, record }));
        });
        return;
      }
      if (url.pathname === "/api/references/check") {
        if (request.method !== "POST") {
          response.writeHead(405, { "content-type": "application/json", allow: "POST" });
          response.end(JSON.stringify({ error: "method not allowed" }));
          return;
        }
        await runPanelWrite(response, async () => {
          const body = await readJsonBody(request);
          const text = typeof body.text === "string" ? body.text : "";
          if (!text.trim()) throw new Error("text is required");
          const references = await listReferences(root);
          const result = checkCitations(text, references);
          response.writeHead(200, { "content-type": "application/json" });
          response.end(JSON.stringify({ schemaVersion: "psyclaw/reference-check/v1", ...result, archiveSize: references.length }));
        });
        return;
      }
      if (url.pathname === "/api/references/download") {
        if (request.method !== "POST") {
          response.writeHead(405, { "content-type": "application/json", allow: "POST" });
          response.end(JSON.stringify({ error: "method not allowed" }));
          return;
        }
        await runPanelWrite(response, async () => {
          const body = await readJsonBody(request);
          const doi = typeof body.doi === "string" ? body.doi.trim() : "";
          if (!doi) throw new Error("doi is required");
          const result = await downloadReferencePdf(root, doi);
          response.writeHead(200, { "content-type": "application/json" });
          response.end(JSON.stringify({ schemaVersion: "psyclaw/reference-download/v1", ...result }));
        });
        return;
      }
      if (url.pathname === "/api/citations") {
        if (request.method === "GET") {
          const citations = await listCitationUses(root);
          response.writeHead(200, { "content-type": "application/json" });
          response.end(JSON.stringify({ schemaVersion: "psyclaw/citations/v1", citations }));
          return;
        }
        if (request.method !== "POST") {
          response.writeHead(405, { "content-type": "application/json", allow: "GET, POST" });
          response.end(JSON.stringify({ error: "method not allowed" }));
          return;
        }
        await runPanelWrite(response, async () => {
          const body = await readJsonBody(request);
          const doi = typeof body.doi === "string" ? body.doi : "";
          const reason = typeof body.reason === "string" ? body.reason : "";
          const context = typeof body.context === "string" ? body.context : "";
          if (!doi || !reason || !context) throw new Error("doi, reason, and context are all required");
          const result = await recordCitationUse(root, {
            doi,
            reason,
            context,
            ...(typeof body.section === "string" && body.section.trim() ? { section: body.section } : {}),
            ...(typeof body.claimId === "string" && body.claimId.trim() ? { claimId: body.claimId } : {}),
          });
          response.writeHead(200, { "content-type": "application/json" });
          response.end(JSON.stringify({ schemaVersion: "psyclaw/citation-record/v1", ok: true, ...result }));
        });
        return;
      }
      if (url.pathname === "/api/recommended-skills") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify(await recommendedSkills()));
        return;
      }
      if (url.pathname === "/api/recommended-mcps") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify(await recommendedMcps()));
        return;
      }
      if (url.pathname === "/api/recommended-install-prep") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify(await recommendedInstallPrep()));
        return;
      }
      if (url.pathname === "/api/mcp-plan") {
        const id = url.searchParams.get("id");
        const catalog = await recommendedMcps() as { items?: Array<Record<string, unknown>> };
        const item = catalog.items?.find((candidate) => candidate.id === id);
        if (!item) {
          response.writeHead(404, { "content-type": "application/json" });
          response.end(JSON.stringify({ error: "unknown MCP recommendation" }));
          return;
        }
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({
          schemaVersion: "psyclaw/mcp-plan-view/v1",
          id: item.id,
          name: item.name,
          sourceRef: item.sourceRef,
          transport: item.transport,
          risk: item.risk,
          writeEffects: item.writeEffects,
          status: "plan-only",
          approval: "required",
          note: "Review source, version, license, dependencies, and tool allowlist before enabling.",
        }));
        return;
      }
      if (url.pathname === "/api/provider-config") {
        if (request.method !== "POST") {
          response.writeHead(405, { "content-type": "application/json", allow: "POST" });
          response.end(JSON.stringify({ error: "method not allowed" }));
          return;
        }
        const body = await readJsonBody(request);
        const id = String(body.id ?? "").trim();
        const preset = PROVIDER_PRESETS.find((candidate) => candidate.id === id);
        const name = String(body.name ?? preset?.name ?? id).trim();
        const baseUrl = String(body.baseUrl ?? preset?.baseUrl ?? "").trim();
        const api = body.api === "anthropic-messages" ? "anthropic-messages" : "openai-completions";
        const apiKeyEnv = String(body.apiKeyEnv ?? preset?.apiKeyEnv ?? `PSYCLAW_${id.toUpperCase().replace(/[^A-Z0-9]/g, "_")}_API_KEY`).trim();
        const modelId = String(body.modelId ?? "").trim();
        const models = Array.isArray(body.models)
          ? body.models.filter((value): value is string => typeof value === "string").map((value) => ({ id: value.trim(), name: value.trim() })).filter((value) => value.id)
          : (modelId ? [{ id: modelId, name: modelId }] : (preset?.models ?? []));
        const apiKey = typeof body.apiKey === "string" ? body.apiKey : undefined;
        if (!id || !name || !baseUrl || models.length === 0) throw new Error("id, name, baseUrl and at least one model are required");
        const result = await saveProviderConfig({
          id,
          name,
          baseUrl,
          api,
          apiKeyEnv,
          models,
          ...(apiKey === undefined ? {} : { apiKey }),
        });
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ schemaVersion: "psyclaw/provider-config-receipt/v1", ok: true, provider: id, modelCount: models.length, apiKeyStored: Boolean(apiKey?.trim()) }));
        return;
      }
      if (url.pathname === "/api/hitl/decision") {
        if (request.method !== "POST") {
          response.writeHead(405, { "content-type": "application/json", allow: "POST" });
          response.end(JSON.stringify({ error: "method not allowed" }));
          return;
        }
        const body = await readJsonBody(request);
        const decision = String(body.decision ?? "").trim();
        const rationale = String(body.rationale ?? "").trim();
        const actor = String(body.actor ?? "researcher").trim();
        if (!["approved", "denied", "needs-changes"].includes(decision) || rationale.length < 3 || actor.length < 1) {
          response.writeHead(400, { "content-type": "application/json" });
          response.end(JSON.stringify({ error: "decision, rationale (3+ chars), and actor are required" }));
          return;
        }
        const recordedAt = new Date().toISOString();
        const idempotencyKey = `panel:hitl:${sha256Text(`${decision}\u0000${rationale}\u0000${actor}`).slice(0, 24)}`;
        const decisionDocument = [
          "---",
          "schemaVersion: psyclaw/hitl-decision-request/v1",
          "documentVersion: 1.0.0",
          `recordedAt: ${recordedAt}`,
          `actor: ${actor.replaceAll("\n", " ")}`,
          `decision: ${decision}`,
          `idempotencyKey: ${idempotencyKey}`,
          "---",
          "",
          "# Decision Request",
          "",
          `Decision: ${decision}`,
          "",
          "## Rationale",
          "",
          rationale,
          "",
        ].join("\n");
        const decisionPath = await assertSafeProjectPath(root, "notes/decision_request.md");
        await atomicWriteFile(decisionPath, decisionDocument);
        const receipt = {
          schemaVersion: "psyclaw/tool-receipt/v1",
          runId: `panel_${randomUUID().replaceAll("-", "")}`,
          taskId: "hitl-decision",
          tool: "panel.hitl.decision",
          effect: "write",
          approval: "approved",
          idempotencyKey,
          ok: true,
          resultHash: sha256Text(decisionDocument),
          startedAt: recordedAt,
          finishedAt: new Date().toISOString(),
        };
        const receiptPath = await assertSafeProjectPath(root, `.psyclaw/manifests/${receipt.runId}.receipt.json`);
        await atomicWriteFile(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`);
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ schemaVersion: "psyclaw/hitl-decision-receipt/v1", ok: true, decision, decisionPath, receiptPath, idempotencyKey }));
        return;
      }
      if (url.pathname === "/" || url.pathname === "/index.html") {
        const html = await readFile(panelHtmlPath, "utf8");
        response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
        response.end(html);
        return;
      }
      response.writeHead(404, { "content-type": "application/json" });
      response.end(JSON.stringify({ error: "not found" }));
    } catch {
      response.writeHead(500, { "content-type": "application/json" });
      response.end(JSON.stringify({ error: "panel request failed", reasonCode: "panel.request-failed" }));
    }
  });
}
