/**
 * Opt-in browser observability for PsyClaw panel + website.
 *
 * Loads Sentry / PostHog from a CDN only when a DSN or project key is present
 * on window.__PSYCLAW_OBS__, a meta tag, or (local debug) a query param.
 * With those empty, this file is a no-op: no network calls, no SDK init.
 */
(function psyclawObservability() {
  if (window.__PSYCLAW_OBS_BOOTED__) return;
  window.__PSYCLAW_OBS_BOOTED__ = true;

  function meta(name) {
    const node = document.querySelector('meta[name="' + name + '"]');
    const value = node && node.getAttribute("content");
    return value ? String(value).trim() : "";
  }

  function param(name) {
    try {
      return new URLSearchParams(location.search).get(name) || "";
    } catch {
      return "";
    }
  }

  function readConfig() {
    const fromWindow = window.__PSYCLAW_OBS__ || {};
    const sentryDsn = String(fromWindow.sentryDsn || meta("psyclaw-sentry-dsn") || param("sentryDsn") || "").trim();
    const posthogKey = String(fromWindow.posthogKey || meta("psyclaw-posthog-key") || param("posthogKey") || "").trim();
    const posthogHost = String(
      fromWindow.posthogHost || meta("psyclaw-posthog-host") || param("posthogHost") || "https://us.posthog.com",
    ).trim();
    const surface = fromWindow.surface === "panel" || fromWindow.surface === "website" ? fromWindow.surface : "web";
    const release = String(fromWindow.release || "").trim();
    return { sentryDsn, posthogKey, posthogHost, surface, release };
  }

  async function loadEsm(url) {
    return import(url);
  }

  async function bootSentry(config) {
    const Sentry = await loadEsm("https://cdn.jsdelivr.net/npm/@sentry/browser@10/+esm");
    Sentry.init({
      dsn: config.sentryDsn,
      release: config.release || undefined,
      environment: "local",
      tracesSampleRate: 1.0,
      sendDefaultPii: false,
      integrations: typeof Sentry.browserTracingIntegration === "function" ? [Sentry.browserTracingIntegration()] : [],
    });
    window.Sentry = Sentry;
  }

  async function bootPostHog(config) {
    const mod = await loadEsm("https://cdn.jsdelivr.net/npm/posthog-js@1/+esm");
    const posthog = mod.default || mod.posthog || mod;
    const panel = config.surface === "panel";
    posthog.init(config.posthogKey, {
      api_host: config.posthogHost,
      person_profiles: "identified_only",
      autocapture: true,
      capture_pageview: true,
      capture_pageleave: true,
      persistence: "memory",
      mask_all_text: panel,
      mask_all_element_attributes: panel,
      session_recording: {
        maskAllInputs: true,
        maskTextSelector: panel
          ? ".markdown, .raw, .viewer-body, .event-detail, pre, code, textarea, [data-file]"
          : undefined,
      },
      loaded: function (client) {
        client.register({ surface: config.surface, app: "psyclaw" });
      },
    });
    window.posthog = posthog;
  }

  const config = readConfig();
  const jobs = [];
  if (config.sentryDsn) jobs.push(bootSentry(config).catch(function () {}));
  if (config.posthogKey) jobs.push(bootPostHog(config).catch(function () {}));
  if (jobs.length === 0) return;
  Promise.all(jobs).catch(function () {});
})();
