export {
  CONTINUOUSLY_WORK_ALIASES,
  CONTINUOUSLY_WORK_ENV,
  CONTINUOUSLY_WORK_FLAG,
  continuouslyWorkPrompt,
  continuouslyWorkWarningText,
  isContinuouslyWorkEnabled,
  isContinuouslyWorkFlag,
  peelContinuouslyWorkFlag,
} from "./session/continuously-work.js";

/** Map top-level session continuation flags to the bundled Pi runtime. */
export function continueSessionArgs(command: string | undefined, args: readonly string[]): string[] | undefined {
  if (command !== "--continue" && command !== "-c") return undefined;
  return [command, ...args];
}

/**
 * Calm usage text for a leftover `--*` token that is not a known command.
 * Avoids the old `Unknown command: --continue-work` dump that looked like a crash.
 */
export function unknownFlagUsage(flag: string): string {
  return [
    `无法识别选项 ${flag}。`,
    "续接最近会话：psyclaw --continue  或  psyclaw -c",
    "持续自动推进：psyclaw --continuously-work  （也接受 --continue-work）",
    "查看全部用法：psyclaw --help",
  ].join("\n");
}
