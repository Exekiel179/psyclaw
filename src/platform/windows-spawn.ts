/**
 * Windows helpers for spawning npm/npx/pipx and other PATH shims that are
 * `.cmd` files. Prefer argv + `cmd.exe /d /c` over `shell: true` so quoting
 * stays under our control.
 */

export function resolveWindowsSpawn(
  command: string,
  args: readonly string[],
  platform: NodeJS.Platform = process.platform,
  comSpec: string = process.env.ComSpec ?? "cmd.exe",
): { command: string; args: string[] } {
  if (platform !== "win32") return { command, args: [...args] };
  // Absolute or extension-qualified executables can run without cmd.exe.
  if (/[\\/]/.test(command) || /\.(exe|cmd|bat|com)$/i.test(command)) {
    return { command, args: [...args] };
  }
  return { command: comSpec, args: ["/d", "/c", command, ...args] };
}

/** Whether package-manager installs should use a shell for `.cmd` resolution. */
export function useWindowsPackageManagerShell(platform: NodeJS.Platform = process.platform): boolean {
  return platform === "win32";
}
