import { arch, platform } from "node:os";
import { PSYCLAW_VERSION } from "../branding.js";
import {
  observabilityEnabled,
  readNodeObservabilityConfig,
  sanitizeAgentEventProperties,
  type NodeObservabilityConfig,
} from "./config.js";
import { filesystemErrorContext, redactUserPath } from "./error-context.js";
import { ensureAnonymousDistinctId, newAnonymousDistinctId } from "./identity.js";
import type { LlmGenerationInput } from "./llm.js";
import type { ObservabilityHandle } from "./node-sdks.js";
import { readTelemetryPreference, resolveTelemetryEnabled, telemetryPreferenceOptions, type TelemetryPreference } from "./preference.js";

export {
  DEFAULT_LANGFUSE_HOST,
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
  parseAnonymousDistinctId,
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
export { ensureAnonymousDistinctId, newAnonymousDistinctId } from "./identity.js";
export { filesystemErrorContext, fsWriteErrorMessage, redactUserPath } from "./error-context.js";
export { extractPiGeneration, lastPiGeneration, posthogAiGenerationProperties } from "./llm.js";
export type { LlmGenerationInput } from "./llm.js";
export { readLangfuseConfig } from "./langfuse.js";

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
  const distinctId = preference.anonymousId
    ?? env.PSYCLAW_DISTINCT_ID?.trim()
    ?? (options.preference !== undefined && options.settingsPath === undefined
      ? newAnonymousDistinctId()
      : await ensureAnonymousDistinctId(telemetryPreferenceOptions(options.settingsPath)));
  const config = {
    ...readNodeObservabilityConfig(env),
    distinctId,
  };
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
  const extracted = filesystemErrorContext(error);
  const safeContext: Record<string, string> = {
    package_version: PSYCLAW_VERSION,
    os_platform: platform(),
    os_arch: arch(),
  };
  for (const [key, value] of Object.entries({ ...extracted, ...context })) {
    if (typeof value === "string" && value.trim()) {
      const limit = key === "failed_path" || key === "cwd" ? 240 : 80;
      const next = key === "failed_path" || key === "cwd" ? redactUserPath(value.trim()) : value.trim();
      safeContext[key] = next.slice(0, limit);
    }
  }
  return emitWhenReady((active) => active.captureError(error, safeContext));
}

export function trackGateWaiting(gate: "plan_approval" | "run_approval" | "tool_approval"): Promise<void> {
  return trackAgentEvent("gate_waiting_for_human", { phase: "gate", gate, status: "waiting" });
}

export function trackSkillInstall(status: "queued" | "started" | "finished" | "error", properties: Record<string, unknown> = {}): Promise<void> {
  return trackAgentEvent(`skill_install_${status === "queued" ? "queued" : status === "started" ? "started" : status === "error" ? "failed" : "finished"}`, {
    phase: "skill_install",
    status,
    ...properties,
  });
}

export function trackLlmGeneration(input: LlmGenerationInput): Promise<void> {
  return emitWhenReady((active) => {
    if (typeof active.captureLlmGeneration === "function") active.captureLlmGeneration(input);
  });
}

export async function withAgentSpan<T>(
  name: string,
  attributes: Record<string, string>,
  fn: () => Promise<T>,
): Promise<T> {
  if (bootPromise) await bootPromise;
  if (handle && typeof handle.runSpan === "function") return handle.runSpan(name, attributes, fn);
  return fn();
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
