import {
  observabilityEnabled,
  readNodeObservabilityConfig,
  sanitizeAgentEventProperties,
  type NodeObservabilityConfig,
} from "./config.js";
import type { ObservabilityHandle } from "./node-sdks.js";
import { isExpectedUserError } from "./expected.js";
import { readTelemetryPreference, resolveTelemetryEnabled, telemetryPreferenceOptions, type TelemetryPreference } from "./preference.js";

export {
  DEFAULT_POSTHOG_HOST,
  OBS_CONFIG_SCRIPT_ID,
  browserConfigForPreference,
  emptyBrowserObservabilityConfig,
  injectBrowserObservabilityConfig,
  observabilityEnabled,
  readBrowserObservabilityConfig,
  readNodeObservabilityConfig,
  sanitizeAgentEventProperties,
} from "./config.js";
export type { BrowserObservabilityConfig, NodeObservabilityConfig, AgentEventPropertyValue } from "./config.js";
export {
  DEFAULT_TELEMETRY_PREFERENCE,
  parseTelemetryPreference,
  psyclawSettingsPath,
  readTelemetryEnvOverride,
  readTelemetryPreference,
  resolveTelemetryEnabled,
  shouldShowTelemetryNotice,
  telemetryPreferenceOptions,
  writeTelemetryPreference,
} from "./preference.js";
export type { TelemetryPreference } from "./preference.js";
export { maybeShowTelemetryNotice } from "./notice.js";
export type { TelemetryNoticeChoice } from "./notice.js";
export { ExpectedUserError, isExpectedUserError, isExpectedUserErrorMessage } from "./expected.js";

type BootFn = (config: NodeObservabilityConfig) => Promise<ObservabilityHandle>;

let bootPromise: Promise<ObservabilityHandle | undefined> | undefined;
let handle: ObservabilityHandle | undefined;

async function defaultBoot(config: NodeObservabilityConfig): Promise<ObservabilityHandle> {
  const { bootNodeSdks } = await import("./node-sdks.js");
  return bootNodeSdks(config);
}

/**
 * Initialize Sentry and/or PostHog when product telemetry is enabled.
 * Safe to call more than once; the first call wins. Opted-out users and
 * PSYCLAW_TELEMETRY=0 never import an SDK.
 */
export async function initNodeObservability(options: {
  env?: NodeJS.ProcessEnv;
  boot?: BootFn;
  preference?: TelemetryPreference;
  settingsPath?: string;
} = {}): Promise<boolean> {
  const env = options.env ?? process.env;
  const preference = options.preference ?? await readTelemetryPreference(telemetryPreferenceOptions(options.settingsPath));
  if (!resolveTelemetryEnabled(preference, env)) {
    return handle !== undefined;
  }
  const config = readNodeObservabilityConfig(env);
  // Disabled must not latch the singleton: tests and a later enable in the
  // same process still need to be able to boot.
  if (!observabilityEnabled(config)) {
    return handle !== undefined;
  }
  if (!bootPromise) {
    const boot = options.boot ?? defaultBoot;
    bootPromise = boot(config).then((next) => {
      handle = next;
      return next;
    });
  }
  await bootPromise;
  return handle !== undefined;
}

export function isObservabilityActive(): boolean {
  return handle !== undefined;
}

export function trackAgentEvent(name: string, properties: Record<string, unknown> = {}): Promise<void> {
  const safe = sanitizeAgentEventProperties(properties);
  return emitWhenReady((active) => active.captureEvent(name, safe));
}

export function captureAgentError(error: unknown, context: Record<string, string> = {}): Promise<void> {
  if (isExpectedUserError(error)) return Promise.resolve();
  const safeContext: Record<string, string> = {};
  for (const [key, value] of Object.entries(context)) {
    if (typeof value === "string" && value.trim()) safeContext[key] = value.trim().slice(0, 80);
  }
  return emitWhenReady((active) => active.captureError(error, safeContext));
}

export function trackGateWaiting(gate: "plan_approval" | "run_approval" | "tool_approval"): Promise<void> {
  return trackAgentEvent("gate_waiting_for_human", { phase: "gate", gate, status: "waiting" });
}

export async function shutdownObservability(): Promise<void> {
  const active = handle;
  handle = undefined;
  bootPromise = undefined;
  if (active) await active.flush();
}

/** Test hook: swap the live handle without loading SDKs. */
export function setObservabilityHandleForTests(next: ObservabilityHandle | undefined): void {
  handle = next;
  bootPromise = Promise.resolve(next);
}

async function emitWhenReady(fn: (active: ObservabilityHandle) => void): Promise<void> {
  if (bootPromise) await bootPromise;
  if (handle) fn(handle);
}

export type { ObservabilityHandle };
