/**
 * Saves one full tool output so a later turn can recall a line range.
 * The stable observation mask keeps only the head and tail in context.
 */
import { lstat, mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, relative, resolve } from "node:path";
import { TOOL_OUTPUT_LOG_DIR } from "../safety/data-access.js";

export const OUTPUT_LOG_MARK = "[psyclaw:output-log";
export const RECALL_CHAR_CAP = 1_600;

export function outputLogFooter(relativePath: string, text: string): string {
  const lines = text.split(/\r?\n/).length;
  return `${OUTPUT_LOG_MARK} ${relativePath} chars=${text.length} lines=${lines}]`;
}

export async function persistToolOutput(root: string, toolCallId: string, text: string, keepChars: number): Promise<string | undefined> {
  if (!toolCallId || !text || text.includes(OUTPUT_LOG_MARK) || text.length <= keepChars) return undefined;
  const id = toolCallId.replace(/[^A-Za-z0-9._-]/g, "").slice(0, 80);
  if (!id) return undefined;
  const relativePath = `${TOOL_OUTPUT_LOG_DIR}/${id}.txt`;
  const rootAbs = resolve(root);
  const absolute = resolve(rootAbs, relativePath);
  const rel = relative(rootAbs, absolute).replaceAll("\\", "/");
  if (rel !== relativePath) return undefined;
  await mkdir(dirname(absolute), { recursive: true });
  try {
    await writeFile(absolute, text, { encoding: "utf8", flag: "wx" });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
  }
  return relativePath;
}

export async function recallToolOutput(root: string, target: string, startLine = 1, lineCount = 40): Promise<string> {
  const normalized = target.trim().replaceAll("\\", "/").replace(/^\.\//, "");
  if (!normalized.startsWith(`${TOOL_OUTPUT_LOG_DIR}/`) || normalized.split("/").includes("..")) {
    throw new Error("psyclaw_recall_output only reads logs under .psyclaw/cache/tool-output");
  }
  const rootAbs = resolve(root);
  const absolute = resolve(rootAbs, normalized);
  const rel = relative(rootAbs, absolute).replaceAll("\\", "/");
  if (!rel.startsWith(`${TOOL_OUTPUT_LOG_DIR}/`)) {
    throw new Error("psyclaw_recall_output only reads logs under .psyclaw/cache/tool-output");
  }
  const stat = await lstat(absolute);
  if (!stat.isFile() || stat.isSymbolicLink()) throw new Error("tool output log is not a regular file");
  const lines = (await readFile(absolute, "utf8")).split(/\r?\n/);
  const start = Number.isFinite(startLine) ? Math.max(1, Math.floor(startLine)) : 1;
  const count = Number.isFinite(lineCount) ? Math.min(80, Math.max(1, Math.floor(lineCount))) : 40;
  const chosen = lines.slice(start - 1, start - 1 + count);
  const end = start + Math.max(chosen.length, 1) - 1;
  let text = [`Recalled ${rel} lines ${start}-${end} of ${lines.length}.`, ...chosen.map((line, index) => `${start + index}|${line}`)].join("\n");
  if (text.length > RECALL_CHAR_CAP) text = `${text.slice(0, RECALL_CHAR_CAP)}\n[psyclaw:recall truncated]`;
  return text;
}
