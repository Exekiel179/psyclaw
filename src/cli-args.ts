export {
  CONTINUOUSLY_WORK_ENV,
  CONTINUOUSLY_WORK_FLAG,
  continuouslyWorkPrompt,
  continuouslyWorkWarningText,
  isContinuouslyWorkEnabled,
  peelContinuouslyWorkFlag,
} from "./session/continuously-work.js";

/** Pi flags that take a following value and must stay attached to that value. */
const SESSION_VALUE_FLAGS = new Set(["--session", "--session-dir", "--session-id"]);

/** Pi flags that resume or select a session without a required value. */
const SESSION_SWITCH_FLAGS = new Set(["--continue", "-c", "--resume", "-r"]);

/**
 * Map top-level session continuation flags to the bundled Pi runtime.
 *
 * Exit hints from the runtime print `psyclaw --session-dir … --session …`.
 * Those flags must be forwarded — not rejected as unknown PsyClaw commands.
 */
export function continueSessionArgs(command: string | undefined, args: readonly string[]): string[] | undefined {
  if (!command) return undefined;
  if (SESSION_SWITCH_FLAGS.has(command) || SESSION_VALUE_FLAGS.has(command)) {
    return [command, ...args];
  }
  return undefined;
}
