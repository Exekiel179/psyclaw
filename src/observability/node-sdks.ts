/**
 * Loaded only after telemetry is confirmed enabled. Importing this file will
 * pull in Sentry/PostHog; callers must keep that behind the preference gate.
 */

import { redactSecrets } from "../core/redact.js";
import type { AgentEventPropertyValue, NodeObservabilityConfig } from "./config.js";
import { isExpectedUserErrorMessage } from "./expected.js";

export interface ObservabilityHandle {
  captureEvent(name: string, properties: Record<string, AgentEventPropertyValue>): void;
  captureError(error: unknown, context?: Record<string, string>): void;
  flush(): Promise<void>;
}

function anonymousDistinctId(): string {
  return `psyclaw-cli:${process.pid}`;
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
        const exceptionText = values?.map((value) => value.value).find((value) => typeof value === "string");
        if (isExpectedUserErrorMessage(event.message ?? "") || (typeof exceptionText === "string" && isExpectedUserErrorMessage(exceptionText))) {
          return null;
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

  const distinctId = anonymousDistinctId();

  return {
    captureEvent(name, properties) {
      posthog?.capture({
        distinctId,
        event: name,
        properties: {
          ...properties,
          surface: "cli",
          $process_person_profile: false,
        },
      });
    },
    captureError(error, context = {}) {
      if (sentry) {
        sentry.withScope((scope) => {
          for (const [key, value] of Object.entries(context)) scope.setTag(key, value.slice(0, 80));
          sentry.captureException(error);
        });
      }
      if (posthog) {
        const err = error instanceof Error ? error : new Error(String(error));
        posthog.capture({
          distinctId,
          event: "agent_error",
          properties: {
            phase: context.phase ?? "unknown",
            error_name: err.name.slice(0, 80),
            surface: "cli",
            $process_person_profile: false,
          },
        });
      }
    },
    async flush() {
      await Promise.all([
        sentry ? sentry.flush(2000).then(() => undefined) : Promise.resolve(),
        posthog ? posthog.shutdown() : Promise.resolve(),
      ]);
    },
  };
}
