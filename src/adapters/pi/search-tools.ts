import { lstat, readFile, readdir, stat } from "node:fs/promises";
import { basename, relative, resolve } from "node:path";
import type { ToolDefinition } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const DEFAULT_FIND_LIMIT = 1_000;
const DEFAULT_GREP_LIMIT = 100;
const MAX_FILE_BYTES = 8 * 1024 * 1024;
const MAX_OUTPUT_BYTES = 50 * 1024;
const MAX_LINE_CHARS = 500;
const EXCLUDED_DIRECTORY_NAMES = new Set([".git", "node_modules"]);

const findParameters = Type.Object({
  pattern: Type.String({ description: "Glob pattern to match files" }),
  path: Type.Optional(Type.String({ description: "Directory to search (default: current directory)" })),
  limit: Type.Optional(Type.Number({ description: "Maximum number of results (default: 1000)" })),
});

const grepParameters = Type.Object({
  pattern: Type.String({ description: "Search pattern (regex or literal string)" }),
  path: Type.Optional(Type.String({ description: "Directory or file to search (default: current directory)" })),
  glob: Type.Optional(Type.String({ description: "Filter files by glob pattern" })),
  ignoreCase: Type.Optional(Type.Boolean()),
  literal: Type.Optional(Type.Boolean()),
  context: Type.Optional(Type.Number({ description: "Context lines before and after each match" })),
  limit: Type.Optional(Type.Number({ description: "Maximum number of matches (default: 100)" })),
});

function normalizedRelative(root: string, path: string): string {
  return relative(root, path).replaceAll("\\", "/");
}

function assertSearchTarget(projectRoot: string, target: string): void {
  const item = normalizedRelative(resolve(projectRoot), resolve(target));
  const segments = item.split("/").filter(Boolean);
  if (segments.includes(".git") || segments.includes("node_modules")) {
    throw new Error("Git metadata and dependency directories cannot be searched");
  }
  if (item === "data/raw" || item.startsWith("data/raw/") ||
      item === ".psyclaw/data/raw" || item.startsWith(".psyclaw/data/raw/")) {
    throw new Error("Raw-data directories cannot be searched");
  }
}

async function assertNotSymlink(path: string): Promise<void> {
  const info = await lstat(path).catch(() => undefined);
  if (info?.isSymbolicLink()) throw new Error("Symlink search roots are not allowed");
}

function clampLimit(value: number | undefined, fallback: number): number {
  return Number.isFinite(value) ? Math.max(1, Math.min(Math.trunc(value!), 10_000)) : fallback;
}

function checkAbort(signal: AbortSignal | undefined): void {
  if (signal?.aborted) throw new Error("Operation aborted");
}

async function regularFile(path: string): Promise<boolean> {
  const info = await lstat(path).catch(() => undefined);
  return info?.isFile() === true && !info.isSymbolicLink();
}

function globExpression(pattern: string): RegExp {
  const normalized = pattern.replaceAll("\\", "/").replace(/^\.\//, "");
  let source = "";
  for (let index = 0; index < normalized.length; index += 1) {
    const char = normalized[index]!;
    const next = normalized[index + 1];
    if (char === "*" && next === "*") {
      if (normalized[index + 2] === "/") {
        source += "(?:.*/)?";
        index += 2;
      } else {
        source += ".*";
        index += 1;
      }
    } else if (char === "*") {
      source += "[^/]*";
    } else if (char === "?") {
      source += "[^/]";
    } else {
      source += char.replace(/[|\\{}()[\]^$+?.]/g, "\\$&");
    }
  }
  return new RegExp(`^${source}$`);
}

function excludedDirectory(relativePath: string, name: string): boolean {
  if (EXCLUDED_DIRECTORY_NAMES.has(name)) return true;
  const normalized = relativePath.replaceAll("\\", "/");
  return normalized === "data/raw" || normalized === ".psyclaw/data/raw";
}

async function nodeGlob(pattern: string, root: string, limit: number, signal?: AbortSignal): Promise<string[]> {
  const expression = globExpression(pattern);
  const basenameOnly = !pattern.replaceAll("\\", "/").includes("/");
  const found: string[] = [];
  const pending = [root];
  while (pending.length > 0) {
    checkAbort(signal);
    const directory = pending.pop()!;
    const entries = await readdir(directory, { withFileTypes: true }).catch(() => []);
    entries.sort((left, right) => left.name.localeCompare(right.name));
    for (const entry of entries) {
      checkAbort(signal);
      const absolute = resolve(directory, entry.name);
      const item = normalizedRelative(root, absolute);
      if (entry.isSymbolicLink()) continue;
      if (entry.isDirectory()) {
        if (!excludedDirectory(item, entry.name)) pending.push(absolute);
        continue;
      }
      if (!entry.isFile() || !expression.test(basenameOnly ? entry.name : item)) continue;
      if (!(await regularFile(absolute))) continue;
      found.push(item);
      if (found.length >= limit) return found.sort();
    }
  }
  return found.sort();
}

function matchesFileFilter(path: string, pattern: string | undefined): boolean {
  if (!pattern) return true;
  const normalized = pattern.replaceAll("\\", "/");
  try {
    return globExpression(normalized).test(normalized.includes("/") ? path : basename(path));
  } catch {
    throw new Error(`Invalid glob pattern: ${pattern}`);
  }
}

function truncateLine(line: string): string {
  return line.length <= MAX_LINE_CHARS ? line : `${line.slice(0, MAX_LINE_CHARS)}...`;
}

function truncateOutput(lines: string[]): string {
  const selected: string[] = [];
  let bytes = 0;
  for (const line of lines) {
    const lineBytes = Buffer.byteLength(line) + 1;
    if (bytes + lineBytes > MAX_OUTPUT_BYTES) {
      selected.push("[Output truncated at 50KB]");
      break;
    }
    selected.push(line);
    bytes += lineBytes;
  }
  return selected.join("\n");
}

function searchExpression(pattern: string, literal: boolean | undefined, ignoreCase: boolean | undefined): RegExp {
  const source = literal ? pattern.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") : pattern;
  try {
    return new RegExp(source, ignoreCase ? "i" : undefined);
  } catch {
    throw new Error(`Invalid regular expression: ${pattern}`);
  }
}

export function createNodeFindTool(): ToolDefinition<typeof findParameters> {
  return {
    name: "find",
    label: "find",
    description: "Search for files by glob pattern using PsyClaw's cross-platform Node fallback. Excludes Git metadata, dependencies, and raw-data directories.",
    promptSnippet: "Find files by glob pattern without requiring external binaries",
    parameters: findParameters,
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      checkAbort(signal);
      const root = resolve(ctx.cwd, params.path || ".");
      assertSearchTarget(ctx.cwd, root);
      await assertNotSymlink(root);
      const info = await stat(root).catch(() => undefined);
      if (!info?.isDirectory()) throw new Error(`Path not found or not a directory: ${root}`);
      const limit = clampLimit(params.limit, DEFAULT_FIND_LIMIT);
      const files = await nodeGlob(params.pattern, root, limit, signal);
      return {
        content: [{ type: "text", text: files.length > 0 ? files.join("\n") : "No files found matching pattern" }],
        details: files.length >= limit ? { resultLimitReached: limit } : undefined,
      };
    },
  };
}

export function createNodeGrepTool(): ToolDefinition<typeof grepParameters> {
  return {
    name: "grep",
    label: "grep",
    description: "Search text files using PsyClaw's cross-platform Node fallback. Excludes Git metadata, dependencies, raw data, binary files, and files over 8MB.",
    promptSnippet: "Search file contents without requiring ripgrep",
    parameters: grepParameters,
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      checkAbort(signal);
      const target = resolve(ctx.cwd, params.path || ".");
      assertSearchTarget(ctx.cwd, target);
      await assertNotSymlink(target);
      const targetInfo = await stat(target).catch(() => undefined);
      if (!targetInfo) throw new Error(`Path not found: ${target}`);
      const root = targetInfo.isDirectory() ? target : resolve(target, "..");
      const paths = targetInfo.isFile()
        ? [target]
        : (await nodeGlob("**/*", root, 10_000, signal)).map((item) => resolve(root, item));
      const expression = searchExpression(params.pattern, params.literal, params.ignoreCase);
      const matchLimit = clampLimit(params.limit, DEFAULT_GREP_LIMIT);
      const context = Math.max(0, Math.min(Math.trunc(params.context ?? 0), 20));
      const output: string[] = [];
      let matches = 0;

      for (const path of paths) {
        checkAbort(signal);
        const relativePath = normalizedRelative(root, path) || basename(path);
        if (!matchesFileFilter(relativePath, params.glob)) continue;
        const info = await lstat(path).catch(() => undefined);
        if (!info?.isFile() || info.isSymbolicLink() || info.size > MAX_FILE_BYTES) continue;
        const content = await readFile(path).catch(() => undefined);
        if (!content || content.subarray(0, 8_192).includes(0)) continue;
        const lines = content.toString("utf8").replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
        for (let index = 0; index < lines.length; index += 1) {
          if (!expression.test(lines[index]!)) continue;
          matches += 1;
          const start = Math.max(0, index - context);
          const end = Math.min(lines.length - 1, index + context);
          for (let current = start; current <= end; current += 1) {
            const separator = current === index ? ":" : "-";
            output.push(`${relativePath}${separator}${current + 1}${separator} ${truncateLine(lines[current]!)}`);
          }
          if (matches >= matchLimit) break;
        }
        if (matches >= matchLimit) break;
      }

      if (matches === 0) return { content: [{ type: "text", text: "No matches found" }], details: undefined };
      if (matches >= matchLimit) output.push(`[${matchLimit} matches limit reached]`);
      return {
        content: [{ type: "text", text: truncateOutput(output) }],
        details: matches >= matchLimit ? { matchLimitReached: matchLimit } : undefined,
      };
    },
  };
}

/** Cross-platform search tools that never download runtime dependencies. */
export function createPsyClawSearchTools(): ToolDefinition[] {
  return [createNodeFindTool(), createNodeGrepTool()];
}
