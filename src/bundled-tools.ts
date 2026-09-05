import { existsSync } from "node:fs";
import { delimiter, join } from "node:path";

export type WindowsArchitecture = "x64" | "arm64";

export function bundledWindowsToolsDir(
  packageRoot: string,
  platform: NodeJS.Platform = process.platform,
  architecture: string = process.arch,
): string | undefined {
  if (platform !== "win32" || (architecture !== "x64" && architecture !== "arm64")) return undefined;
  const directory = join(packageRoot, "vendor", "windows", architecture);
  if (!existsSync(join(directory, "fd.exe")) || !existsSync(join(directory, "rg.exe"))) return undefined;
  return directory;
}

export function withBundledWindowsTools(
  env: NodeJS.ProcessEnv,
  packageRoot: string,
  platform: NodeJS.Platform = process.platform,
  architecture: string = process.arch,
): NodeJS.ProcessEnv {
  const directory = bundledWindowsToolsDir(packageRoot, platform, architecture);
  if (directory === undefined) return { ...env };
  const currentPath = env.PATH ?? env.Path ?? "";
  const result = { ...env };
  delete result.Path;
  result.PATH = currentPath ? `${directory}${delimiter}${currentPath}` : directory;
  return result;
}
