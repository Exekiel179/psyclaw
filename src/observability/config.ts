/**
 * Observability config. This module must not import Sentry or PostHog:
 * reading process.env and local preference is not telemetry, and tests rely
 * on that split.
 *
 * Product telemetry is on by default. Users can turn it off; PSYCLAW_TELEMETRY=0
 * forces it off for this process. Public client credentials are applied only
 * when telemetry is enabled.
 */

import { PSYCLAW_VERSION } from "../branding.js";
import {
  PUBLIC_POSTHOG_KEY,
  PUBLIC_SENTRY_DSN,
  PUBLIC_SENTRY_DSN_WEB,
} from "./public-keys.js";
import type { TelemetryPreference } from "./preference.js";
import { resolveTelemetryEnabled } from "./preference.js";

export const DEFAULT_POSTHOG_HOST = "https://us.posthog.com";
export const DEFAULT_LANGFUSE_HOST = "https://cloud.langfuse.com";
export const OBS_CONFIG_SCRIPT_ID = "psyclaw-obs-config";

const ALLOWED_EVENT_PROPERTIES = new Set([
  "phase",
  "status",
  "duration_ms",
  "mode",
  "skill_count",
  "command",
  "verdict",
  "gate",
  "surface",
  "error_name",
  "errno",
  "syscall",
  "failed_path",
  "cwd",
  "scope",
  "package_version",
  "os_platform",
  "os_arch",
  "skill_id",
  "provider",
  "model",
]);

const LONG_STRING_PROPERTIES = new Set(["failed_path", "cwd"]);
const STRING_LIMIT = 80;
const PATH_LIMIT = 240;

export interface NodeObservabilityConfig {
  sentryDsn?: string;
  posthogKey?: string;
  posthogHost: string;
  release: string;
  environment: string;
  langfusePublicKey?: string;
  langfuseSecretKey?: string;
  langfuseHost: string;
  distinctId?: string;
}

export interface BrowserObservabilityConfig {
  sentryDsn: string;
  posthogKey: string;
  posthogHost: string;
  surface: "panel" | "website";
  release: string;
  telemetryEnabled: boolean;
  showTelemetryNotice: boolean;
  distinctId: string;
}

export type AgentEventPropertyValue = string | number | boolean;

function trimEnv(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
}

export function observabilityEnabled(config: Pick<NodeObservabilityConfig, "sentryDsn" | "posthogKey">): boolean {
  return Boolean(config.sentryDsn || config.posthogKey);
}

export function emptyBrowserObservabilityConfig(
  surface: BrowserObservabilityConfig["surface"] = "panel",
): BrowserObservabilityConfig {
  return {
    sentryDsn: "",
    posthogKey: "",
    posthogHost: DEFAULT_POSTHOG_HOST,
    surface,
    release: `psyclaw-web@${PSYCLAW_VERSION}`,
    telemetryEnabled: false,
    showTelemetryNotice: false,
    distinctId: "",
  };
}

export function readNodeObservabilityConfig(
  env: NodeJS.ProcessEnv = process.env,
  options: { publicDefaults?: boolean } = {},
): NodeObservabilityConfig {
  const usePublic = options.publicDefaults !== false;
  const sentryDsn = trimEnv(env.SENTRY_DSN) ?? (usePublic ? PUBLIC_SENTRY_DSN : undefined);
  const posthogKey = trimEnv(env.POSTHOG_KEY) ?? (usePublic ? PUBLIC_POSTHOG_KEY : undefined);
  const posthogHost = trimEnv(env.POSTHOG_HOST) ?? DEFAULT_POSTHOG_HOST;
  const release = trimEnv(env.SENTRY_RELEASE) ?? `psyclaw@${PSYCLAW_VERSION}`;
  const environment = trimEnv(env.SENTRY_ENVIRONMENT) ?? trimEnv(env.NODE_ENV) ?? "local";
  const langfusePublicKey = trimEnv(env.LANGFUSE_PUBLIC_KEY);
  const langfuseSecretKey = trimEnv(env.LANGFUSE_SECRET_KEY);
  const langfuseHost = (trimEnv(env.LANGFUSE_HOST) ?? trimEnv(env.LANGFUSE_BASE_URL) ?? DEFAULT_LANGFUSE_HOST)
    .replace(/\/+$/, "");
  const distinctId = trimEnv(env.PSYCLAW_DISTINCT_ID);
  return {
    ...(sentryDsn === undefined ? {} : { sentryDsn }),
    ...(posthogKey === undefined ? {} : { posthogKey }),
    posthogHost,
    release,
    environment,
    ...(langfusePublicKey === undefined ? {} : { langfusePublicKey }),
    ...(langfuseSecretKey === undefined ? {} : { langfuseSecretKey }),
    langfuseHost,
    ...(distinctId === undefined ? {} : { distinctId }),
  };
}

export function readBrowserObservabilityConfig(
  env: NodeJS.ProcessEnv = process.env,
  surface: BrowserObservabilityConfig["surface"] = "panel",
  options: {
    enabled?: boolean;
    showTelemetryNotice?: boolean;
    publicDefaults?: boolean;
  } = {},
): BrowserObservabilityConfig {
  if (options.enabled === false) {
    return {
      ...emptyBrowserObservabilityConfig(surface),
      showTelemetryNotice: false,
    };
  }
  const usePublic = options.publicDefaults !== false;
  const sentryDsn =
    trimEnv(env.SENTRY_DSN_WEB) ?? trimEnv(env.PUBLIC_SENTRY_DSN) ?? (usePublic ? PUBLIC_SENTRY_DSN_WEB : undefined) ?? "";
  const posthogKey =
    trimEnv(env.PUBLIC_POSTHOG_KEY) ?? trimEnv(env.POSTHOG_KEY) ?? (usePublic ? PUBLIC_POSTHOG_KEY : undefined) ?? "";
  const posthogHost = trimEnv(env.PUBLIC_POSTHOG_HOST) ?? trimEnv(env.POSTHOG_HOST) ?? DEFAULT_POSTHOG_HOST;
  const release = trimEnv(env.SENTRY_RELEASE) ?? `psyclaw-web@${PSYCLAW_VERSION}`;
  return {
    sentryDsn,
    posthogKey,
    posthogHost,
    surface,
    release,
    telemetryEnabled: true,
    showTelemetryNotice: options.showTelemetryNotice === true,
    distinctId: "",
  };
}

export function browserConfigForPreference(
  env: NodeJS.ProcessEnv,
  preference: TelemetryPreference,
  surface: BrowserObservabilityConfig["surface"] = "panel",
): BrowserObservabilityConfig {
  const enabled = resolveTelemetryEnabled(preference, env);
  if (!enabled) return emptyBrowserObservabilityConfig(surface);
  return {
    ...readBrowserObservabilityConfig(env, surface, {
      enabled: true,
      showTelemetryNotice: !preference.noticeAcknowledged && env.PSYCLAW_SKIP_TELEMETRY_NOTICE !== "1" && env.CI !== "true" && env.CI !== "1",
    }),
    distinctId: preference.anonymousId ?? "",
  };
}

/** Drop anything that is not a coarse, non-content metadata field. */
export function sanitizeAgentEventProperties(
  properties: Record<string, unknown> = {},
): Record<string, AgentEventPropertyValue> {
  const safe: Record<string, AgentEventPropertyValue> = {};
  for (const [key, value] of Object.entries(properties)) {
    if (!ALLOWED_EVENT_PROPERTIES.has(key)) continue;
    if (typeof value === "number" && Number.isFinite(value)) {
      safe[key] = value;
      continue;
    }
    if (typeof value === "boolean") {
      safe[key] = value;
      continue;
    }
    if (typeof value === "string" && value.trim()) {
      const limit = LONG_STRING_PROPERTIES.has(key) ? PATH_LIMIT : STRING_LIMIT;
      safe[key] = value.trim().slice(0, limit);
    }
  }
  return safe;
}

function serializeBrowserConfig(config: BrowserObservabilityConfig): string {
  return JSON.stringify(config).replaceAll("<", "\\u003c").replaceAll("\u2028", "\\u2028").replaceAll("\u2029", "\\u2029");
}

/**
 * Replace the placeholder config script in static HTML, or insert one into
 * `<head>` when the marker is missing (tests, older copies).
 */
export function injectBrowserObservabilityConfig(html: string, config: BrowserObservabilityConfig): string {
  const json = serializeBrowserConfig(config);
  const script = `<script id="${OBS_CONFIG_SCRIPT_ID}">window.__PSYCLAW_OBS__=${json};</script>`;
  const pattern = new RegExp(`<script id="${OBS_CONFIG_SCRIPT_ID}">[\\s\\S]*?</script>`);
  if (pattern.test(html)) return html.replace(pattern, script);
  return html.replace(/<head([^>]*)>/i, `<head$1>\n${script}`);
}
