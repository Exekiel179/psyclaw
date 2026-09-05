/** Map top-level session continuation flags to the bundled Pi runtime. */
export function continueSessionArgs(command: string | undefined, args: readonly string[]): string[] | undefined {
  if (command !== "--continue" && command !== "-c") return undefined;
  return [command, ...args];
}

/** Strip developer-mode flags from argv and report whether they were present. */
export function extractDeveloperFlag(args: readonly string[]): { developer: boolean; rest: string[] } {
  const rest: string[] = [];
  let developer = false;
  for (const arg of args) {
    if (arg === "--developer" || arg === "-D") {
      developer = true;
      continue;
    }
    rest.push(arg);
  }
  return { developer, rest };
}

/** Enable gated slash commands (/verify, /model, /agents run) for this process. */
export function enableDeveloperCommands(): void {
  process.env.PSYCLAW_DEVELOPER_COMMANDS = "1";
}

export function developerCommandsEnabled(): boolean {
  return process.env.PSYCLAW_DEVELOPER_COMMANDS === "1";
}
