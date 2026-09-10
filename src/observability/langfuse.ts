/**
 * Optional Langfuse Cloud tracing via the public ingestion API.
 *
 * Sentry Performance already owns the global OpenTelemetry TracerProvider
 * (`@sentry/node` init). Langfuse is therefore a separate REST client: no
 * second NodeSDK / TracerProvider is registered. When LANGFUSE_PUBLIC_KEY or
 * LANGFUSE_SECRET_KEY is unset, every call is a no-op.
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

function trimEnv(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
}

export function readLangfuseConfig(env: NodeJS.ProcessEnv = process.env): LangfuseConfig | undefined {
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
  config: LangfuseConfig,
  options: { fetchImpl?: typeof fetch } = {},
): LangfuseHandle {
  const pending = new Set<Promise<void>>();
  const fetchImpl = options.fetchImpl ?? fetch;
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
