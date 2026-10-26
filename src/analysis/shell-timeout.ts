/**
 * Default time limit for shell commands. Pi's bash tool has no default timeout, so one
 * slow model fit (or a full script re-run) could hold the agent idle for the whole session.
 */
export const DEFAULT_SHELL_TIMEOUT_SECONDS = 600;
export const MAX_SHELL_TIMEOUT_SECONDS = 1_800;

const SHELL_TOOLS = new Set(["bash", "powershell"]);
const TIMEOUT_MARK = "Command timed out after";

/** Fills in or caps `timeout` (seconds) on a shell tool call. Mutates the input in place, as Pi expects. */
export function applyShellTimeout(toolName: string, input: unknown): void {
  if (!SHELL_TOOLS.has(toolName) || !input || typeof input !== "object") return;
  const params = input as { timeout?: unknown };
  const current = typeof params.timeout === "number" && Number.isFinite(params.timeout) && params.timeout > 0 ? params.timeout : undefined;
  params.timeout = current === undefined ? DEFAULT_SHELL_TIMEOUT_SECONDS : Math.min(current, MAX_SHELL_TIMEOUT_SECONDS);
}

export function isShellTimeout(toolName: string, text: string): boolean {
  return SHELL_TOOLS.has(toolName) && text.includes(TIMEOUT_MARK);
}

export const SHELL_TIMEOUT_HINT = [
  "[psyclaw] The command hit the shell time limit and was stopped.",
  "Do not re-run it unchanged. Time the slow step on a subsample first, then use a faster equivalent",
  "(e.g. Satterthwaite instead of Kenward-Roger, fewer bootstrap draws, run only the changed part of the script),",
  `or pass a larger timeout (max ${MAX_SHELL_TIMEOUT_SECONDS}s) only when the estimated run time justifies it.`,
].join(" ");
