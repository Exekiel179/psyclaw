import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { sha256File, sha256Text } from "../core/hash.js";
import { appendJsonl, readJsonl } from "./jsonl.js";
import { assertSafeProjectPath } from "./paths.js";

export const APPROVAL_SCHEMA = "psyclaw/approval/v1" as const;

export type ApprovalDecision = "approved" | "skipped" | "rejected" | "auto-approved";
export type ApprovalKind = "document" | "run-mode" | "step" | "tool";

export interface ApprovalRecord {
  schemaVersion: typeof APPROVAL_SCHEMA;
  id: string;
  kind: ApprovalKind;
  nodeId: string;
  decision: ApprovalDecision;
  actor: "human" | "auto";
  at: string;
  runId?: string;
  path?: string;
  sha256?: string;
  summary: string;
}

export interface ApprovalNode {
  id: string;
  title: string;
  summary: string;
  required: boolean;
}

export const PRIMARY_PLAN_DOCUMENTS = [
  { id: "goal", path: "notes/goal.md", title: "研究目标" },
  { id: "research-spec", path: "notes/research-spec.md", title: "研究规格" },
  { id: "plan", path: "notes/plan.md", title: "执行计划" },
] as const;

export const DEFAULT_RUN_APPROVAL_NODES: readonly ApprovalNode[] = [
  { id: "scope", title: "范围与研究问题", summary: "确认研究范围、主要问题与排除边界", required: true },
  { id: "evidence", title: "证据收集方案", summary: "确认来源范围、检索方式与全文获取边界", required: true },
  { id: "analysis", title: "分析与方法决策", summary: "确认变量、排除、缺失值与分析方法", required: true },
  { id: "writing", title: "写作与主张边界", summary: "确认输出类型、引用与不确定性表达", required: true },
  { id: "review", title: "复核与交付", summary: "确认复核方式、格式与最终交付范围", required: false },
];

async function approvalPath(root: string): Promise<string> {
  return assertSafeProjectPath(root, ".psyclaw/approvals.jsonl");
}

export async function appendApproval(
  root: string,
  input: Omit<ApprovalRecord, "schemaVersion" | "id" | "at"> & { at?: string },
): Promise<ApprovalRecord> {
  const { at, ...fields } = input;
  const record: ApprovalRecord = {
    schemaVersion: APPROVAL_SCHEMA,
    id: `approval_${randomUUID().replaceAll("-", "")}`,
    at: at ?? new Date().toISOString(),
    ...fields,
  };
  await appendJsonl(await approvalPath(root), record);
  return record;
}

export async function readApprovals(root: string): Promise<ApprovalRecord[]> {
  return (await readJsonl<ApprovalRecord>(await approvalPath(root))).filter((row) => row.schemaVersion === APPROVAL_SCHEMA);
}

export async function approvePrimaryDocument(
  root: string,
  document: typeof PRIMARY_PLAN_DOCUMENTS[number],
  decision: Exclude<ApprovalDecision, "auto-approved">,
): Promise<ApprovalRecord> {
  const absolute = join(root, document.path);
  await readFile(absolute, "utf8");
  return appendApproval(root, {
    kind: "document",
    nodeId: document.id,
    decision,
    actor: "human",
    path: document.path,
    sha256: await sha256File(absolute),
    summary: document.title,
  });
}

export async function primaryPlanApprovalStatus(root: string): Promise<{
  ok: boolean;
  documents: Array<{ id: string; path: string; approved: boolean }>;
}> {
  const approvals = await readApprovals(root);
  const documents = await Promise.all(PRIMARY_PLAN_DOCUMENTS.map(async (document) => {
    const hash = await sha256File(join(root, document.path)).catch(() => "");
    const latest = approvals.filter((row) => row.kind === "document" && row.nodeId === document.id).at(-1);
    return { id: document.id, path: document.path, approved: latest?.decision === "approved" && latest.sha256 === hash };
  }));
  return { ok: documents.every((item) => item.approved), documents };
}

export function approvalInputDigest(input: unknown): string {
  return sha256Text(JSON.stringify(input));
}
