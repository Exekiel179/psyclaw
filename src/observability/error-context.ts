/**
 * Coarse filesystem / runtime context for agent_error and Sentry tags.
 * Home directories are rewritten to `~` so usernames do not leave the machine.
 */

import { homedir } from "node:os";
import { isAbsolute, relative } from "node:path";

const PATH_LIMIT = 240;

export interface FilesystemErrorContext {
  error_name: string;
  errno?: string;
  syscall?: string;
  failed_path?: string;
  cwd?: string;
  scope?: "project" | "user" | "unknown";
}

export function redactUserPath(value: string, home = homedir()): string {
  const normalized = value.replaceAll("\\", "/");
  const homeNormalized = home.replaceAll("\\", "/");
  if (homeNormalized && (normalized === homeNormalized || normalized.startsWith(`${homeNormalized}/`))) {
    return `~${normalized.slice(homeNormalized.length)}`;
  }
  return normalized;
}

export function inferFsScope(
  failedPath: string | undefined,
  cwd = process.cwd(),
  agentDir?: string,
): "project" | "user" | "unknown" {
  if (!failedPath) return "unknown";
  const haystack = failedPath.replaceAll("\\", "/");
  const agent = agentDir?.replaceAll("\\", "/");
  if (agent && (haystack === agent || haystack.startsWith(`${agent}/`))) return "user";
  if (haystack.includes("/.psyclaw/agent/") || haystack.includes("/.psyclaw/skills/") || haystack.startsWith("~/")) {
    if (haystack.includes("/.psyclaw/imports/") || haystack.includes(`${cwd.replaceAll("\\", "/")}/.psyclaw/`)) {
      return "project";
    }
    if (haystack.includes("/.psyclaw/agent/") || haystack.includes("/.psyclaw/skills/")) return "user";
  }
  const cwdNormalized = cwd.replaceAll("\\", "/");
  try {
    const rel = relative(cwdNormalized, isAbsolute(failedPath) ? haystack : `${cwdNormalized}/${haystack}`);
    const normalizedRel = rel.replaceAll("\\", "/");
    if (normalizedRel === "" || (!normalizedRel.startsWith("../") && normalizedRel !== "..")) return "project";
  } catch {
    /* fall through */
  }
  return "unknown";
}

function errnoException(error: unknown): NodeJS.ErrnoException | undefined {
  if (!error || typeof error !== "object") return undefined;
  const candidate = error as NodeJS.ErrnoException;
  if (typeof candidate.code === "string" || typeof candidate.errno === "number" || typeof candidate.syscall === "string") {
    return candidate;
  }
  const cause = (error as { cause?: unknown }).cause;
  if (cause && cause !== error) return errnoException(cause);
  return undefined;
}

export function filesystemErrorContext(
  error: unknown,
  options: { cwd?: string; agentDir?: string } = {},
): FilesystemErrorContext {
  const cwd = options.cwd ?? process.cwd();
  const err = error instanceof Error ? error : new Error(String(error));
  const fs = errnoException(error);
  const dest = (fs as NodeJS.ErrnoException & { dest?: string } | undefined)?.dest;
  const failedPath = typeof fs?.path === "string" && fs.path.trim()
    ? fs.path
    : typeof dest === "string" && dest.trim()
      ? dest
      : undefined;
  const context: FilesystemErrorContext = {
    error_name: err.name.slice(0, 80),
    cwd: redactUserPath(cwd).slice(0, PATH_LIMIT),
  };
  if (typeof fs?.code === "string" && fs.code.trim()) context.errno = fs.code.trim().slice(0, 32);
  else if (typeof fs?.errno === "number" && Number.isFinite(fs.errno)) context.errno = String(fs.errno);
  if (typeof fs?.syscall === "string" && fs.syscall.trim()) context.syscall = fs.syscall.trim().slice(0, 40);
  if (failedPath) {
    context.failed_path = redactUserPath(failedPath).slice(0, PATH_LIMIT);
    context.scope = inferFsScope(failedPath, cwd, options.agentDir);
  }
  return context;
}

export function fsWriteErrorMessage(
  error: unknown,
  path: string,
  scope: "project" | "user",
): string {
  const code = errnoException(error)?.code;
  const display = redactUserPath(path);
  const codeSuffix = code ? `（${code}）` : "";
  if (scope === "user") {
    return `无法写入用户级 Skill 状态：${display}${codeSuffix}。请检查系统目录（~/.psyclaw）权限。`;
  }
  if (code === "EPERM" || code === "EACCES") {
    return `无法写入 ${display}${codeSuffix}。当前工作目录不可写；用户级 Skill 请选择「系统目录」安装，项目级状态需要可写的项目目录。`;
  }
  return `无法写入 ${display}${codeSuffix}。`;
}

export function copyErrnoOnto(target: Error, source: unknown, fallbackPath?: string): Error {
  const fs = errnoException(source);
  const dest = target as NodeJS.ErrnoException;
  if (fs?.code) dest.code = fs.code;
  if (typeof fs?.errno === "number") dest.errno = fs.errno;
  if (fs?.syscall) dest.syscall = fs.syscall;
  dest.path = fs?.path ?? fallbackPath;
  return target;
}
