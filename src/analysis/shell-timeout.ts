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

const SLOW_SCRIPT_MS = 3 * 60_000;
const SCRIPT_RUN = /\b(?:Rscript|python3?)\s+(?:-\S+\s+)*([\w./-]+\.(?:R|r|py))\b/;

/** The script a shell command runs as a whole (`Rscript results/analysis.R`), if any. */
export function scriptInCommand(command: string): string | undefined {
  return SCRIPT_RUN.exec(command)?.[1];
}

function minutes(ms: number): string {
  return (ms / 60_000).toFixed(1);
}

/**
 * Counts slow full runs of the same script and speaks up only from the second one, so a normal
 * run adds nothing to the context. The prompt rules alone did not stop runs from re-running a
 * 10–25 minute script after every small edit, without ever hitting the shell time limit.
 */
export class ShellClock {
  private readonly started = new Map<string, { at: number; script: string | undefined }>();
  private readonly scriptRuns = new Map<string, { count: number; ms: number }>();
  private readonly origin: number;

  constructor(
    private readonly now: () => number = Date.now,
    private readonly budgetMinutes: number | undefined = parseBudget(process.env.PSYCLAW_TIME_BUDGET_MINUTES),
  ) {
    this.origin = now();
  }

  start(toolName: string, toolCallId: string, command: string | undefined): void {
    if (!SHELL_TOOLS.has(toolName)) return;
    this.started.set(toolCallId, { at: this.now(), script: command ? scriptInCommand(command) : undefined });
  }

  /** A note for the tool result, or undefined when the command was quick. */
  finish(toolCallId: string): string | undefined {
    const entry = this.started.get(toolCallId);
    if (!entry) return undefined;
    this.started.delete(toolCallId);
    const elapsed = this.now() - entry.at;
    const lines: string[] = [];
    if (entry.script && elapsed >= SLOW_SCRIPT_MS) {
      const runs = this.scriptRuns.get(entry.script) ?? { count: 0, ms: 0 };
      runs.count += 1;
      runs.ms += elapsed;
      this.scriptRuns.set(entry.script, runs);
      if (runs.count >= 2) {
        lines.push(`[psyclaw] ${entry.script} has now run in full ${runs.count} times (${minutes(runs.ms)} min in total). Save fitted models and costly results to disk and rerun only the section you changed.`);
      }
    }
    if (lines.length > 0 && this.budgetMinutes !== undefined) {
      const left = this.budgetMinutes - (this.now() - this.origin) / 60_000;
      lines.push(`[psyclaw] About ${Math.max(0, Math.round(left))} of ${this.budgetMinutes} budget minutes remain.`);
    }
    return lines.length > 0 ? lines.join("\n") : undefined;
  }
}

function parseBudget(raw: string | undefined): number | undefined {
  const value = raw === undefined ? NaN : Number(raw);
  return Number.isFinite(value) && value > 0 ? value : undefined;
}
