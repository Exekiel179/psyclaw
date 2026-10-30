/**
 * Optional Langfuse Cloud tracing via the public ingestion API or relay.
 *
 * Sentry Performance already owns the global OpenTelemetry TracerProvider
 * (`@sentry/node` init). Langfuse is therefore a separate REST client: no
 * second NodeSDK / TracerProvider is registered.
 * 
 * **Security**: Langfuse secret key grants full read/write access to the project.
 * It MUST NOT be embedded in publicly distributed builds. Options:
 * 1. User environment variables (LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY)
 * 2. Relay endpoint (LANGFUSE_RELAY_URL) that holds the secret securely
 * 
 * When all credentials are unset, every call is a no-op.
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

function trimEnv(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
}

/**
 * Read Langfuse config from environment. Returns undefined if credentials are incomplete.
 * Prefers relay (safer) over direct credentials.
 */
export function readLangfuseConfig(env: NodeJS.ProcessEnv = process.env): LangfuseConfig | LangfuseRelayConfig | undefined {
  // Prefer relay endpoint (no secret key exposure)
  const relayUrl = trimEnv(env.LANGFUSE_RELAY_URL);
  if (relayUrl) {
    return { relayUrl };
  }
  
  // Fall back to direct credentials (user's own Langfuse account)
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
  config: LangfuseConfig | LangfuseRelayConfig,
  options: { fetchImpl?: typeof fetch } = {},
): LangfuseHandle {
  const pending = new Set<Promise<void>>();
  const fetchImpl = options.fetchImpl ?? fetch;
  
  // Relay mode: no secret key in CLI, just forward to relay
  if ("relayUrl" in config) {
    const relayUrl = config.relayUrl;
    const enqueue = (batch: unknown): void => {
      const job = fetchImpl(relayUrl, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-langfuse-sdk-name": "psyclaw",
          "x-langfuse-sdk-version": PSYCLAW_VERSION,
        },
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
  
  // Direct mode: use user's own credentials
  const authorization = `Basic ${Buffer.from(`${config.publicKey}:${config.secretKey}`).toString("base64")}`;

  const enqueue = (batch: unknown): void => {
    const job = fetchImpl(`${config.host}/api/public/ingestion`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization,
        "x-langfuse-sdk-name": "psyclaw",
        "x-langfuse-sdk-version": PSYCLAW_VERSION,
      },
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
