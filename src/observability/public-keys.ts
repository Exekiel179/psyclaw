/**
 * Bundled public client keys for PsyClaw product analytics.
 *
 * These are project DSN / PostHog project keys meant for client apps, not user
 * secrets. They are used only while telemetry is enabled (on by default; the
 * user may turn it off). Override any of them with the matching env var.
 */

export const PUBLIC_SENTRY_DSN =
  "https://b2b38f3bd3388684400e99b83baf2996@o4512050300911616.ingest.us.sentry.io/4512051818266624";

export const PUBLIC_SENTRY_DSN_WEB =
  "https://ccdf2394345c2a184955d005d49d5451@o4512050300911616.ingest.us.sentry.io/4512051822395392";

export const PUBLIC_POSTHOG_KEY = "phc_zmztC3DEHRT88FVxaFF7ihK7TmBqrzvbDQF7DARzr4P5";
