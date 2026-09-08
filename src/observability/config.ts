/**
 * Env-only observability config. This module must not import Sentry or PostHog:
 * reading process.env is not telemetry, and tests rely on that split.
 *
 * Keys are opt-in. Empty / unset values mean "do not initialize any SDK".
 */

import { PSYCLAW_VERSION } from "../branding.js";

export const DEFAULT_POSTHOG_HOST = "https://us.posthog.com";
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
]);

export interface NodeObservabilityConfig {
  sentryDsn?: string;
  posthogKey?: string;
  posthogHost: string;
  release: string;
  environment: string;
}

export interface BrowserObservabilityConfig {
  sentryDsn: string;
  posthogKey: string;
  posthogHost: string;
  surface: "panel" | "website";
  release: string;
}

export type AgentEventPropertyValue = string | number | boolean;

function trimEnv(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
}

export function observabilityEnabled(config: Pick<NodeObservabilityConfig, "sentryDsn" | "posthogKey">): boolean {
  return Boolean(config.sentryDsn || config.posthogKey);
}

export function readNodeObservabilityConfig(env: NodeJS.ProcessEnv = process.env): NodeObservabilityConfig {
  const sentryDsn = trimEnv(env.SENTRY_DSN);
  const posthogKey = trimEnv(env.POSTHOG_KEY);
  const posthogHost = trimEnv(env.POSTHOG_HOST) ?? DEFAULT_POSTHOG_HOST;
  const release = trimEnv(env.SENTRY_RELEASE) ?? `psyclaw@${PSYCLAW_VERSION}`;
  const environment = trimEnv(env.SENTRY_ENVIRONMENT) ?? trimEnv(env.NODE_ENV) ?? "local";
  return {
    ...(sentryDsn === undefined ? {} : { sentryDsn }),
    ...(posthogKey === undefined ? {} : { posthogKey }),
    posthogHost,
    release,
    environment,
  };
}

export function readBrowserObservabilityConfig(
  env: NodeJS.ProcessEnv = process.env,
  surface: BrowserObservabilityConfig["surface"] = "panel",
): BrowserObservabilityConfig {
  const sentryDsn = trimEnv(env.SENTRY_DSN_WEB) ?? trimEnv(env.PUBLIC_SENTRY_DSN) ?? "";
  const posthogKey = trimEnv(env.PUBLIC_POSTHOG_KEY) ?? trimEnv(env.POSTHOG_KEY) ?? "";
  const posthogHost = trimEnv(env.PUBLIC_POSTHOG_HOST) ?? trimEnv(env.POSTHOG_HOST) ?? DEFAULT_POSTHOG_HOST;
  const release = trimEnv(env.SENTRY_RELEASE) ?? `psyclaw-web@${PSYCLAW_VERSION}`;
  return { sentryDsn, posthogKey, posthogHost, surface, release };
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
      safe[key] = value.trim().slice(0, 80);
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
