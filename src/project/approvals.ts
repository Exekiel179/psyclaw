import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { sha256File, sha256Text } from "../core/hash.js";
import { appendJsonl, readJsonl } from "./jsonl.js";
import { assertSafeProjectPath } from "./paths.js";

export const APPROVAL_SCHEMA = "psyclaw/approval/v1" as const;

export type ApprovalDecision = "approved" | "skipped" | "rejected" | "auto-approved";
/** Operational authorization only. Research-method decisions use the
 * separate `psyclaw/research-decision/v1` contract and must never be inferred
 * from an approval record. */
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

/**
 * `/run` authorizes ordinary planned execution. This list is intentionally
 * empty: researcher decisions are created dynamically only for unresolved,
 * consequential methodological trade-offs.
 */
export const DEFAULT_RUN_APPROVAL_NODES: readonly ApprovalNode[] = [];

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
