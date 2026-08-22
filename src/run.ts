/**
 * Staged progress output for psyclaw workflows: prints `[stage] label…` lines
 * the way a research pipeline reads. The stage tag is rendered in the psyclaw
 * accent color; notes are dimmed. Used by the `psyclaw_workflow` tool (captured
 * into the tool result) and by TTY sessions. Pure line formatting is exported
 * for tests.
 */

const ACCENT = "\x1b[36m"; // teal
const DIM = "\x1b[2m";
const RESET = "\x1b[0m";

export function formatStageLine(tag: string, label: string, color = true): string {
  const tagPart = color ? `${ACCENT}[${tag}]${RESET}` : `[${tag}]`;
  return `${tagPart} ${label}`;
}

export function formatNoteLine(note: string, color = true): string {
  return color ? `  ${DIM}${note}${RESET}` : `  ${note}`;
}

export interface StageRunnerOptions {
  /** Override stdout (tests). */
  write?: (line: string) => void;
  color?: boolean;
}

export interface StageRunner {
  /** Print `[tag] label…`, run `fn`, then print an optional completion note. */
  stage<T>(tag: string, label: string, fn: () => Promise<T>, onDone?: (result: T) => string): Promise<T>;
  note(message: string): void;
}

export function createStageRunner(options: StageRunnerOptions = {}): StageRunner {
  const write = options.write ?? ((line) => process.stdout.write(`${line}\n`));
  const color = options.color ?? process.stdout.isTTY;
  return {
    note(message: string): void {
      write(formatNoteLine(message, color));
    },
    async stage<T>(tag: string, label: string, fn: () => Promise<T>, onDone?: (result: T) => string): Promise<T> {
      write(formatStageLine(tag, `${label}…`, color));
      const result = await fn();
      if (onDone !== undefined) write(formatNoteLine(onDone(result), color));
      return result;
    },
  };
}
