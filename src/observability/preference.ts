import { mkdir, readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import { atomicWriteFile } from "../project/jsonl.js";

export interface TelemetryPreference {
  enabled: boolean;
  noticeAcknowledged: boolean;
  /** Stable PostHog distinct_id shared by CLI and the local panel. */
  anonymousId?: string;
}

export const DEFAULT_TELEMETRY_PREFERENCE: TelemetryPreference = {
  enabled: true,
  noticeAcknowledged: false,
};

export function psyclawSettingsPath(settingsPath?: string): string {
  return settingsPath ?? join(getAgentDir(), "psyclaw-settings.json");
}

export function telemetryPreferenceOptions(settingsPath?: string, now?: Date): { settingsPath?: string; now?: Date } {
  return {
    ...(settingsPath === undefined ? {} : { settingsPath }),
    ...(now === undefined ? {} : { now }),
  };
}

const ANONYMOUS_ID_RE = /^psyclaw:[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function parseAnonymousDistinctId(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  return ANONYMOUS_ID_RE.test(trimmed) ? trimmed : undefined;
}

export function parseTelemetryPreference(settings: unknown): TelemetryPreference {
  if (!settings || typeof settings !== "object" || Array.isArray(settings)) {
    return { ...DEFAULT_TELEMETRY_PREFERENCE };
  }
  const telemetry = (settings as { telemetry?: unknown }).telemetry;
  if (!telemetry || typeof telemetry !== "object" || Array.isArray(telemetry)) {
    return { ...DEFAULT_TELEMETRY_PREFERENCE };
  }
  const record = telemetry as { enabled?: unknown; noticeAcknowledged?: unknown; anonymousId?: unknown };
  const anonymousId = parseAnonymousDistinctId(record.anonymousId);
  return {
    enabled: record.enabled !== false,
    noticeAcknowledged: record.noticeAcknowledged === true,
    ...(anonymousId === undefined ? {} : { anonymousId }),
  };
}

export async function readPsyClawSettings(settingsPath?: string): Promise<Record<string, unknown>> {
  const path = psyclawSettingsPath(settingsPath);
  try {
    const parsed = JSON.parse(await readFile(path, "utf8")) as unknown;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
  return {};
}

export async function readTelemetryPreference(options: { settingsPath?: string } = {}): Promise<TelemetryPreference> {
  return parseTelemetryPreference(await readPsyClawSettings(options.settingsPath));
}

export async function writeTelemetryPreference(
  patch: Partial<TelemetryPreference>,
  options: { settingsPath?: string; now?: Date } = {},
): Promise<TelemetryPreference> {
  const path = psyclawSettingsPath(options.settingsPath);
  const existing = await readPsyClawSettings(options.settingsPath);
  const current = parseTelemetryPreference(existing);
  const next: TelemetryPreference = {
    enabled: patch.enabled ?? current.enabled,
    noticeAcknowledged: patch.noticeAcknowledged ?? current.noticeAcknowledged,
    ...(patch.anonymousId ?? current.anonymousId
      ? { anonymousId: patch.anonymousId ?? current.anonymousId }
      : {}),
  };
  const previousTelemetry =
    existing.telemetry && typeof existing.telemetry === "object" && !Array.isArray(existing.telemetry)
      ? (existing.telemetry as Record<string, unknown>)
      : {};
  await mkdir(dirname(path), { recursive: true });
  await atomicWriteFile(
    path,
    `${JSON.stringify({
      ...existing,
      telemetry: {
        ...previousTelemetry,
        enabled: next.enabled,
        noticeAcknowledged: next.noticeAcknowledged,
        ...(next.anonymousId === undefined ? {} : { anonymousId: next.anonymousId }),
        updatedAt: (options.now ?? new Date()).toISOString(),
      },
    }, null, 2)}\n`,
  );
  return next;
}

/** `PSYCLAW_TELEMETRY=0` forces off; `=1` forces on. Unset means follow the saved preference. */
export function readTelemetryEnvOverride(env: NodeJS.ProcessEnv = process.env): boolean | undefined {
  const raw = env.PSYCLAW_TELEMETRY?.trim().toLowerCase();
  if (!raw) return undefined;
  if (raw === "0" || raw === "false" || raw === "off" || raw === "no") return false;
  if (raw === "1" || raw === "true" || raw === "on" || raw === "yes") return true;
  return undefined;
}

export function resolveTelemetryEnabled(
  preference: TelemetryPreference,
  env: NodeJS.ProcessEnv = process.env,
): boolean {
  const override = readTelemetryEnvOverride(env);
  if (override !== undefined) return override;
  return preference.enabled;
}

export function shouldShowTelemetryNotice(
  preference: TelemetryPreference,
  env: NodeJS.ProcessEnv = process.env,
  interactive = Boolean(process.stdin.isTTY && process.stdout.isTTY),
): boolean {
  if (preference.noticeAcknowledged) return false;
  if (!interactive) return false;
  if (env.CI === "true" || env.CI === "1") return false;
  if (env.PSYCLAW_SKIP_TELEMETRY_NOTICE === "1") return false;
  if (readTelemetryEnvOverride(env) === false) return false;
  return true;
}
