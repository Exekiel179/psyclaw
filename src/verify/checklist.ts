import { readFile } from "node:fs/promises";
import { atomicWriteFile } from "../project/jsonl.js";
import { assertSafeProjectPath } from "../project/paths.js";

export const VERIFY_CHECKLIST_SCHEMA = "psyclaw/verify-checklist/v1" as const;
export const VERIFY_CHECKLIST_PATH = ".psyclaw/verify-checklist.json" as const;

/**
 * Checklist statuses:
 * - unverified: not checked yet
 * - ai-checked: AI finished a /crosscheck or /verify pass on the item (does NOT satisfy human gate)
 * - verified: human approved via Panel「核实」or wake-options (internal human-approve; not a user slash)
 * - flagged / skipped: do not satisfy the human gate
 */
export type VerifyStatus = "unverified" | "ai-checked" | "verified" | "flagged" | "skipped";

export type VerifyMarkSource = "ai" | "human";

/** Domains for process/substantive AI passes; humans approve separately via Panel/wake. */
export type CrosscheckKind = "citations" | "format" | "requirements" | "stats" | "general";

export type VerifyPhase = "pre-analysis" | "post-analysis" | "general";

export interface VerifyItem {
  id: string;
  label: string;
  status: VerifyStatus;
  kind?: CrosscheckKind;
  phase?: VerifyPhase;
  notes?: string;
  updatedAt?: string;
  /** Who last set a conclusive mark; gate only accepts human-verified. */
  approvedBy?: VerifyMarkSource;
}

export interface VerifyChecklist {
  schemaVersion: typeof VERIFY_CHECKLIST_SCHEMA;
  items: VerifyItem[];
  updatedAt: string;
}

export type HumanVerifyGateScope = "analysis-complete" | "academic-finalize";

export type HumanVerifyGateResult =
  | { ok: true; checklist: VerifyChecklist }
  | { ok: false; checklist: VerifyChecklist; pending: VerifyItem[]; message: string };

const DEFAULT_ITEMS: readonly Omit<VerifyItem, "status">[] = [
  { id: "design-estimand", label: "研究问题 / estimand 与拟做分析一致", kind: "requirements", phase: "pre-analysis" },
  { id: "method-choice", label: "分析方法选择已经人确认（或已标注 auto/未审批）", kind: "stats", phase: "pre-analysis" },
  { id: "missing-exclusion", label: "缺失与排除规则已披露", kind: "requirements", phase: "pre-analysis" },
  { id: "n", label: "样本量 / N", kind: "stats", phase: "post-analysis" },
  { id: "primary-effect", label: "主效应 / 主要结果（含效应量与不确定性）", kind: "stats", phase: "post-analysis" },
  { id: "table-text", label: "表与正文一致", kind: "format", phase: "post-analysis" },
  { id: "method-match", label: "方法与实际脚本一致", kind: "stats", phase: "post-analysis" },
  { id: "key-claim", label: "关键主张有结果支撑、无过度因果", kind: "requirements", phase: "post-analysis" },
  { id: "citations", label: "引文 DOI / 字段交叉核验", kind: "citations", phase: "general" },
];

const VALID_STATUS = new Set<VerifyStatus>(["unverified", "ai-checked", "verified", "flagged", "skipped"]);
const VALID_KIND = new Set<CrosscheckKind>(["citations", "format", "requirements", "stats", "general"]);

const SCOPE_PHASES: Record<HumanVerifyGateScope, readonly VerifyPhase[]> = {
  "analysis-complete": ["pre-analysis", "post-analysis"],
  "academic-finalize": ["pre-analysis", "post-analysis", "general"],
};

export function defaultVerifyChecklist(now = new Date().toISOString()): VerifyChecklist {
  return {
    schemaVersion: VERIFY_CHECKLIST_SCHEMA,
    updatedAt: now,
    items: DEFAULT_ITEMS.map((item) => ({ ...item, status: "unverified" as const })),
  };
}

function isVerifyItem(item: unknown): item is VerifyItem {
  if (!item || typeof item !== "object") return false;
  const row = item as VerifyItem;
  return typeof row.id === "string"
    && typeof row.label === "string"
    && VALID_STATUS.has(row.status)
    && (row.kind === undefined || VALID_KIND.has(row.kind))
    && (row.approvedBy === undefined || row.approvedBy === "ai" || row.approvedBy === "human");
}

export async function loadVerifyChecklist(root: string): Promise<VerifyChecklist> {
  const path = await assertSafeProjectPath(root, VERIFY_CHECKLIST_PATH);
  try {
    const parsed = JSON.parse(await readFile(path, "utf8")) as Partial<VerifyChecklist>;
    if (parsed.schemaVersion !== VERIFY_CHECKLIST_SCHEMA || !Array.isArray(parsed.items)) {
      return {
        schemaVersion: VERIFY_CHECKLIST_SCHEMA,
        items: [],
        updatedAt: new Date().toISOString(),
      };
    }
    const items = parsed.items.filter(isVerifyItem);
    return {
      schemaVersion: VERIFY_CHECKLIST_SCHEMA,
      updatedAt: typeof parsed.updatedAt === "string" ? parsed.updatedAt : new Date().toISOString(),
      items,
    };
  } catch {
    return {
      schemaVersion: VERIFY_CHECKLIST_SCHEMA,
      items: [],
      updatedAt: new Date().toISOString(),
    };
  }
}

export async function saveVerifyChecklist(root: string, checklist: VerifyChecklist): Promise<void> {
  const path = await assertSafeProjectPath(root, VERIFY_CHECKLIST_PATH);
  await atomicWriteFile(path, `${JSON.stringify(checklist, null, 2)}\n`);
}

/** Ensure default analysis/academic gate items exist before completion checks. */
export async function ensureDefaultVerifyChecklist(root: string): Promise<VerifyChecklist> {
  const checklist = await loadVerifyChecklist(root);
  const now = new Date().toISOString();
  let changed = false;
  for (const proposed of DEFAULT_ITEMS) {
    if (checklist.items.some((item) => item.id === proposed.id)) continue;
    checklist.items.push({ ...proposed, status: "unverified", updatedAt: now });
    changed = true;
  }
  if (changed || checklist.items.length === 0) {
    checklist.updatedAt = now;
    await saveVerifyChecklist(root, checklist);
  }
  return checklist;
}

/** Create only the checklist items explicitly proposed by a checklist tool call. */
export async function createVerifyItems(
  root: string,
  items: readonly Pick<VerifyItem, "id" | "label" | "kind" | "phase">[],
): Promise<VerifyChecklist> {
  const checklist = await loadVerifyChecklist(root);
  const now = new Date().toISOString();
  for (const proposed of items) {
    if (!proposed.id.trim() || !proposed.label.trim()) continue;
    const existing = checklist.items.find((item) => item.id === proposed.id);
    if (existing) continue;
    checklist.items.push({
      id: proposed.id,
      label: proposed.label,
      status: "unverified",
      ...(proposed.kind ? { kind: proposed.kind } : {}),
      ...(proposed.phase ? { phase: proposed.phase } : {}),
      updatedAt: now,
    });
  }
  if (items.length > 0) {
    checklist.updatedAt = now;
    await saveVerifyChecklist(root, checklist);
  }
  return checklist;
}

/**
 * Resolve the status that will be persisted.
 * AI-originated `verified` marks become `ai-checked` so human approval remains mandatory.
 */
export function resolveVerifyMark(
  requested: VerifyStatus | "human",
  source: VerifyMarkSource = "ai",
): { status: VerifyStatus; approvedBy?: VerifyMarkSource } {
  if (requested === "human") {
    return { status: "verified", approvedBy: "human" };
  }
  if (requested === "verified") {
    if (source === "human") return { status: "verified", approvedBy: "human" };
    return { status: "ai-checked", approvedBy: "ai" };
  }
  if (requested === "ai-checked") {
    return { status: "ai-checked", approvedBy: "ai" };
  }
  return { status: requested, approvedBy: source };
}

export async function markVerifyItem(
  root: string,
  id: string,
  status: VerifyStatus | "human",
  notes?: string,
  kind?: CrosscheckKind,
  options?: { source?: VerifyMarkSource },
): Promise<VerifyChecklist> {
  const source = options?.source ?? "ai";
  const resolved = resolveVerifyMark(status, source);
  const checklist = await loadVerifyChecklist(root);
  const now = new Date().toISOString();
  const existing = checklist.items.find((item) => item.id === id);
  if (existing) {
    existing.status = resolved.status;
    existing.updatedAt = now;
    if (resolved.approvedBy !== undefined) existing.approvedBy = resolved.approvedBy;
    else delete existing.approvedBy;
    if (notes !== undefined) existing.notes = notes;
    if (kind !== undefined) existing.kind = kind;
  } else {
    const item: VerifyItem = {
      id,
      label: id,
      status: resolved.status,
      updatedAt: now,
      ...(resolved.approvedBy !== undefined ? { approvedBy: resolved.approvedBy } : {}),
      ...(kind ? { kind } : {}),
      ...(notes !== undefined ? { notes } : {}),
    };
    checklist.items.push(item);
  }
  checklist.updatedAt = now;
  await saveVerifyChecklist(root, checklist);
  return checklist;
}

/** Mark remaining open items as skipped with an explicit disclosure note. Does not satisfy the human gate. */
export async function skipUnverifiedItems(root: string, reason = "用户跳过核对"): Promise<VerifyChecklist> {
  const checklist = await loadVerifyChecklist(root);
  const now = new Date().toISOString();
  for (const item of checklist.items) {
    if (item.status === "unverified" || item.status === "ai-checked") {
      item.status = "skipped";
      item.updatedAt = now;
      item.approvedBy = "human";
      item.notes = item.notes ? `${item.notes}; ${reason}` : `${reason}（未经人核对；analysis/academic 收尾仍须人核实）`;
    }
  }
  checklist.updatedAt = now;
  await saveVerifyChecklist(root, checklist);
  return checklist;
}

function itemPhase(item: VerifyItem): VerifyPhase {
  return item.phase ?? "general";
}

export function isHumanVerified(item: VerifyItem): boolean {
  return item.status === "verified" && item.approvedBy !== "ai";
}

/**
 * Hard gate for analysis handoff and academic finalization.
 * Only human-approved `verified` items pass; AI checks and skips do not.
 */
export function evaluateHumanVerifyGate(
  checklist: VerifyChecklist,
  scope: HumanVerifyGateScope,
): HumanVerifyGateResult {
  const phases = new Set(SCOPE_PHASES[scope]);
  const relevant = checklist.items.filter((item) => phases.has(itemPhase(item)));
  const pending = relevant.filter((item) => !isHumanVerified(item));
  if (pending.length === 0 && relevant.length > 0) {
    return { ok: true, checklist };
  }
  const scopeLabel = scope === "analysis-complete" ? "分析收尾 / HANDOFF" : "学术定稿";
  const pendingText = pending.length > 0
    ? pending.map((item) => `${item.id}(${item.status})`).join(", ")
    : "清单为空或缺少默认项";
  return {
    ok: false,
    checklist,
    pending,
    message: [
      `人审硬门禁（${scopeLabel}）：须先完成 AI /crosscheck 与/或 /verify，再由人在 Panel「核实」或唤醒选项中批准。`,
      `未过人审：${pendingText}`,
      "跳过/AI 已核不算通过。人审不经斜杠命令，由收尾门禁自动要求。",
    ].join("\n"),
  };
}

export async function assertHumanVerifyGate(
  root: string,
  scope: HumanVerifyGateScope,
): Promise<HumanVerifyGateResult> {
  const checklist = await ensureDefaultVerifyChecklist(root);
  return evaluateHumanVerifyGate(checklist, scope);
}

export function formatVerifyChecklist(checklist: VerifyChecklist): string {
  const lines = [
    "交叉核验清单（AI /crosscheck 核查 → 人在 Panel 核实；analysis/academic 收尾强制人审）",
    `更新：${checklist.updatedAt}`,
  ];
  for (const item of checklist.items) {
    const mark = item.status === "verified" ? "[x]"
      : item.status === "ai-checked" ? "[A]"
        : item.status === "flagged" ? "[!]"
          : item.status === "skipped" ? "[~]"
            : "[ ]";
    const kind = item.kind ? `/${item.kind}` : "";
    const phase = item.phase ? ` · ${item.phase}` : "";
    const who = item.approvedBy ? ` · ${item.approvedBy}` : "";
    lines.push(`${mark} ${item.id}${kind}${phase}${who}: ${item.label}${item.notes ? ` — ${item.notes}` : ""}`);
  }
  lines.push("过程核对：/crosscheck [焦点]（数据、引文真实性、格式要求；可多视角合并）");
  lines.push("实质验证：/verify [焦点]（结果是否成立、引文/方法是否合理）");
  lines.push("人审：Panel「核实」或唤醒选项（收尾门禁自动要求；非斜杠命令）");
  return lines.join("\n");
}

export function isNaturalPlanConfirm(text: string): boolean {
  return /^(可以|确认|同意|好的|行|ok|okay|yes|y|继续|开始执行)([。.!！\s].*)?$/i.test(text.trim());
}
