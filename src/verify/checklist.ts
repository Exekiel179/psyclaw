import { readFile } from "node:fs/promises";
import { atomicWriteFile } from "../project/jsonl.js";
import { assertSafeProjectPath } from "../project/paths.js";

export const VERIFY_CHECKLIST_SCHEMA = "psyclaw/verify-checklist/v1" as const;
export const VERIFY_CHECKLIST_PATH = ".psyclaw/verify-checklist.json" as const;

export type VerifyStatus = "unverified" | "verified" | "flagged";

export interface VerifyItem {
  id: string;
  label: string;
  status: VerifyStatus;
  notes?: string;
  updatedAt?: string;
}

export interface VerifyChecklist {
  schemaVersion: typeof VERIFY_CHECKLIST_SCHEMA;
  items: VerifyItem[];
  updatedAt: string;
}

const DEFAULT_ITEMS: readonly Omit<VerifyItem, "status">[] = [
  { id: "n", label: "样本量 / N" },
  { id: "primary-effect", label: "主效应 / 主要结果" },
  { id: "table-text", label: "表与正文一致" },
  { id: "method-match", label: "方法与实际分析一致" },
  { id: "key-claim", label: "关键主张有结果支撑" },
];

export function defaultVerifyChecklist(now = new Date().toISOString()): VerifyChecklist {
  return {
    schemaVersion: VERIFY_CHECKLIST_SCHEMA,
    updatedAt: now,
    items: DEFAULT_ITEMS.map((item) => ({ ...item, status: "unverified" as const })),
  };
}

export async function loadVerifyChecklist(root: string): Promise<VerifyChecklist> {
  const path = await assertSafeProjectPath(root, VERIFY_CHECKLIST_PATH);
  try {
    const parsed = JSON.parse(await readFile(path, "utf8")) as Partial<VerifyChecklist>;
    if (parsed.schemaVersion !== VERIFY_CHECKLIST_SCHEMA || !Array.isArray(parsed.items)) {
      return defaultVerifyChecklist();
    }
    return {
      schemaVersion: VERIFY_CHECKLIST_SCHEMA,
      updatedAt: typeof parsed.updatedAt === "string" ? parsed.updatedAt : new Date().toISOString(),
      items: parsed.items.filter((item): item is VerifyItem =>
        Boolean(item && typeof item.id === "string" && typeof item.label === "string" &&
          (item.status === "unverified" || item.status === "verified" || item.status === "flagged"))),
    };
  } catch {
    return defaultVerifyChecklist();
  }
}

export async function saveVerifyChecklist(root: string, checklist: VerifyChecklist): Promise<void> {
  const path = await assertSafeProjectPath(root, VERIFY_CHECKLIST_PATH);
  await atomicWriteFile(path, `${JSON.stringify(checklist, null, 2)}\n`);
}

export async function markVerifyItem(
  root: string,
  id: string,
  status: VerifyStatus,
  notes?: string,
): Promise<VerifyChecklist> {
  const checklist = await loadVerifyChecklist(root);
  const now = new Date().toISOString();
  const existing = checklist.items.find((item) => item.id === id);
  if (existing) {
    existing.status = status;
    existing.updatedAt = now;
    if (notes !== undefined) existing.notes = notes;
  } else {
    const item: VerifyItem = { id, label: id, status, updatedAt: now };
    if (notes !== undefined) item.notes = notes;
    checklist.items.push(item);
  }
  checklist.updatedAt = now;
  await saveVerifyChecklist(root, checklist);
  return checklist;
}

export function formatVerifyChecklist(checklist: VerifyChecklist): string {
  const lines = ["核查清单（AI 语义核查 + 人确认；非 SHA 学术过关）", `更新：${checklist.updatedAt}`];
  for (const item of checklist.items) {
    const mark = item.status === "verified" ? "[x]" : item.status === "flagged" ? "[!]" : "[ ]";
    lines.push(`${mark} ${item.id}: ${item.label}${item.notes ? ` — ${item.notes}` : ""}`);
  }
  lines.push("用法：/verify list | /verify <id> verified|unverified|flagged [备注]");
  return lines.join("\n");
}
