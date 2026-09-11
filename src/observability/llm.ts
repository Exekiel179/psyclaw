/**
 * PostHog LLM analytics + Langfuse generation payloads for the Pi stack.
 *
 * PsyClaw talks to models through `@earendil-works/pi-ai` / pi-coding-agent,
 * not OpenAI/LangChain SDKs. Official PostHog guidance for that harness is
 * either `@posthog/pi` or manual `$ai_generation` capture. We capture manually
 * so events stay behind PsyClaw telemetry consent, share the CLI/panel
 * distinct_id, and never include prompts, completions, or tool I/O.
 */

import { randomUUID } from "node:crypto";
import { estimateUsageCost } from "../core/pricing.js";

export interface LlmUsage {
  input?: number;
  output?: number;
  cacheRead?: number;
  cacheWrite?: number;
  cost?: { total?: number };
}

export interface LlmGenerationInput {
  provider?: string;
  model?: string;
  usage?: LlmUsage;
  latencyMs?: number;
  error?: boolean;
  errorName?: string;
  httpStatus?: number;
  stream?: boolean;
  traceId?: string;
  sessionId?: string;
  spanName?: string;
  surface?: string;
}

export type PosthogAiPropertyValue = string | number | boolean;

function finiteNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

export function usageFromUnknown(value: unknown): LlmUsage | undefined {
  if (!value || typeof value !== "object") return undefined;
  const record = value as LlmUsage;
  if (
    finiteNumber(record.input) === undefined
    && finiteNumber(record.output) === undefined
    && finiteNumber(record.cacheRead) === undefined
  ) {
    return undefined;
  }
  return record;
}

/**
 * Pull token usage out of a Pi session / RPC event without reading message
 * content. Matches the shapes already used by the panel usage aggregator.
 */
export function extractPiGeneration(entry: unknown): LlmGenerationInput | undefined {
  if (!entry || typeof entry !== "object") return undefined;
  const record = entry as { type?: unknown; message?: unknown; usage?: unknown };
  if (record.type === "message" && record.message && typeof record.message === "object") {
    const message = record.message as {
      usage?: unknown;
      provider?: unknown;
      model?: unknown;
      responseModel?: unknown;
      errorMessage?: unknown;
      error?: unknown;
    };
    const usage = usageFromUnknown(message.usage);
    if (!usage) return undefined;
    const provider = typeof message.provider === "string" ? message.provider : undefined;
    const model = typeof message.responseModel === "string"
      ? message.responseModel
      : typeof message.model === "string"
        ? message.model
        : undefined;
    const error = Boolean(message.errorMessage) || Boolean(message.error);
    return {
      ...(provider === undefined ? {} : { provider }),
      ...(model === undefined ? {} : { model }),
      usage,
      error,
      spanName: "pi-message",
    };
  }
  if ((record.type === "agent_end" || record.type === "agent_settled") && record.message && typeof record.message === "object") {
    return extractPiGeneration({ type: "message", message: record.message });
  }
  if ((record.type === "branch_summary" || record.type === "compaction") && record.usage) {
    const usage = usageFromUnknown(record.usage);
    if (!usage) return undefined;
    return { provider: "summaries", model: "summaries", usage, spanName: String(record.type) };
  }
  return undefined;
}

export function lastPiGeneration(entries: readonly unknown[]): LlmGenerationInput | undefined {
  for (let index = entries.length - 1; index >= 0; index -= 1) {
    const found = extractPiGeneration(entries[index]);
    if (found) return found;
  }
  return undefined;
}

/** PostHog `$ai_generation` properties. Prompt/completion fields are omitted on purpose. */
export function posthogAiGenerationProperties(
  input: LlmGenerationInput,
  options: { distinctId: string; sessionId: string },
): Record<string, PosthogAiPropertyValue> {
  const provider = input.provider?.trim().slice(0, 80) || "unknown";
  const model = input.model?.trim().slice(0, 120) || "unknown";
  const usage = input.usage ?? {};
  const inputTokens = finiteNumber(usage.input) ?? 0;
  const outputTokens = finiteNumber(usage.output) ?? 0;
  const cacheRead = finiteNumber(usage.cacheRead) ?? 0;
  const cacheWrite = finiteNumber(usage.cacheWrite) ?? 0;
  const reportedCost = finiteNumber(usage.cost?.total);
  const estimatedCost = estimateUsageCost(usage, provider, model);
  const latencySeconds = finiteNumber(input.latencyMs) !== undefined
    ? Number(((input.latencyMs as number) / 1000).toFixed(4))
    : undefined;
  const properties: Record<string, PosthogAiPropertyValue> = {
    $ai_trace_id: (input.traceId ?? randomUUID()).slice(0, 80),
    $ai_session_id: (input.sessionId ?? options.sessionId).slice(0, 80),
    $ai_span_name: (input.spanName ?? "pi-generation").slice(0, 80),
    $ai_model: model,
    $ai_provider: provider,
    $ai_input_tokens: inputTokens,
    $ai_output_tokens: outputTokens,
    $ai_cache_read_tokens: cacheRead,
    $ai_cache_write_tokens: cacheWrite,
    $ai_http_status: input.httpStatus ?? (input.error ? 500 : 200),
    $ai_is_error: input.error === true,
    $ai_stream: input.stream === true,
    $ai_privacy_mode: true,
    surface: (input.surface ?? "cli").slice(0, 32),
    $process_person_profile: false,
  };
  if (latencySeconds !== undefined) properties.$ai_latency = latencySeconds;
  if (reportedCost !== undefined) properties.$ai_total_cost_usd = reportedCost;
  else if (estimatedCost > 0) properties.$ai_total_cost_usd = estimatedCost;
  if (input.errorName) properties.$ai_error = input.errorName.slice(0, 80);
  return properties;
}

export function langfuseGenerationBody(input: LlmGenerationInput, options: { sessionId: string; userId: string }) {
  const provider = input.provider?.trim().slice(0, 80) || "unknown";
  const model = input.model?.trim().slice(0, 120) || "unknown";
  const usage = input.usage ?? {};
  const inputTokens = finiteNumber(usage.input) ?? 0;
  const outputTokens = finiteNumber(usage.output) ?? 0;
  const cacheRead = finiteNumber(usage.cacheRead) ?? 0;
  const cacheWrite = finiteNumber(usage.cacheWrite) ?? 0;
  const started = new Date(Date.now() - (finiteNumber(input.latencyMs) ?? 0)).toISOString();
  const ended = new Date().toISOString();
  const traceId = input.traceId ?? randomUUID();
  const observationId = randomUUID();
  const reportedCost = finiteNumber(usage.cost?.total);
  const estimatedCost = estimateUsageCost(usage, provider, model);
  const cost = reportedCost ?? (estimatedCost > 0 ? estimatedCost : undefined);
  return {
    traceId,
    observationId,
    started,
    ended,
    ingest: {
      batch: [
        {
          id: randomUUID(),
          timestamp: ended,
          type: "trace-create",
          body: {
            id: traceId,
            timestamp: started,
            name: input.spanName ?? "pi-generation",
            sessionId: options.sessionId,
            userId: options.userId,
            metadata: {
              provider,
              surface: input.surface ?? "cli",
              privacyMode: true,
            },
          },
        },
        {
          id: randomUUID(),
          timestamp: ended,
          type: "generation-create",
          body: {
            id: observationId,
            traceId,
            name: input.spanName ?? "pi-generation",
            startTime: started,
            endTime: ended,
            model,
            usageDetails: {
              input: inputTokens,
              output: outputTokens,
              total: inputTokens + outputTokens + cacheRead + cacheWrite,
              cache_read: cacheRead,
              cache_write: cacheWrite,
            },
            ...(cost === undefined ? {} : { costDetails: { total: cost } }),
            level: input.error ? "ERROR" : "DEFAULT",
            ...(input.errorName === undefined ? {} : { statusMessage: input.errorName.slice(0, 200) }),
            metadata: {
              provider,
              surface: input.surface ?? "cli",
              privacyMode: true,
            },
          },
        },
      ],
    },
  };
}
