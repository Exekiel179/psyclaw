import type { Effect, ToolReceipt } from "../core/contracts.js";
import { sha256Text } from "../core/hash.js";

export interface ToolDescriptor {
  id: string;
  description: string;
  effect: Effect;
  source: string;
  trust: "builtin" | "approved" | "untrusted";
  enabled: boolean;
}

export interface ToolCall {
  runId: string;
  taskId: string;
  tool: string;
  input: unknown;
  idempotencyKey?: string;
}

export interface Approval {
  decision: "not-needed" | "approved" | "denied";
  actor: "policy" | "researcher";
  reason: string;
}

export interface Integration {
  list(): Promise<readonly ToolDescriptor[]>;
  health(): Promise<{ ok: boolean; reason?: string }>;
  invoke(call: ToolCall, approval: Approval): Promise<ToolReceipt>;
}

/**
 * Build a fail-closed receipt without copying an internal denial explanation
 * into an externally visible field. The explanation is retained only as a
 * digest so an audit can correlate identical failures without leaking text.
 */
export function denyByDefault(
  call: ToolCall,
  effect: Effect,
  reason: string,
  reasonCode = "integration.denied",
): ToolReceipt {
  const now = new Date().toISOString();
  const safeReasonCode = /^[a-z0-9][a-z0-9._-]{0,63}$/.test(reasonCode)
    ? reasonCode
    : "integration.denied";
  return {
    schemaVersion: "psyclaw/tool-receipt/v1",
    runId: call.runId,
    taskId: call.taskId,
    tool: call.tool,
    effect,
    approval: "denied",
    ...(call.idempotencyKey ? { idempotencyKey: call.idempotencyKey } : {}),
    ok: false,
    reasonCode: safeReasonCode,
    startedAt: now,
    finishedAt: now,
    resultHash: sha256Text(reason),
  };
}
