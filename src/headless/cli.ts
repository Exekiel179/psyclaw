/**
 * CLI entry for full headless PsyClaw agent runs (evaluation / batch).
 *
 * Usage:
 *   psyclaw run --prompt "…" [--cwd DIR] [--mode json|text|rpc]
 *   psyclaw run --prompt-file PATH …
 *   psyclaw run "…"
 *   echo "…" | psyclaw run --stdin
 */
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import {
  runHeadlessAgent,
  type HeadlessAgentRunResult,
  type HeadlessOutputMode,
} from "./run.js";

export function headlessRunUsage(): string {
  return [
    "Usage:",
    "  psyclaw run --prompt <text> [options]",
    "  psyclaw run --prompt-file <path> [options]",
    "  psyclaw run --stdin [options]",
    "  psyclaw run <prompt words…> [options]",
    "",
    "Full PsyClaw agent (extensions + core skills + tools), no TUI.",
    "Same stack as `psyclaw chat`, driven by Pi --print for agent evaluation.",
    "",
    "Options:",
    "  --cwd <dir>           Working directory (default: .)",
    "  --prompt <text>       User prompt (single turn)",
    "  --prompt-file <path>  Read prompt from file",
    "  --file <path>         Alias of --prompt-file",
    "  --stdin               Read prompt from stdin",
    "  --mode <m>            Pi output mode: json (default), text, rpc",
    "  --provider <id>       Model provider",
    "  --model <id>          Model id",
    "  --thinking <level>    Thinking level",
    "  --read-only           Restrict to read-oriented tools",
    "  --allow-write         Explicit full tools (default; opposite of --read-only)",
    "  --persist-session     Keep a session file (default: --no-session)",
    "  --no-approve          Do not auto-approve project trust",
    "  --out <path>          Also write structured receipt JSON to path",
    "  --inherit-stdio       Stream child stdout/stderr live (receipt still returned)",
    "  --timeout-ms <n>      Kill after N ms (default: 1800000)",
    "  -h, --help            Show this help",
    "",
  ].join("\n");
}

export interface ParsedHeadlessRunArgs {
  cwd: string;
  prompt: string;
  mode: HeadlessOutputMode;
  provider?: string;
  model?: string;
  thinking?: string;
  readOnly: boolean;
  persistSession: boolean;
  approveProject: boolean;
  outPath?: string;
  inheritStdio: boolean;
  timeoutMs?: number;
}

function takeValue(argv: string[], i: number, flag: string): { value: string; next: number } {
  const next = argv[i + 1];
  if (!next || next.startsWith("-")) {
    throw new Error(`${flag} requires a value`);
  }
  return { value: next, next: i + 1 };
}

async function readStdin(): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of process.stdin) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk)));
  }
  return Buffer.concat(chunks).toString("utf8");
}

/**
 * Parse `psyclaw run` argv (everything after the `run` command).
 */
export async function parseHeadlessRunArgs(argv: string[]): Promise<ParsedHeadlessRunArgs> {
  let cwd = process.cwd();
  let prompt: string | undefined;
  let promptFile: string | undefined;
  let fromStdin = false;
  let mode: HeadlessOutputMode = "json";
  let provider: string | undefined;
  let model: string | undefined;
  let thinking: string | undefined;
  let readOnly = false;
  let persistSession = false;
  let approveProject = true;
  let outPath: string | undefined;
  let inheritStdio = false;
  let timeoutMs: number | undefined;
  const positional: string[] = [];

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i]!;
    if (arg === "-h" || arg === "--help") {
      throw new Error("HELP");
    }
    if (arg === "--cwd") {
      const t = takeValue(argv, i, arg);
      cwd = resolve(t.value);
      i = t.next;
      continue;
    }
    if (arg === "--prompt") {
      const t = takeValue(argv, i, arg);
      prompt = t.value;
      i = t.next;
      continue;
    }
    if (arg === "--prompt-file" || arg === "--file") {
      const t = takeValue(argv, i, arg);
      promptFile = resolve(t.value);
      i = t.next;
      continue;
    }
    if (arg === "--stdin") {
      fromStdin = true;
      continue;
    }
    if (arg === "--mode") {
      const t = takeValue(argv, i, arg);
      if (t.value !== "json" && t.value !== "text" && t.value !== "rpc") {
        throw new Error(`--mode must be json|text|rpc (got ${t.value})`);
      }
      mode = t.value;
      i = t.next;
      continue;
    }
    if (arg === "--provider") {
      const t = takeValue(argv, i, arg);
      provider = t.value;
      i = t.next;
      continue;
    }
    if (arg === "--model") {
      const t = takeValue(argv, i, arg);
      model = t.value;
      i = t.next;
      continue;
    }
    if (arg === "--thinking") {
      const t = takeValue(argv, i, arg);
      thinking = t.value;
      i = t.next;
      continue;
    }
    if (arg === "--read-only") {
      readOnly = true;
      continue;
    }
    if (arg === "--allow-write") {
      readOnly = false;
      continue;
    }
    if (arg === "--persist-session") {
      persistSession = true;
      continue;
    }
    if (arg === "--no-approve") {
      approveProject = false;
      continue;
    }
    if (arg === "--out") {
      const t = takeValue(argv, i, arg);
      outPath = resolve(t.value);
      i = t.next;
      continue;
    }
    if (arg === "--inherit-stdio") {
      inheritStdio = true;
      continue;
    }
    if (arg === "--timeout-ms") {
      const t = takeValue(argv, i, arg);
      const n = Number(t.value);
      if (!Number.isFinite(n) || n <= 0) throw new Error("--timeout-ms must be a positive number");
      timeoutMs = Math.floor(n);
      i = t.next;
      continue;
    }
    if (arg.startsWith("-")) {
      throw new Error(`Unknown argument: ${arg}`);
    }
    positional.push(arg);
  }

  if (promptFile) {
    prompt = await readFile(promptFile, "utf8");
  } else if (fromStdin) {
    prompt = await readStdin();
  } else if (prompt === undefined && positional.length > 0) {
    prompt = positional.join(" ");
  }

  if (prompt === undefined || !prompt.trim()) {
    throw new Error("Specify a prompt via --prompt, --prompt-file/--file, --stdin, or positional words");
  }

  const explicit = [
    argv.includes("--prompt"),
    argv.includes("--prompt-file") || argv.includes("--file"),
    fromStdin,
  ].filter(Boolean).length;
  if (explicit > 1) {
    throw new Error("Specify at most one of --prompt, --prompt-file/--file, or --stdin");
  }

  return {
    cwd,
    prompt,
    mode,
    readOnly,
    persistSession,
    approveProject,
    inheritStdio,
    ...(provider === undefined ? {} : { provider }),
    ...(model === undefined ? {} : { model }),
    ...(thinking === undefined ? {} : { thinking }),
    ...(outPath === undefined ? {} : { outPath }),
    ...(timeoutMs === undefined ? {} : { timeoutMs }),
  };
}

/**
 * Dispatch `psyclaw run` for the main CLI (returns structured receipt).
 * `packageRoot` is accepted for call-site compatibility; launch prep resolves the package root itself.
 */
export async function dispatchHeadlessRun(
  argv: string[],
  _packageRoot?: string,
): Promise<HeadlessAgentRunResult> {
  const parsed = await parseHeadlessRunArgs(argv);
  return runHeadlessAgent({
    cwd: parsed.cwd,
    prompt: parsed.prompt,
    mode: parsed.mode,
    readOnly: parsed.readOnly,
    persistSession: parsed.persistSession,
    approveProject: parsed.approveProject,
    inheritStdio: parsed.inheritStdio,
    ...(parsed.provider === undefined ? {} : { provider: parsed.provider }),
    ...(parsed.model === undefined ? {} : { model: parsed.model }),
    ...(parsed.thinking === undefined ? {} : { thinking: parsed.thinking }),
    ...(parsed.outPath === undefined ? {} : { outPath: parsed.outPath }),
    ...(parsed.timeoutMs === undefined ? {} : { timeoutMs: parsed.timeoutMs }),
  });
}

/** Standalone exit-code CLI (prints agent stdout; receipt via --out). */
export async function runHeadlessCli(argv: string[]): Promise<number> {
  if (argv.includes("-h") || argv.includes("--help")) {
    process.stdout.write(`${headlessRunUsage()}\n`);
    return 0;
  }
  const inheritStdio = argv.includes("--inherit-stdio");
  try {
    const result = await dispatchHeadlessRun(argv);
    if (!inheritStdio) {
      if (result.stdout) {
        process.stdout.write(result.stdout.endsWith("\n") ? result.stdout : `${result.stdout}\n`);
      }
      if (result.stderr) {
        process.stderr.write(result.stderr.endsWith("\n") ? result.stderr : `${result.stderr}\n`);
      }
    }
    if (!result.ok && result.error) {
      process.stderr.write(`psyclaw run: ${result.error}\n`);
    }
    return result.ok ? 0 : result.exitCode || 1;
  } catch (error) {
    if (error instanceof Error && error.message === "HELP") {
      process.stdout.write(`${headlessRunUsage()}\n`);
      return 0;
    }
    process.stderr.write(`psyclaw run: ${error instanceof Error ? error.message : String(error)}\n`);
    return 1;
  }
}
