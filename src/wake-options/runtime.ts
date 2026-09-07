import { randomUUID } from "node:crypto";
import { markVerifyItem, type VerifyStatus } from "../verify/checklist.js";
import {
  panelHub,
  type WakeOptionItem,
  type WakeOptionsAnswer,
  type WakeOptionsMode,
  type WakeOptionsPrompt,
} from "../panel/hub.js";

export interface WakeOptionsRequest {
  title: string;
  prompt?: string;
  mode: WakeOptionsMode;
  options: WakeOptionItem[];
  allowMultiple?: boolean;
  minSelections?: number;
  syncVerify?: boolean;
  timeoutMs?: number;
}

export interface WakeOptionsResult {
  status: "answered" | "cancelled" | "timeout";
  source: WakeOptionsAnswer["source"];
  selectedIds: string[];
  selectedLabels: string[];
  panelClients: number;
  verifySynced?: boolean;
  notes?: string;
}

function normalizeOptions(options: WakeOptionItem[]): WakeOptionItem[] {
  const seen = new Set<string>();
  const out: WakeOptionItem[] = [];
  for (const option of options) {
    const id = option.id.trim();
    const label = option.label.trim();
    if (!id || !label || seen.has(id)) continue;
    seen.add(id);
    out.push({
      id,
      label,
      ...(option.description?.trim() ? { description: option.description.trim() } : {}),
      ...(option.checked === true ? { checked: true } : {}),
    });
  }
  return out;
}

export function buildWakePrompt(request: WakeOptionsRequest, now = Date.now()): WakeOptionsPrompt {
  const options = normalizeOptions(request.options);
  if (options.length < 1) throw new Error("options must contain at least one item");
  const mode = request.mode;
  const allowMultiple = mode === "checklist" ? request.allowMultiple !== false : Boolean(request.allowMultiple);
  const timeoutMs = Math.min(Math.max(request.timeoutMs ?? 180_000, 5_000), 900_000);
  const id = `wake_${randomUUID().slice(0, 8)}`;
  return {
    id,
    title: request.title.trim() || "请选择",
    ...(request.prompt?.trim() ? { prompt: request.prompt.trim() } : {}),
    mode,
    options,
    allowMultiple,
    minSelections: request.minSelections ?? (mode === "choice" ? 1 : 0),
    syncVerify: request.syncVerify ?? mode === "checklist",
    createdAt: new Date(now).toISOString(),
    expiresAt: new Date(now + timeoutMs).toISOString(),
  };
}

export async function applyWakeVerifySync(
  root: string,
  prompt: WakeOptionsPrompt,
  selectedIds: string[],
): Promise<boolean> {
  if (!prompt.syncVerify) return false;
  const selected = new Set(selectedIds);
  for (const option of prompt.options) {
    const status: VerifyStatus = selected.has(option.id) ? "verified" : "unverified";
    await markVerifyItem(root, option.id, status, `wake-options:${prompt.id}`, undefined);
  }
  return true;
}

/**
 * Publish a wake-options prompt to Panel (SSE) and wait for an answer.
 * Caller may race this against a CLI UI promise.
 */
export function waitForPanelWakeAnswer(prompt: WakeOptionsPrompt, timeoutMs: number): Promise<WakeOptionsAnswer> {
  return panelHub.publishWake(prompt, timeoutMs);
}

export function resolvePanelWakeAnswer(answer: WakeOptionsAnswer): boolean {
  return panelHub.resolveWake(answer);
}

export function formatWakeResult(result: WakeOptionsResult): string {
  return JSON.stringify({ schemaVersion: "psyclaw/wake-options-result/v1", ...result }, null, 2);
}

export function labelsFor(prompt: WakeOptionsPrompt, ids: string[]): string[] {
  const map = new Map(prompt.options.map((item) => [item.id, item.label]));
  return ids.map((id) => map.get(id) ?? id);
}
