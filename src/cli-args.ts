export {
  CONTINUOUSLY_WORK_ENV,
  CONTINUOUSLY_WORK_FLAG,
  continuouslyWorkPrompt,
  continuouslyWorkWarningText,
  isContinuouslyWorkEnabled,
  peelContinuouslyWorkFlag,
} from "./session/continuously-work.js";

/** Map top-level session continuation flags to the bundled Pi runtime. */
export function continueSessionArgs(command: string | undefined, args: readonly string[]): string[] | undefined {
  if (command !== "--continue" && command !== "-c") return undefined;
  return [command, ...args];
}
