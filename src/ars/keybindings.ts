import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { getAgentDir } from "@earendil-works/pi-coding-agent";

/** Pi default for app.thinking.cycle; PsyClaw reclaims it for academic mode. */
export const PI_DEFAULT_THINKING_CYCLE_KEY = "shift+tab";
/** Replacement binding so thinking level remains reachable. */
export const PSYCLAW_THINKING_CYCLE_KEY = "ctrl+shift+tab";

function bindsShiftTab(value: unknown): boolean {
  if (value === undefined) return true;
  if (typeof value === "string") return value === PI_DEFAULT_THINKING_CYCLE_KEY;
  if (Array.isArray(value)) {
    return value.length === 0 || value.includes(PI_DEFAULT_THINKING_CYCLE_KEY);
  }
  return false;
}

/**
 * Ensure Shift+Tab is free for academic mode by moving thinking-level cycle off
 * it when the user still has Pi's default (or no) binding.
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
  if (!bindsShiftTab(current)) {
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
