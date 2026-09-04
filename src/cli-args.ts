/** Map top-level session continuation flags to the bundled Pi runtime. */
export function continueSessionArgs(command: string | undefined, args: readonly string[]): string[] | undefined {
  if (command !== "--continue" && command !== "-c") return undefined;
  return [command, ...args];
}
