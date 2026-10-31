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

  if (isRelayConfig(config)) {
    endpoint = `${config.relayUrl}/ingestion`;
    headers = {
      "content-type": "application/json",
      "x-langfuse-sdk-name": "psyclaw",
      "x-langfuse-sdk-version": PSYCLAW_VERSION,
    };
  } else {
    const authorization = `Basic ${Buffer.from(`${config.publicKey}:${config.secretKey}`).toString("base64")}`;
    endpoint = `${config.host}/api/public/ingestion`;
    headers = {
      "content-type": "application/json",
      authorization,
      "x-langfuse-sdk-name": "psyclaw",
      "x-langfuse-sdk-version": PSYCLAW_VERSION,
    };
  }

  const enqueue = (batch: unknown): void => {
    const job = fetchImpl(endpoint, {
      method: "POST",
      headers,
      body: JSON.stringify({
        batch,
        metadata: { batch_size: Array.isArray(batch) ? batch.length : 1, sdk_integration: "psyclaw" },
      }),
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
