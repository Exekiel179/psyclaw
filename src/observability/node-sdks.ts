/**
 * Loaded only after telemetry is confirmed enabled. Importing this file will
 * pull in Sentry/PostHog; callers must keep that behind the preference gate.
 *
 * Init order (documented in docs/telemetry.md):
 * 1. Sentry.init — owns the global OpenTelemetry TracerProvider for Performance.
 * 2. PostHog Node client — product events + `$ai_generation`.
 * 3. Langfuse REST ingestion — optional, isolated from OTel (no second TracerProvider).
 */

import { randomUUID } from "node:crypto";
import { arch, platform } from "node:os";
import { PSYCLAW_VERSION } from "../branding.js";
import { redactSecrets } from "../core/redact.js";
import type { AgentEventPropertyValue, NodeObservabilityConfig } from "./config.js";
import { filesystemErrorContext, redactUserPath } from "./error-context.js";
import { createLangfuseHandle, readLangfuseConfig, type LangfuseHandle } from "./langfuse.js";
import { posthogAiGenerationProperties, type LlmGenerationInput } from "./llm.js";

export interface ObservabilityHandle {
  readonly distinctId?: string;
  captureEvent(name: string, properties: Record<string, AgentEventPropertyValue>): void;
  captureError(error: unknown, context?: Record<string, string>): void;
  captureLlmGeneration?(input: LlmGenerationInput): void;
  runSpan?<T>(name: string, attributes: Record<string, string>, fn: () => Promise<T>): Promise<T>;
  flush(): Promise<void>;
}

export async function bootNodeSdks(config: NodeObservabilityConfig): Promise<ObservabilityHandle> {
  const sentry = config.sentryDsn ? await import("@sentry/node") : undefined;
  if (sentry && config.sentryDsn) {
    sentry.init({
      dsn: config.sentryDsn,
      release: config.release,
      environment: config.environment,
      tracesSampleRate: 1.0,
      sendDefaultPii: false,
      includeLocalVariables: false,
      enableLogs: false,
      dataCollection: {
        userInfo: false,
        httpBodies: [],
      },
      beforeSend(event) {
        if (typeof event.message === "string") event.message = redactSecrets(event.message).slice(0, 500);
        const values = event.exception?.values;
        if (values) {
          for (const value of values) {
            if (typeof value.value === "string") value.value = redactSecrets(value.value).slice(0, 500);
          }
        }
        if (event.user) {
          event.user = event.user.id === undefined ? {} : { id: event.user.id };
        }
        return event;
      },
    });
  }

  const posthog = config.posthogKey
    ? new (await import("posthog-node")).PostHog(config.posthogKey, {
        host: config.posthogHost,
        flushAt: 1,
        flushInterval: 2000,
        disableGeoip: true,
      })
    : undefined;

  const distinctId = config.distinctId?.trim() || `psyclaw:${randomUUID()}`;
  const llmSessionId = randomUUID();
  const langfuseConfig = config.langfusePublicKey && config.langfuseSecretKey
    ? { publicKey: config.langfusePublicKey, secretKey: config.langfuseSecretKey, host: config.langfuseHost }
    : readLangfuseConfig();
  const langfuse: LangfuseHandle | undefined = langfuseConfig ? createLangfuseHandle(langfuseConfig) : undefined;

  const runtimeTags = (): Record<string, string> => ({
    package_version: PSYCLAW_VERSION,
    os_platform: platform(),
    os_arch: arch(),
  });

  return {
    distinctId,
    captureEvent(name, properties) {
      posthog?.capture({
        distinctId,
        event: name,
        properties: {
          ...properties,
          surface: properties.surface ?? "cli",
          $process_person_profile: false,
        },
      });
    },
    captureError(error, context = {}) {
      const extracted = filesystemErrorContext(error);
      const merged: Record<string, string> = {
        ...runtimeTags(),
        ...Object.fromEntries(
          Object.entries(extracted).filter((entry): entry is [string, string] => typeof entry[1] === "string" && entry[1].length > 0),
        ),
        ...context,
      };
      for (const key of ["cwd", "failed_path"] as const) {
        if (merged[key]) merged[key] = redactUserPath(merged[key]).slice(0, 240);
      }
      if (sentry) {
        sentry.withScope((scope) => {
          for (const [key, value] of Object.entries(merged)) {
            const limit = key === "failed_path" || key === "cwd" ? 240 : 80;
            scope.setTag(key, value.slice(0, limit));
          }
          sentry.captureException(error);
        });
      }
      if (posthog) {
        const err = error instanceof Error ? error : new Error(String(error));
        posthog.capture({
          distinctId,
          event: "agent_error",
          properties: {
            phase: merged.phase ?? "unknown",
            error_name: (merged.error_name ?? err.name).slice(0, 80),
            surface: merged.surface ?? "cli",
            ...(merged.errno === undefined ? {} : { errno: merged.errno.slice(0, 32) }),
            ...(merged.syscall === undefined ? {} : { syscall: merged.syscall.slice(0, 40) }),
            ...(merged.failed_path === undefined ? {} : { failed_path: merged.failed_path.slice(0, 240) }),
            ...(merged.cwd === undefined ? {} : { cwd: merged.cwd.slice(0, 240) }),
            ...(merged.scope === undefined ? {} : { scope: merged.scope.slice(0, 32) }),
            package_version: merged.package_version,
            os_platform: merged.os_platform,
            os_arch: merged.os_arch,
            $process_person_profile: false,
          },
        });
      }
    },
    captureLlmGeneration(input) {
      const properties = posthogAiGenerationProperties(input, { distinctId, sessionId: llmSessionId });
      posthog?.capture({
        distinctId,
        event: "$ai_generation",
        properties,
      });
      langfuse?.captureGeneration(input, { sessionId: llmSessionId, userId: distinctId });
    },
    async runSpan(name, attributes, fn) {
      if (!sentry) return fn();
      return sentry.startSpan({ name, op: "psyclaw", attributes }, async () => fn());
    },
    async flush() {
      await Promise.all([
        sentry ? sentry.flush(2000).then(() => undefined) : Promise.resolve(),
        posthog ? posthog.shutdown() : Promise.resolve(),
        langfuse ? langfuse.flush() : Promise.resolve(),
      ]);
    },
  };
}
