import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { getAgentDir } from "@earendil-works/pi-coding-agent";

/** Pi default for app.thinking.cycle; PsyClaw reclaims it for session modes. */
export const PI_DEFAULT_THINKING_CYCLE_KEY = "shift+tab";
/**
 * Thinking-level cycle. Prefer ctrl+shift+t: many terminals/macOS apps swallow
 * ctrl+shift+tab for their own tab switching, so that chord never reaches Pi.
 */
export const PSYCLAW_THINKING_CYCLE_KEY = "ctrl+shift+t";
/** Prior PsyClaw default that is unreliable in common terminals. */
export const LEGACY_PSYCLAW_THINKING_CYCLE_KEYS = ["ctrl+shift+tab"] as const;

function needsMigration(value: unknown): boolean {
  if (value === undefined) return true;
  if (typeof value === "string") {
    return value === PI_DEFAULT_THINKING_CYCLE_KEY
      || (LEGACY_PSYCLAW_THINKING_CYCLE_KEYS as readonly string[]).includes(value);
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return true;
    return value.every((item) =>
      item === PI_DEFAULT_THINKING_CYCLE_KEY
      || (LEGACY_PSYCLAW_THINKING_CYCLE_KEYS as readonly string[]).includes(item));
  }
  return false;
}

/**
 * Ensure Shift+Tab is free for session modes by moving thinking-level cycle off
 * it (and off the legacy ctrl+shift+tab chord that terminals often intercept).
 */
export async function ensureAcademicModeKeybindings(
  agentDir: string = getAgentDir(),
): Promise<{ path: string; updated: boolean; thinkingCycleKey: string }> {
  const path = join(agentDir, "keybindings.json");
  let config: Record<string, unknown> = {};
  try {
    const raw = JSON.parse(await readFile(path, "utf8")) as unknown;
    if (raw && typeof raw === "object" && !Array.isArray(raw)) {
      config = { ...(raw as Record<string, unknown>) };
    }
  } catch {
    // Missing or invalid file → create defaults.
  }

  const current = config["app.thinking.cycle"];
  if (!needsMigration(current)) {
    return {
      path,
      updated: false,
      thinkingCycleKey: typeof current === "string" ? current : PSYCLAW_THINKING_CYCLE_KEY,
    };
  }

  const next = {
    ...config,
    "app.thinking.cycle": PSYCLAW_THINKING_CYCLE_KEY,
  };
  await mkdir(agentDir, { recursive: true });
  await writeFile(path, `${JSON.stringify(next, null, 2)}\n`, "utf8");
  return { path, updated: true, thinkingCycleKey: PSYCLAW_THINKING_CYCLE_KEY };
}
