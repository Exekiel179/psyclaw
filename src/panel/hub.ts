import type { ServerResponse } from "node:http";

export type WakeOptionsMode = "choice" | "checklist";

export interface WakeOptionItem {
  id: string;
  label: string;
  description?: string;
  /** Pre-checked for checklist mode. */
  checked?: boolean;
}

export interface WakeOptionsPrompt {
  id: string;
  title: string;
  prompt?: string;
  mode: WakeOptionsMode;
  options: WakeOptionItem[];
  allowMultiple?: boolean;
  minSelections?: number;
  /** When true (default for checklist), apply selections to `.psyclaw/verify-checklist.json`. */
  syncVerify?: boolean;
  createdAt: string;
  expiresAt: string;
}

export interface WakeOptionsAnswer {
  promptId: string;
  selectedIds: string[];
  source: "panel" | "cli" | "timeout" | "cancel";
  notes?: string;
}

export type PanelHubEvent =
  | { type: "assistant_start"; messageId: string }
  | { type: "assistant_delta"; messageId: string; delta: string; text: string }
  | { type: "assistant_end"; messageId: string; text: string }
  | { type: "agent_settled" }
  | { type: "user_echo"; text: string }
  | { type: "wake_options"; prompt: WakeOptionsPrompt }
  | { type: "wake_options_resolved"; promptId: string; answer: WakeOptionsAnswer }
  | { type: "ping"; at: string };

type WakeWaiter = {
  resolve: (answer: WakeOptionsAnswer) => void;
  reject: (error: Error) => void;
  timer: NodeJS.Timeout;
};

/**
 * In-process hub bridging the Pi CLI session and Panel SSE clients.
 * One process owns both the interactive session and the loopback Panel.
 */
export class PanelHub {
  private readonly clients = new Set<ServerResponse>();
  private readonly wakeWaiters = new Map<string, WakeWaiter>();
  private pendingWake: WakeOptionsPrompt | undefined;

  subscriberCount(): number {
    return this.clients.size;
  }

  /** True when at least one Panel browser tab is listening on SSE. */
  hasPanelClients(): boolean {
    return this.clients.size > 0;
  }

  getPendingWake(): WakeOptionsPrompt | undefined {
    return this.pendingWake;
  }

  subscribe(response: ServerResponse): () => void {
    this.clients.add(response);
    response.write(`event: ready\ndata: ${JSON.stringify({ ok: true, at: new Date().toISOString() })}\n\n`);
    if (this.pendingWake) {
      response.write(`event: wake_options\ndata: ${JSON.stringify({ type: "wake_options", prompt: this.pendingWake })}\n\n`);
    }
    return () => {
      this.clients.delete(response);
    };
  }

  broadcast(event: PanelHubEvent): void {
    const name = event.type;
    const payload = `event: ${name}\ndata: ${JSON.stringify(event)}\n\n`;
    for (const client of this.clients) {
      try {
        client.write(payload);
      } catch {
        this.clients.delete(client);
      }
    }
  }

  publishWake(prompt: WakeOptionsPrompt, timeoutMs: number): Promise<WakeOptionsAnswer> {
    if (this.wakeWaiters.has(prompt.id)) {
      return Promise.reject(new Error(`wake-options id already pending: ${prompt.id}`));
    }
    this.pendingWake = prompt;
    this.broadcast({ type: "wake_options", prompt });
    return new Promise<WakeOptionsAnswer>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.wakeWaiters.delete(prompt.id);
        if (this.pendingWake?.id === prompt.id) this.pendingWake = undefined;
        const answer: WakeOptionsAnswer = {
          promptId: prompt.id,
          selectedIds: [],
          source: "timeout",
        };
        this.broadcast({ type: "wake_options_resolved", promptId: prompt.id, answer });
        resolve(answer);
      }, timeoutMs);
      this.wakeWaiters.set(prompt.id, { resolve, reject, timer });
    });
  }

  resolveWake(answer: WakeOptionsAnswer): boolean {
    const waiter = this.wakeWaiters.get(answer.promptId);
    if (!waiter) return false;
    clearTimeout(waiter.timer);
    this.wakeWaiters.delete(answer.promptId);
    if (this.pendingWake?.id === answer.promptId) this.pendingWake = undefined;
    this.broadcast({ type: "wake_options_resolved", promptId: answer.promptId, answer });
    waiter.resolve(answer);
    return true;
  }

  cancelWake(promptId: string, source: "panel" | "cli" | "cancel" = "cancel"): boolean {
    return this.resolveWake({ promptId, selectedIds: [], source });
  }
}

/** Process-wide hub shared by workbench server and Pi panel extension. */
export const panelHub = new PanelHub();

/** Extract plain assistant text from a Pi AgentMessage-shaped object. */
export function extractAssistantText(message: unknown): string {
  if (!message || typeof message !== "object") return "";
  const row = message as { role?: unknown; content?: unknown };
  if (row.role !== undefined && row.role !== "assistant") return "";
  if (typeof row.content === "string") return row.content;
  if (!Array.isArray(row.content)) return "";
  return row.content.map((part) => {
    if (typeof part === "string") return part;
    if (!part || typeof part !== "object") return "";
    const item = part as { type?: unknown; text?: unknown };
    if (item.type === "text" && typeof item.text === "string") return item.text;
    return "";
  }).join("");
}

/** Extract streaming text delta from Pi assistantMessageEvent when present. */
export function extractAssistantDelta(assistantMessageEvent: unknown): string {
  if (!assistantMessageEvent || typeof assistantMessageEvent !== "object") return "";
  const event = assistantMessageEvent as { type?: unknown; delta?: unknown; text?: unknown };
  if (event.type === "text_delta" && typeof event.delta === "string") return event.delta;
  if (typeof event.delta === "string") return event.delta;
  return "";
}

export function messageIdOf(message: unknown, fallback: string): string {
  if (message && typeof message === "object") {
    const row = message as { id?: unknown };
    if (typeof row.id === "string" && row.id.trim()) return row.id;
  }
  return fallback;
}
