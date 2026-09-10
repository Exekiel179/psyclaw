import { afterEach, describe, expect, it } from "vitest";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";
import {
  captureAgentError,
  extractPiGeneration,
  filesystemErrorContext,
  fsWriteErrorMessage,
  injectBrowserObservabilityConfig,
  maybeShowTelemetryNotice,
  observabilityEnabled,
  OBS_CONFIG_SCRIPT_ID,
  parseTelemetryPreference,
  readBrowserObservabilityConfig,
  readNodeObservabilityConfig,
  readTelemetryEnvOverride,
  resolveTelemetryEnabled,
  sanitizeAgentEventProperties,
  setObservabilityHandleForTests,
  shouldShowTelemetryNotice,
  shutdownObservability,
  trackAgentEvent,
  trackGateWaiting,
  trackLlmGeneration,
  trackSkillInstall,
  initNodeObservability,
  isObservabilityActive,
  writeTelemetryPreference,
} from "../../src/observability/index.js";
import { DEFAULT_TELEMETRY_PREFERENCE } from "../../src/observability/preference.js";
import { PUBLIC_POSTHOG_KEY, PUBLIC_SENTRY_DSN } from "../../src/observability/public-keys.js";
import { posthogAiGenerationProperties } from "../../src/observability/llm.js";
import { readLangfuseConfig } from "../../src/observability/langfuse.js";
import { ensureAnonymousDistinctId, newAnonymousDistinctId } from "../../src/observability/identity.js";

describe("observability config", () => {
  it("fills public client credentials by default", () => {
    const config = readNodeObservabilityConfig({});
    expect(observabilityEnabled(config)).toBe(true);
    expect(config.sentryDsn).toBe(PUBLIC_SENTRY_DSN);
    expect(config.posthogKey).toBe(PUBLIC_POSTHOG_KEY);
    expect(config.posthogHost).toBe("https://us.posthog.com");
  });

  it("can omit public defaults when asked", () => {
    const config = readNodeObservabilityConfig({}, { publicDefaults: false });
    expect(observabilityEnabled(config)).toBe(false);
    expect(config.sentryDsn).toBeUndefined();
    expect(config.posthogKey).toBeUndefined();
  });

  it("lets env vars override the public credentials", () => {
    expect(readNodeObservabilityConfig({ SENTRY_DSN: " https://example@o/1 " }).sentryDsn).toBe("https://example@o/1");
    expect(readNodeObservabilityConfig({ POSTHOG_KEY: "phc_test" }).posthogKey).toBe("phc_test");
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
    expect(config.telemetryEnabled).toBe(true);
  });

  it("returns empty browser keys when telemetry is disabled", () => {
    const config = readBrowserObservabilityConfig({ PUBLIC_POSTHOG_KEY: "phc_public" }, "panel", { enabled: false });
    expect(config.sentryDsn).toBe("");
    expect(config.posthogKey).toBe("");
    expect(config.telemetryEnabled).toBe(false);
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

  it("keeps filesystem error metadata and drops research text", () => {
    const safe = sanitizeAgentEventProperties({
      errno: "EPERM",
      syscall: "mkdir",
      failed_path: "~/project/.psyclaw",
      cwd: "~/project",
      scope: "project",
      paper: "should not leak",
    });
    expect(safe).toEqual({
      errno: "EPERM",
      syscall: "mkdir",
      failed_path: "~/project/.psyclaw",
      cwd: "~/project",
      scope: "project",
    });
  });

  it("injects config into the placeholder script without embedding HTML", () => {
    const html = `<html><head><script id="${OBS_CONFIG_SCRIPT_ID}">window.__PSYCLAW_OBS__={"surface":"panel"};</script></head></html>`;
    const next = injectBrowserObservabilityConfig(html, {
      sentryDsn: "https://web@o/1",
      posthogKey: "",
      posthogHost: "https://us.posthog.com",
      surface: "panel",
      release: "psyclaw-web@0.0.0",
      telemetryEnabled: true,
      showTelemetryNotice: false,
      distinctId: "psyclaw:11111111-1111-4111-8111-111111111111",
    });
    expect(next).toContain(`id="${OBS_CONFIG_SCRIPT_ID}"`);
    expect(next).toContain("https://web@o/1");
    expect(next).toContain("psyclaw:11111111-1111-4111-8111-111111111111");
    expect(next).not.toContain("<script id=\"psyclaw-obs-config\">window.__PSYCLAW_OBS__={\"surface\":\"panel\"}");
  });
});

describe("telemetry preference", () => {
  it("defaults to enabled and notice not yet acknowledged", () => {
    expect(parseTelemetryPreference(undefined)).toEqual(DEFAULT_TELEMETRY_PREFERENCE);
    expect(parseTelemetryPreference({})).toEqual(DEFAULT_TELEMETRY_PREFERENCE);
    expect(parseTelemetryPreference({ telemetry: { enabled: false } })).toEqual({
      enabled: false,
      noticeAcknowledged: false,
    });
  });

  it("treats PSYCLAW_TELEMETRY as a process override", () => {
    expect(readTelemetryEnvOverride({})).toBeUndefined();
    expect(readTelemetryEnvOverride({ PSYCLAW_TELEMETRY: "0" })).toBe(false);
    expect(readTelemetryEnvOverride({ PSYCLAW_TELEMETRY: "off" })).toBe(false);
    expect(readTelemetryEnvOverride({ PSYCLAW_TELEMETRY: "1" })).toBe(true);
    expect(resolveTelemetryEnabled({ enabled: false, noticeAcknowledged: true }, { PSYCLAW_TELEMETRY: "1" })).toBe(true);
    expect(resolveTelemetryEnabled({ enabled: true, noticeAcknowledged: true }, { PSYCLAW_TELEMETRY: "0" })).toBe(false);
    expect(resolveTelemetryEnabled({ enabled: true, noticeAcknowledged: false }, {})).toBe(true);
    expect(resolveTelemetryEnabled({ enabled: false, noticeAcknowledged: true }, {})).toBe(false);
  });

  it("shows the startup notice once, not after ack, and not when forced off", () => {
    const unseen = { enabled: true, noticeAcknowledged: false };
    expect(shouldShowTelemetryNotice(unseen, {}, true)).toBe(true);
    expect(shouldShowTelemetryNotice(unseen, {}, false)).toBe(false);
    expect(shouldShowTelemetryNotice({ enabled: true, noticeAcknowledged: true }, {}, true)).toBe(false);
    expect(shouldShowTelemetryNotice(unseen, { PSYCLAW_TELEMETRY: "0" }, true)).toBe(false);
    expect(shouldShowTelemetryNotice(unseen, { CI: "true" }, true)).toBe(false);
  });

  it("persists enable/disable in psyclaw-settings.json without dropping other keys", async () => {
    const dir = await mkdtemp(join(tmpdir(), "psyclaw-telemetry-"));
    const settingsPath = join(dir, "psyclaw-settings.json");
    await writeFile(settingsPath, `${JSON.stringify({ psyclawPet: true }, null, 2)}\n`, "utf8");
    const next = await writeTelemetryPreference(
      { enabled: false, noticeAcknowledged: true },
      { settingsPath, now: new Date("2026-09-08T00:00:00.000Z") },
    );
    expect(next).toEqual({ enabled: false, noticeAcknowledged: true });
    const saved = JSON.parse(await readFile(settingsPath, "utf8")) as {
      psyclawPet?: unknown;
      telemetry?: { enabled?: unknown; noticeAcknowledged?: unknown };
    };
    expect(saved.psyclawPet).toBe(true);
    expect(saved.telemetry?.enabled).toBe(false);
    expect(saved.telemetry?.noticeAcknowledged).toBe(true);
  });

  it("records a disable choice from the startup notice", async () => {
    const dir = await mkdtemp(join(tmpdir(), "psyclaw-telemetry-notice-"));
    const settingsPath = join(dir, "psyclaw-settings.json");
    const next = await maybeShowTelemetryNotice({
      settingsPath,
      interactive: true,
      env: {},
      prompt: async () => "disable",
    });
    expect(next).toEqual({ enabled: false, noticeAcknowledged: true });
  });
});

describe("observability runtime gate", () => {
  afterEach(async () => {
    await shutdownObservability();
  });

  it("does not boot SDKs when the user opted out", async () => {
    let booted = 0;
    const enabled = await initNodeObservability({
      env: {},
      preference: { enabled: false, noticeAcknowledged: true },
      boot: async () => {
        booted += 1;
        return { captureEvent() {}, captureError() {}, async flush() {} };
      },
    });
    expect(enabled).toBe(false);
    expect(isObservabilityActive()).toBe(false);
    expect(booted).toBe(0);
  });

  it("does not boot SDKs when PSYCLAW_TELEMETRY=0", async () => {
    let booted = 0;
    await initNodeObservability({
      env: { PSYCLAW_TELEMETRY: "0" },
      preference: { enabled: true, noticeAcknowledged: true },
      boot: async () => {
        booted += 1;
        return { captureEvent() {}, captureError() {}, async flush() {} };
      },
    });
    expect(booted).toBe(0);
    expect(isObservabilityActive()).toBe(false);
  });

  it("boots with public credentials when telemetry is on and env keys are unset", async () => {
    const events: Array<{ name: string; properties: Record<string, unknown> }> = [];
    const errors: unknown[] = [];
    const enabled = await initNodeObservability({
      env: {},
      preference: { enabled: true, noticeAcknowledged: true, anonymousId: "psyclaw:aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" },
      boot: async (config) => {
        expect(config.posthogKey).toBe(PUBLIC_POSTHOG_KEY);
        expect(config.distinctId).toBe("psyclaw:aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");
        return {
          captureEvent(name, properties) { events.push({ name, properties }); },
          captureError(error, context) { errors.push({ error, context }); },
          captureLlmGeneration(input) { events.push({ name: "$ai_generation", properties: { model: input.model ?? "" } }); },
          async flush() {},
        };
      },
    });
    expect(enabled).toBe(true);
    await trackAgentEvent("research_run_started", { phase: "brief", goal: "secret research", status: "started" });
    await trackGateWaiting("plan_approval");
    await trackSkillInstall("queued", { skill_id: "session-handoff", scope: "user" });
    const perm = Object.assign(new Error("EPERM: mkdir"), { code: "EPERM", errno: -1, syscall: "mkdir", path: "/tmp/project/.psyclaw" });
    await captureAgentError(perm, { phase: "cli", cwd: `${homedir()}/secret-lab` });
    await trackLlmGeneration({ provider: "deepseek", model: "deepseek-v4-flash", usage: { input: 3, output: 2 } });
    expect(events).toEqual([
      { name: "research_run_started", properties: { phase: "brief", status: "started" } },
      { name: "gate_waiting_for_human", properties: { phase: "gate", gate: "plan_approval", status: "waiting" } },
      { name: "skill_install_queued", properties: { phase: "skill_install", status: "queued", skill_id: "session-handoff", scope: "user" } },
      { name: "$ai_generation", properties: { model: "deepseek-v4-flash" } },
    ]);
    expect(errors).toHaveLength(1);
    const errorContext = (errors[0] as { context?: Record<string, string> }).context;
    expect(errorContext).toMatchObject({
      phase: "cli",
      errno: "EPERM",
      syscall: "mkdir",
    });
    expect(errorContext?.cwd).toMatch(/^~/);
    expect(errorContext?.cwd).not.toContain(homedir());
  });

  it("drops events when no handle is installed", () => {
    setObservabilityHandleForTests(undefined);
    expect(() => trackAgentEvent("research_run_started", { phase: "cli" })).not.toThrow();
  });
});

describe("committed telemetry files", () => {
  it("keeps live client keys only in the public-keys module", async () => {
    const root = join(import.meta.dirname, "..", "..");
    const files = [
      ".env.example",
      "docs/telemetry.md",
      "apps/shared/observability.js",
      "apps/panel/index.html",
      "apps/website/index.html",
      "src/observability/config.ts",
      "src/observability/node-sdks.ts",
      "src/observability/langfuse.ts",
      "src/observability/llm.ts",
      "src/observability/identity.ts",
      "src/observability/error-context.ts",
    ];
    const forbidden = [
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
    const publicKeys = await readFile(join(root, "src/observability/public-keys.ts"), "utf8");
    expect(publicKeys).toContain("phc_zmztC3DEHRT88");
  });
});

describe("error context and identity", () => {
  it("extracts errno, syscall, and home-redacted paths from Node fs errors", () => {
    const error = Object.assign(new Error("EPERM"), {
      code: "EPERM",
      errno: -1,
      syscall: "mkdir",
      path: `${join("/home/researcher", "project", ".psyclaw")}`,
    });
    const context = filesystemErrorContext(error, { cwd: "/home/researcher/project" });
    expect(context.errno).toBe("EPERM");
    expect(context.syscall).toBe("mkdir");
    expect(context.failed_path).toContain(".psyclaw");
    expect(context.failed_path).not.toContain("secret-token");
  });

  it("explains unwritable project recommendation paths in Chinese", () => {
    const error = Object.assign(new Error("denied"), { code: "EPERM", syscall: "mkdir", path: "/tmp/proj/.psyclaw" });
    expect(fsWriteErrorMessage(error, "/tmp/proj/.psyclaw/recommendations.json", "project")).toContain("无法写入");
    expect(fsWriteErrorMessage(error, "/tmp/proj/.psyclaw/recommendations.json", "project")).toContain("EPERM");
    expect(fsWriteErrorMessage(error, "/tmp/proj/.psyclaw/recommendations.json", "project")).toContain("系统目录");
  });

  it("persists a stable anonymous distinct id in psyclaw-settings.json", async () => {
    const dir = await mkdtemp(join(tmpdir(), "psyclaw-distinct-"));
    const settingsPath = join(dir, "psyclaw-settings.json");
    const first = await ensureAnonymousDistinctId({ settingsPath });
    const second = await ensureAnonymousDistinctId({ settingsPath });
    expect(first).toMatch(/^psyclaw:[0-9a-f-]{36}$/i);
    expect(second).toBe(first);
    expect(newAnonymousDistinctId()).not.toBe(first);
  });
});

describe("LLM and Langfuse payloads", () => {
  it("builds PostHog $ai_generation properties without prompts or completions", () => {
    const properties = posthogAiGenerationProperties({
      provider: "deepseek",
      model: "deepseek-v4-flash",
      usage: { input: 10, output: 4, cacheRead: 2, cost: { total: 0.001 } },
      latencyMs: 1500,
    }, { distinctId: "psyclaw:id", sessionId: "session-1" });
    expect(properties.$ai_provider).toBe("deepseek");
    expect(properties.$ai_model).toBe("deepseek-v4-flash");
    expect(properties.$ai_input_tokens).toBe(10);
    expect(properties.$ai_output_tokens).toBe(4);
    expect(properties.$ai_latency).toBe(1.5);
    expect(properties.$ai_privacy_mode).toBe(true);
    expect(JSON.stringify(properties)).not.toContain("prompt");
    expect(properties.$ai_input).toBeUndefined();
    expect(properties.$ai_output_choices).toBeUndefined();
  });

  it("reads usage from Pi assistant messages and ignores user turns", () => {
    expect(extractPiGeneration({
      type: "message",
      message: {
        provider: "deepseek",
        model: "deepseek-v4-flash",
        usage: { input: 8, output: 2 },
      },
    })).toMatchObject({ provider: "deepseek", model: "deepseek-v4-flash", usage: { input: 8, output: 2 } });
    expect(extractPiGeneration({ type: "message", message: { role: "user", content: "研究目标" } })).toBeUndefined();
  });

  it("treats Langfuse as unset when keys are missing", () => {
    expect(readLangfuseConfig({})).toBeUndefined();
    expect(readLangfuseConfig({ LANGFUSE_PUBLIC_KEY: "pk-lf-test", LANGFUSE_SECRET_KEY: "sk-lf-test" })).toEqual({
      publicKey: "pk-lf-test",
      secretKey: "sk-lf-test",
      host: "https://cloud.langfuse.com",
    });
  });

  it("posts Langfuse generations without prompt or completion bodies", async () => {
    const { createLangfuseHandle } = await import("../../src/observability/langfuse.js");
    const bodies: string[] = [];
    const handle = createLangfuseHandle(
      { publicKey: "pk-lf-test", secretKey: "sk-lf-test", host: "https://cloud.langfuse.com" },
      {
        fetchImpl: (async (_url, init) => {
          bodies.push(String(init?.body ?? ""));
          return new Response("{}", { status: 207 });
        }) as typeof fetch,
      },
    );
    handle.captureGeneration(
      { provider: "deepseek", model: "deepseek-v4-flash", usage: { input: 2, output: 1 }, latencyMs: 10 },
      { sessionId: "session-1", userId: "psyclaw:id" },
    );
    await handle.flush();
    expect(bodies).toHaveLength(1);
    expect(bodies[0]).toContain("generation-create");
    expect(bodies[0]).not.toContain("prompt");
    expect(bodies[0]).not.toContain("$ai_input");
    expect(bodies[0]).not.toContain("研究目标");
  });
});
