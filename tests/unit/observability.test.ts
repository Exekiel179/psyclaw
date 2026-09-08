import { afterEach, describe, expect, it } from "vitest";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import {
  captureAgentError,
  injectBrowserObservabilityConfig,
  observabilityEnabled,
  OBS_CONFIG_SCRIPT_ID,
  readBrowserObservabilityConfig,
  readNodeObservabilityConfig,
  sanitizeAgentEventProperties,
  setObservabilityHandleForTests,
  shutdownObservability,
  trackAgentEvent,
  trackGateWaiting,
  initNodeObservability,
  isObservabilityActive,
} from "../../src/observability/index.js";

describe("observability config", () => {
  it("treats unset env as disabled and never invents keys", () => {
    const config = readNodeObservabilityConfig({});
    expect(observabilityEnabled(config)).toBe(false);
    expect(config.sentryDsn).toBeUndefined();
    expect(config.posthogKey).toBeUndefined();
    expect(config.posthogHost).toBe("https://us.posthog.com");
  });

  it("enables independently for Sentry and PostHog", () => {
    expect(observabilityEnabled(readNodeObservabilityConfig({ SENTRY_DSN: " https://example@o/1 " }))).toBe(true);
    expect(observabilityEnabled(readNodeObservabilityConfig({ POSTHOG_KEY: "phc_test" }))).toBe(true);
    expect(readNodeObservabilityConfig({ POSTHOG_HOST: "https://eu.posthog.com" }).posthogHost).toBe("https://eu.posthog.com");
  });

  it("reads browser keys from public aliases and does not use the Node DSN", () => {
    const config = readBrowserObservabilityConfig({
      SENTRY_DSN: "https://node-dsn@o/1",
      SENTRY_DSN_WEB: "https://web-dsn@o/2",
      PUBLIC_POSTHOG_KEY: "phc_public",
      POSTHOG_KEY: "phc_server",
    }, "panel");
    expect(config.sentryDsn).toBe("https://web-dsn@o/2");
    expect(config.posthogKey).toBe("phc_public");
    expect(config.surface).toBe("panel");
  });

  it("falls back to POSTHOG_KEY for the panel when PUBLIC_POSTHOG_KEY is unset", () => {
    const config = readBrowserObservabilityConfig({ POSTHOG_KEY: "phc_only" }, "website");
    expect(config.posthogKey).toBe("phc_only");
    expect(config.sentryDsn).toBe("");
  });

  it("strips research-content-like properties from agent events", () => {
    const safe = sanitizeAgentEventProperties({
      phase: "brief",
      status: "blocked",
      duration_ms: 12,
      goal: "社交支持与研究生心理健康",
      paper: "full manuscript text",
      email: "researcher@example.com",
      command: "brief",
    });
    expect(safe).toEqual({ phase: "brief", status: "blocked", duration_ms: 12, command: "brief" });
  });

  it("injects config into the placeholder script without embedding HTML", () => {
    const html = `<html><head><script id="${OBS_CONFIG_SCRIPT_ID}">window.__PSYCLAW_OBS__={"surface":"panel"};</script></head></html>`;
    const next = injectBrowserObservabilityConfig(html, {
      sentryDsn: "https://web@o/1",
      posthogKey: "",
      posthogHost: "https://us.posthog.com",
      surface: "panel",
      release: "psyclaw-web@0.0.0",
    });
    expect(next).toContain(`id="${OBS_CONFIG_SCRIPT_ID}"`);
    expect(next).toContain("https://web@o/1");
    expect(next).not.toContain("<script id=\"psyclaw-obs-config\">window.__PSYCLAW_OBS__={\"surface\":\"panel\"}");
  });
});

describe("observability runtime gate", () => {
  afterEach(async () => {
    await shutdownObservability();
  });

  it("does not boot SDKs when env vars are unset", async () => {
    let booted = 0;
    const enabled = await initNodeObservability({
      env: {},
      boot: async () => {
        booted += 1;
        return { captureEvent() {}, captureError() {}, async flush() {} };
      },
    });
    expect(enabled).toBe(false);
    expect(isObservabilityActive()).toBe(false);
    expect(booted).toBe(0);
  });

  it("boots once when a key is present and no-ops event capture onto the handle", async () => {
    const events: Array<{ name: string; properties: Record<string, unknown> }> = [];
    const errors: unknown[] = [];
    const enabled = await initNodeObservability({
      env: { POSTHOG_KEY: "phc_test" },
      boot: async () => ({
        captureEvent(name, properties) { events.push({ name, properties }); },
        captureError(error) { errors.push(error); },
        async flush() {},
      }),
    });
    expect(enabled).toBe(true);
    await trackAgentEvent("research_run_started", { phase: "brief", goal: "secret research", status: "started" });
    await trackGateWaiting("plan_approval");
    await captureAgentError(new Error("boom"), { phase: "cli" });
    expect(events).toEqual([
      { name: "research_run_started", properties: { phase: "brief", status: "started" } },
      { name: "gate_waiting_for_human", properties: { phase: "gate", gate: "plan_approval", status: "waiting" } },
    ]);
    expect(errors).toHaveLength(1);
  });

  it("drops events when no handle is installed", () => {
    setObservabilityHandleForTests(undefined);
    expect(() => trackAgentEvent("research_run_started", { phase: "cli" })).not.toThrow();
  });
});

describe("committed telemetry files", () => {
  it("does not embed live Sentry DSNs or PostHog project keys", async () => {
    const root = join(import.meta.dirname, "..", "..");
    const files = [
      ".env.example",
      "docs/telemetry.md",
      "apps/shared/observability.js",
      "apps/panel/index.html",
      "apps/website/index.html",
      "src/observability/config.ts",
      "src/observability/node-sdks.ts",
    ];
    const forbidden = [
      "ingest.us.sentry.io",
      "b2b38f3bd338",
      "ccdf2394345c",
      "phc_zmztC3DEHRT88",
    ];
    for (const relative of files) {
      const text = await readFile(join(root, relative), "utf8");
      for (const needle of forbidden) {
        expect(text, `${relative} must not contain ${needle}`).not.toContain(needle);
      }
    }
  });
});
