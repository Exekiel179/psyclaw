/**
 * Optional Langfuse Cloud tracing via the public ingestion API.
 *
 * Sentry Performance already owns the global OpenTelemetry TracerProvider
 * (`@sentry/node` init). Langfuse is therefore a separate REST client: no
 * second NodeSDK / TracerProvider is registered.
 *
 * Two modes:
 * 1. Direct ingestion (local dev): Requires LANGFUSE_PUBLIC_KEY and
 *    LANGFUSE_SECRET_KEY. Uses Basic auth directly to Langfuse host.
 * 2. Relay ingestion (production): Requires LANGFUSE_RELAY_URL. Posts to
 *    the relay without auth; the relay adds credentials and forwards to Langfuse.
 *
 * When neither mode is configured, every call is a no-op.
 */

import { PSYCLAW_VERSION } from "../branding.js";
import { DEFAULT_LANGFUSE_HOST } from "./config.js";
import type { LlmGenerationInput } from "./llm.js";
import { langfuseGenerationBody } from "./llm.js";

export { DEFAULT_LANGFUSE_HOST };

export interface LangfuseConfig {
  publicKey: string;
  secretKey: string;
  host: string;
}

export interface LangfuseRelayConfig {
  relayUrl: string;
}

export type LangfuseClientConfig = LangfuseConfig | LangfuseRelayConfig;

function isRelayConfig(config: LangfuseClientConfig): config is LangfuseRelayConfig {
  return "relayUrl" in config;
}

function trimEnv(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
}

export function readLangfuseConfig(env: NodeJS.ProcessEnv = process.env): LangfuseClientConfig | undefined {
  const relayUrl = trimEnv(env.LANGFUSE_RELAY_URL);
  if (relayUrl) {
    return { relayUrl: relayUrl.replace(/\/+$/, "") };
  }
  const publicKey = trimEnv(env.LANGFUSE_PUBLIC_KEY);
  const secretKey = trimEnv(env.LANGFUSE_SECRET_KEY);
  if (!publicKey || !secretKey) return undefined;
  const host = (trimEnv(env.LANGFUSE_HOST) ?? trimEnv(env.LANGFUSE_BASE_URL) ?? DEFAULT_LANGFUSE_HOST)
    .replace(/\/+$/, "");
  return { publicKey, secretKey, host };
}

export interface LangfuseHandle {
  captureGeneration(input: LlmGenerationInput, options: { sessionId: string; userId: string }): void;
  flush(): Promise<void>;
}

export function createLangfuseHandle(
  config: LangfuseClientConfig,
  options: { fetchImpl?: typeof fetch } = {},
): LangfuseHandle {
  const pending = new Set<Promise<void>>();
  const fetchImpl = options.fetchImpl ?? fetch;

  let endpoint: string;
  let headers: Record<string, string>;
  let useOtel: boolean;

  if (isRelayConfig(config)) {
    // Relay mode: still send legacy format to /ingestion
    // The relay worker will convert to OTEL
    endpoint = `${config.relayUrl}/ingestion`;
    headers = {
      "content-type": "application/json",
      "x-langfuse-sdk-name": "psyclaw",
      "x-langfuse-sdk-version": PSYCLAW_VERSION,
    };
    useOtel = false;
  } else {
    // Direct mode: use OTEL endpoint
    const authorization = `Basic ${Buffer.from(`${config.publicKey}:${config.secretKey}`).toString("base64")}`;
    endpoint = `${config.host}/api/public/otel/v1/traces`;
    headers = {
      "content-type": "application/json",
      authorization,
      "x-langfuse-sdk-name": "psyclaw",
      "x-langfuse-sdk-version": PSYCLAW_VERSION,
      "x-langfuse-ingestion-version": "4",
    };
    useOtel = true;
  }

  const enqueue = (batch: unknown): void => {
    const payload = useOtel ? convertLegacyBatchToOTLP({ batch, metadata: {} }) : {
      batch,
      metadata: { batch_size: Array.isArray(batch) ? batch.length : 1, sdk_integration: "psyclaw" },
    };

    const job = fetchImpl(endpoint, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    }).then((response) => {
      if (!response.ok) return undefined;
      return undefined;
    }).catch(() => undefined).then(() => undefined);
    pending.add(job);
    void job.finally(() => pending.delete(job));
  };

  return {
    captureGeneration(input, ids) {
      try {
        enqueue(langfuseGenerationBody(input, ids).ingest.batch);
      } catch {
        /* never break the agent on telemetry */
      }
    },
    async flush() {
      await Promise.allSettled([...pending]);
    },
  };
}

interface OTLPAttribute {
  key: string;
  value: { stringValue?: string; intValue?: string; doubleValue?: number };
}

interface OTLPSpan {
  traceId: string;
  spanId: string;
  name: string;
  kind: number;
  startTimeUnixNano: string;
  endTimeUnixNano: string;
  attributes: OTLPAttribute[];
  status?: { code: number; message?: string };
}

interface OTLPPayload {
  resourceSpans: Array<{
    resource: {
      attributes: OTLPAttribute[];
    };
    scopeSpans: Array<{
      scope: {
        name: string;
        version: string;
      };
      spans: OTLPSpan[];
    }>;
  }>;
}

/**
 * Convert legacy Langfuse batch format to OTLP/HTTP JSON format.
 */
function convertLegacyBatchToOTLP(payload: { batch: unknown; metadata: unknown }): OTLPPayload {
  const batchArray = Array.isArray(payload.batch) ? payload.batch : [];
  const spans: OTLPSpan[] = [];

  // Group events by trace ID to build parent-child relationships
  const traceMap = new Map<string, Record<string, unknown>>();
  const generationMap = new Map<string, Record<string, unknown>>();

  // First pass: collect trace and generation data
  for (const event of batchArray) {
    const eventRecord = event as { type?: string; body?: Record<string, unknown> };
    if (eventRecord.type === "trace-create" && eventRecord.body?.id) {
      traceMap.set(String(eventRecord.body.id), eventRecord.body);
    } else if (eventRecord.type === "generation-create" && eventRecord.body?.id) {
      generationMap.set(String(eventRecord.body.id), eventRecord.body);
    }
  }

  // Second pass: build OTLP spans
  for (const event of batchArray) {
    const eventRecord = event as { type?: string; body?: Record<string, unknown> };
    if (eventRecord.type === "generation-create" && eventRecord.body) {
      const gen = eventRecord.body;
      const trace = gen.traceId ? traceMap.get(String(gen.traceId)) : undefined;

      // Convert timestamps to nanoseconds
      const startTimeNanos = dateToNanos(String(gen.startTime));
      const endTimeNanos = dateToNanos(String(gen.endTime));

      // Build OTLP span
      const span: OTLPSpan = {
        traceId: hexToBase64(String(gen.traceId)),
        spanId: hexToBase64(String(gen.id)),
        name: String(gen.name || "generation"),
        kind: 1, // SPAN_KIND_INTERNAL
        startTimeUnixNano: startTimeNanos,
        endTimeUnixNano: endTimeNanos,
        attributes: [
          { key: "langfuse.observation.type", value: { stringValue: "generation" } },
          { key: "langfuse.observation.id", value: { stringValue: String(gen.id) } },
          { key: "langfuse.trace.id", value: { stringValue: String(gen.traceId) } },
        ],
      };

      // Add trace-level attributes from trace-create event
      if (trace) {
        if (trace.name) {
          span.attributes.push({ key: "langfuse.trace.name", value: { stringValue: String(trace.name) } });
        }
        if (trace.sessionId) {
          span.attributes.push({ key: "langfuse.session.id", value: { stringValue: String(trace.sessionId) } });
        }
        if (trace.userId) {
          span.attributes.push({ key: "langfuse.user.id", value: { stringValue: String(trace.userId) } });
        }
        if (trace.metadata && typeof trace.metadata === "object") {
          for (const [key, value] of Object.entries(trace.metadata as Record<string, unknown>)) {
            span.attributes.push({
              key: `langfuse.trace.metadata.${key}`,
              value: { stringValue: String(value) },
            });
          }
        }
      }

      // Add generation-specific attributes
      if (gen.model) {
        span.attributes.push({ key: "gen_ai.system", value: { stringValue: "langfuse" } });
        span.attributes.push({ key: "gen_ai.request.model", value: { stringValue: String(gen.model) } });
      }

      // Add usage details
      if (gen.usageDetails && typeof gen.usageDetails === "object") {
        const usage = gen.usageDetails as Record<string, unknown>;
        if (usage.input !== undefined) {
          span.attributes.push({
            key: "gen_ai.usage.input_tokens",
            value: { intValue: String(usage.input) },
          });
        }
        if (usage.output !== undefined) {
          span.attributes.push({
            key: "gen_ai.usage.output_tokens",
            value: { intValue: String(usage.output) },
          });
        }
        if (usage.total !== undefined) {
          span.attributes.push({
            key: "langfuse.usage.total",
            value: { intValue: String(usage.total) },
          });
        }
        if (usage.cache_read !== undefined) {
          span.attributes.push({
            key: "langfuse.usage.cache_read",
            value: { intValue: String(usage.cache_read) },
          });
        }
        if (usage.cache_write !== undefined) {
          span.attributes.push({
            key: "langfuse.usage.cache_write",
            value: { intValue: String(usage.cache_write) },
          });
        }
      }

      // Add cost details
      if (gen.costDetails && typeof gen.costDetails === "object") {
        const cost = (gen.costDetails as Record<string, unknown>).total;
        if (cost !== undefined) {
          span.attributes.push({
            key: "langfuse.usage.cost",
            value: { doubleValue: Number(cost) },
          });
        }
      }

      // Add level/status
      if (gen.level) {
        span.attributes.push({
          key: "langfuse.observation.level",
          value: { stringValue: String(gen.level) },
        });
        // Map ERROR level to OTEL status
        if (gen.level === "ERROR") {
          span.status = { code: 2 }; // STATUS_CODE_ERROR
        }
      }

      // Add status message
      if (gen.statusMessage) {
        span.attributes.push({
          key: "langfuse.observation.status_message",
          value: { stringValue: String(gen.statusMessage) },
        });
        if (!span.status) {
          span.status = { code: 2, message: String(gen.statusMessage) };
        }
      }

      // Add metadata
      if (gen.metadata && typeof gen.metadata === "object") {
        for (const [key, value] of Object.entries(gen.metadata as Record<string, unknown>)) {
          span.attributes.push({
            key: `langfuse.observation.metadata.${key}`,
            value: { stringValue: String(value) },
          });
        }
      }

      spans.push(span);
    }
  }

  // Build OTLP payload
  return {
    resourceSpans: [
      {
        resource: {
          attributes: [
            { key: "service.name", value: { stringValue: "psyclaw" } },
          ],
        },
        scopeSpans: [
          {
            scope: {
              name: "psyclaw",
              version: PSYCLAW_VERSION,
            },
            spans,
          },
        ],
      },
    ],
  };
}

/**
 * Convert ISO 8601 timestamp to nanoseconds since Unix epoch
 */
function dateToNanos(dateString: string): string {
  return String(new Date(dateString).getTime() * 1_000_000);
}

/**
 * Convert hex trace/span ID to base64 for OTLP
 */
function hexToBase64(hexString: string): string {
  // Remove any hyphens (UUID format)
  const clean = hexString.replace(/-/g, "");

  // Pad to 32 chars (16 bytes) for trace ID or 16 chars (8 bytes) for span ID
  const padded = clean.length === 32 ? clean : clean.padStart(32, "0");

  // Convert hex to bytes
  const bytes: number[] = [];
  for (let i = 0; i < padded.length; i += 2) {
    bytes.push(parseInt(padded.substr(i, 2), 16));
  }

  // Convert to base64
  return Buffer.from(bytes).toString("base64");
}
