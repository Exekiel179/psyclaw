import {
  observabilityEnabled,
  readNodeObservabilityConfig,
  sanitizeAgentEventProperties,
  type NodeObservabilityConfig,
} from "./config.js";
import type { ObservabilityHandle } from "./node-sdks.js";

export {
  DEFAULT_POSTHOG_HOST,
  OBS_CONFIG_SCRIPT_ID,
  injectBrowserObservabilityConfig,
  observabilityEnabled,
  readBrowserObservabilityConfig,
  readNodeObservabilityConfig,
  sanitizeAgentEventProperties,
} from "./config.js";
export type { BrowserObservabilityConfig, NodeObservabilityConfig, AgentEventPropertyValue } from "./config.js";

type BootFn = (config: NodeObservabilityConfig) => Promise<ObservabilityHandle>;

let bootPromise: Promise<ObservabilityHandle | undefined> | undefined;
let handle: ObservabilityHandle | undefined;

async function defaultBoot(config: NodeObservabilityConfig): Promise<ObservabilityHandle> {
  const { bootNodeSdks } = await import("./node-sdks.js");
  return bootNodeSdks(config);
}

/**
 * Initialize Sentry and/or PostHog only when the matching env vars are set.
 * Safe to call more than once; the first call wins. With keys unset this
 * returns immediately and never imports an SDK.
 */
export async function initNodeObservability(options: {
  env?: NodeJS.ProcessEnv;
  boot?: BootFn;
} = {}): Promise<boolean> {
  const env = options.env ?? process.env;
  const config = readNodeObservabilityConfig(env);
  // Disabled must not latch the singleton: tests and late opt-in in a child
  // process still need to be able to boot when keys appear.
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
