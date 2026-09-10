/**
 * Stable anonymous distinct_id shared by CLI (posthog-node) and the local panel
 * (posthog-js). Persisted in ~/.psyclaw/agent/psyclaw-settings.json so the two
 * surfaces can be joined without collecting an email or other identity.
 */

import { randomUUID } from "node:crypto";
import {
  parseTelemetryPreference,
  readPsyClawSettings,
  writeTelemetryPreference,
  type TelemetryPreference,
} from "./preference.js";

export { parseAnonymousDistinctId } from "./preference.js";

export function newAnonymousDistinctId(): string {
  return `psyclaw:${randomUUID()}`;
}

export async function ensureAnonymousDistinctId(options: { settingsPath?: string } = {}): Promise<string> {
  const settings = await readPsyClawSettings(options.settingsPath);
  const preference = parseTelemetryPreference(settings);
  if (preference.anonymousId) return preference.anonymousId;
  const next: TelemetryPreference = {
    ...preference,
    anonymousId: newAnonymousDistinctId(),
  };
  await writeTelemetryPreference(next, options);
  return next.anonymousId!;
}
