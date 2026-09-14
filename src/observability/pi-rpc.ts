/**
 * Shared wrap+track for Pi RPC `promptAndWait` LLM calls.
 * Never attaches prompts, completions, or tool I/O to spans or generations.
 */
import type { PiRpcMessage } from "../adapters/pi/rpc.js";
import { lastPiGeneration } from "./llm.js";
import { trackLlmGeneration, withAgentSpan } from "./index.js";

export interface ObservePiRpcCallOptions {
  phase: string;
  spanName: string;
  provider?: string;
  model?: string;
  timeoutMs?: number;
}

function fallbackProvider(options: ObservePiRpcCallOptions): string {
  return options.provider?.trim() || "unknown";
}

function fallbackModel(options: ObservePiRpcCallOptions): string {
  return options.model?.trim() || "unknown";
}

function spanAttributes(options: ObservePiRpcCallOptions): Record<string, string> {
  const attributes: Record<string, string> = {
    phase: options.phase,
    provider: fallbackProvider(options),
  };
  if (options.model?.trim()) attributes.model = options.model.trim();
  return attributes;
}

export async function observePiRpcPromptAndWait(
  client: { promptAndWait: (prompt: string, timeoutMs?: number) => Promise<PiRpcMessage[]> },
  prompt: string,
  options: ObservePiRpcCallOptions,
): Promise<PiRpcMessage[]> {
  const startedAt = Date.now();
  try {
    const events = await withAgentSpan(
      "cli.llm_call",
      spanAttributes(options),
      () => client.promptAndWait(prompt, options.timeoutMs),
    );
    const generation = lastPiGeneration(events);
    void trackLlmGeneration({
      provider: generation?.provider ?? fallbackProvider(options),
      model: generation?.model ?? fallbackModel(options),
      ...(generation?.usage === undefined ? {} : { usage: generation.usage }),
      latencyMs: Date.now() - startedAt,
      surface: "cli",
      spanName: options.spanName,
      ...(generation?.error === true ? { error: true } : {}),
      ...(generation?.errorName === undefined ? {} : { errorName: generation.errorName }),
    });
    return events;
  } catch (error) {
    void trackLlmGeneration({
      provider: fallbackProvider(options),
      model: fallbackModel(options),
      latencyMs: Date.now() - startedAt,
      error: true,
      errorName: error instanceof Error ? error.name : "Error",
      surface: "cli",
      spanName: options.spanName,
    });
    throw error;
  }
}
