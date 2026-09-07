import { readFile } from "node:fs/promises";
import { atomicWriteFile } from "../project/jsonl.js";
import { assertSafeProjectPath } from "../project/paths.js";

export const VERIFY_CHECKLIST_SCHEMA = "psyclaw/verify-checklist/v1" as const;
export const VERIFY_CHECKLIST_PATH = ".psyclaw/verify-checklist.json" as const;

export type VerifyStatus = "unverified" | "verified" | "flagged" | "skipped";

/** Cross-check domains the model may propose; humans mark via Panel or /crosscheck. */
export type CrosscheckKind = "citations" | "format" | "requirements" | "stats" | "general";

export interface VerifyItem {
  id: string;
  label: string;
  status: VerifyStatus;
  kind?: CrosscheckKind;
  phase?: "pre-analysis" | "post-analysis" | "general";
  notes?: string;
  updatedAt?: string;
}

export interface VerifyChecklist {
  schemaVersion: typeof VERIFY_CHECKLIST_SCHEMA;
  items: VerifyItem[];
  updatedAt: string;
}

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

const VALID_STATUS = new Set<VerifyStatus>(["unverified", "verified", "flagged", "skipped"]);
const VALID_KIND = new Set<CrosscheckKind>(["citations", "format", "requirements", "stats", "general"]);

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
    && (row.kind === undefined || VALID_KIND.has(row.kind));
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

export async function markVerifyItem(
  root: string,
  id: string,
  status: VerifyStatus,
  notes?: string,
  kind?: CrosscheckKind,
): Promise<VerifyChecklist> {
  const checklist = await loadVerifyChecklist(root);
  const now = new Date().toISOString();
  const existing = checklist.items.find((item) => item.id === id);
  if (existing) {
    existing.status = status;
    existing.updatedAt = now;
    if (notes !== undefined) existing.notes = notes;
    if (kind !== undefined) existing.kind = kind;
  } else {
    const item: VerifyItem = {
      id,
      label: id,
      status,
      updatedAt: now,
      ...(kind ? { kind } : {}),
      ...(notes !== undefined ? { notes } : {}),
    };
    checklist.items.push(item);
  }
  checklist.updatedAt = now;
  await saveVerifyChecklist(root, checklist);
  return checklist;
}

/** Mark remaining unverified items as skipped with an explicit disclosure note. */
export async function skipUnverifiedItems(root: string, reason = "用户跳过核对"): Promise<VerifyChecklist> {
  const checklist = await loadVerifyChecklist(root);
  const now = new Date().toISOString();
  for (const item of checklist.items) {
    if (item.status === "unverified") {
      item.status = "skipped";
      item.updatedAt = now;
      item.notes = item.notes ? `${item.notes}; ${reason}` : `${reason}（未经人核对）`;
    }
  }
  checklist.updatedAt = now;
  await saveVerifyChecklist(root, checklist);
  return checklist;
}

export function formatVerifyChecklist(checklist: VerifyChecklist): string {
  const lines = [
    "交叉核验清单（模型提出项 + 人在 Panel/对话中勾选；跳过须标注未经核对）",
    `更新：${checklist.updatedAt}`,
  ];
  for (const item of checklist.items) {
    const mark = item.status === "verified" ? "[x]"
      : item.status === "flagged" ? "[!]"
        : item.status === "skipped" ? "[~]"
          : "[ ]";
    const kind = item.kind ? `/${item.kind}` : "";
    const phase = item.phase ? ` · ${item.phase}` : "";
    lines.push(`${mark} ${item.id}${kind}${phase}: ${item.label}${item.notes ? ` — ${item.notes}` : ""}`);
  }
  lines.push("用法：/crosscheck list | /crosscheck <id> verified|unverified|flagged|skipped [备注]");
  lines.push("也可：/crosscheck skip（其余未核项标为未经核对）| /crosscheck kind <citations|format|requirements|stats>");
  return lines.join("\n");
}

export function isNaturalPlanConfirm(text: string): boolean {
  return /^(可以|确认|同意|好的|行|ok|okay|yes|y|继续|开始执行)([。.!！\s].*)?$/i.test(text.trim());
}
