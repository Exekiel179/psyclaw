/**
 * Full PsyClaw headless agent runs for evaluation.
 * Same extensions / core skills / tools / identity as interactive chat,
 * launched with Pi `--print` (no TUI).
 */
import { spawn, type ChildProcess } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { prepareAgentLaunch, type PreparedAgentLaunch } from "../chat.js";

export type HeadlessOutputMode = "text" | "json" | "rpc";

export interface HeadlessAgentRunOptions {
  cwd: string;
  /** User prompt for a single print turn. */
  prompt: string;
  provider?: string;
  model?: string;
  thinking?: string;
  /** Pi --mode. Default json for machine-readable eval. */
  mode?: HeadlessOutputMode;
  /** Persist a session file. Default false (--no-session). */
  persistSession?: boolean;
  /** Restrict to read-oriented tools. Default false (full agent tools). */
  readOnly?: boolean;
  /** Trust project-local files for this run. Default true. */
  approveProject?: boolean;
  /** Write the structured receipt JSON here. */
  outPath?: string;
  /** Also tee child stdout/stderr to the parent (default: capture only). */
  inheritStdio?: boolean;
  timeoutMs?: number;
  /** Extra Pi CLI args after PsyClaw base args. */
  extraArgs?: string[];
  /** Test hook: replace prepareAgentLaunch. */
  prepare?: (options: { cwd: string; readOnly: boolean }) => Promise<PreparedAgentLaunch>;
  spawnProcess?: typeof spawn;
}

export interface HeadlessAgentRunResult {
  schemaVersion: "psyclaw/headless-agent-run/v1";
  ok: boolean;
  cwd: string;
  mode: HeadlessOutputMode;
  readOnly: boolean;
  exitCode: number;
  durationMs: number;
  stdout: string;
  stderr: string;
  promptChars: number;
  /** First JSON object found on stdout when mode=json (best-effort). */
  parsedJson?: unknown;
  error?: string;
}

export function buildHeadlessPiArgs(
  options: Pick<
    HeadlessAgentRunOptions,
    "mode" | "persistSession" | "approveProject" | "provider" | "model" | "thinking" | "extraArgs" | "prompt"
  >,
  baseArgs: string[],
): string[] {
  const mode = options.mode ?? "json";
  const args = [
    ...baseArgs,
    "--print",
    "--mode", mode,
    ...(options.persistSession === true ? [] : ["--no-session"]),
    ...(options.approveProject === false ? ["--no-approve"] : ["--approve"]),
  ];
  if (options.provider) args.push("--provider", options.provider);
  if (options.model) args.push("--model", options.model);
  if (options.thinking) args.push("--thinking", options.thinking);
  if (options.extraArgs?.length) args.push(...options.extraArgs);
  // Prompt after `--` so it cannot be parsed as a Pi flag.
  args.push("--", options.prompt);
  return args;
}

function tryParseJsonStdout(stdout: string): unknown | undefined {
  const trimmed = stdout.trim();
  if (!trimmed) return undefined;
  try {
    return JSON.parse(trimmed);
  } catch {
    // Fall through: Pi may emit multiple JSON lines or text + JSON.
  }
  const lines = trimmed.split("\n").map((line) => line.trim()).filter(Boolean);
  for (let i = lines.length - 1; i >= 0; i--) {
    try {
      return JSON.parse(lines[i]!);
    } catch {
      /* keep scanning */
    }
  }
  return undefined;
}

/**
 * Run the full PsyClaw agent non-interactively (Pi --print).
 * Suitable for agent evaluation harnesses that need skills, tools, and gates.
 */
export async function runHeadlessAgent(options: HeadlessAgentRunOptions): Promise<HeadlessAgentRunResult> {
  const cwd = resolve(options.cwd);
  const prompt = options.prompt.trim();
  if (!prompt) throw new Error("headless agent run requires a non-empty prompt");
  if (prompt.length > 500_000) throw new Error("headless prompt exceeds 500000 characters");

  const mode = options.mode ?? "json";
  const readOnly = options.readOnly === true;
  const timeoutMs = options.timeoutMs ?? 1_800_000;
  const started = Date.now();

  const prepared = await (options.prepare ?? ((opts) => prepareAgentLaunch({
    cwd: opts.cwd,
    readOnly: opts.readOnly,
    quietPrep: true,
  })))({ cwd, readOnly });

  const args = buildHeadlessPiArgs(options, prepared.baseArgs);
  const inherit = options.inheritStdio === true;

  let stdout = "";
  let stderr = "";
  let exitCode = 1;

  try {
    exitCode = await new Promise<number>((resolvePromise, reject) => {
      const child: ChildProcess = (options.spawnProcess ?? spawn)(
        process.execPath,
        [...prepared.nodeArgvPrefix, ...args],
        {
          cwd: prepared.cwd,
          env: prepared.spawnEnv,
          shell: false,
          stdio: inherit ? ["ignore", "inherit", "inherit"] : ["ignore", "pipe", "pipe"],
        },
      );
      const timer = setTimeout(() => {
        child.kill("SIGTERM");
        setTimeout(() => {
          if (!child.killed) child.kill("SIGKILL");
        }, 5_000).unref();
      }, timeoutMs);
      timer.unref?.();

      if (!inherit) {
        child.stdout?.setEncoding("utf8");
        child.stderr?.setEncoding("utf8");
        child.stdout?.on("data", (chunk: string) => {
          stdout += chunk;
          if (stdout.length > 32 * 1024 * 1024) stdout = `${stdout.slice(-16 * 1024 * 1024)}\n…[truncated]…\n`;
        });
        child.stderr?.on("data", (chunk: string) => {
          stderr += chunk;
          if (stderr.length > 8 * 1024 * 1024) stderr = `${stderr.slice(-4 * 1024 * 1024)}\n…[truncated]…\n`;
        });
      }
      child.on("error", (error) => {
        clearTimeout(timer);
        reject(error);
      });
      child.on("close", (code) => {
        clearTimeout(timer);
        resolvePromise(code ?? 1);
      });
    });
  } catch (error) {
    const result: HeadlessAgentRunResult = {
      schemaVersion: "psyclaw/headless-agent-run/v1",
      ok: false,
      cwd,
      mode,
      readOnly,
      exitCode: 1,
      durationMs: Date.now() - started,
      stdout,
      stderr,
      promptChars: prompt.length,
      error: error instanceof Error ? error.message : String(error),
    };
    if (options.outPath) await writeReceipt(options.outPath, result);
    return result;
  }

  const parsedJson = mode === "json" ? tryParseJsonStdout(stdout) : undefined;
  const result: HeadlessAgentRunResult = {
    schemaVersion: "psyclaw/headless-agent-run/v1",
    ok: exitCode === 0,
    cwd,
    mode,
    readOnly,
    exitCode,
    durationMs: Date.now() - started,
    stdout,
    stderr,
    promptChars: prompt.length,
    ...(parsedJson === undefined ? {} : { parsedJson }),
    ...(exitCode === 0 ? {} : { error: `agent exited with code ${exitCode}` }),
  };
  if (options.outPath) await writeReceipt(options.outPath, result);
  return result;
}

async function writeReceipt(path: string, result: HeadlessAgentRunResult): Promise<void> {
  const target = resolve(path);
  await mkdir(dirname(target), { recursive: true });
  await writeFile(target, `${JSON.stringify(result, null, 2)}\n`, "utf8");
}

/** @deprecated Use runHeadlessAgent. Kept for older imports. */
export async function runHeadlessPrompt(options: {
  cwd: string;
  prompt: string;
  provider?: string;
  model?: string;
  allowWrite?: boolean;
  timeoutMs?: number;
  prepare?: HeadlessAgentRunOptions["prepare"];
  spawnProcess?: typeof spawn;
}): Promise<HeadlessAgentRunResult> {
  return runHeadlessAgent({
    cwd: options.cwd,
    prompt: options.prompt,
    readOnly: options.allowWrite !== true,
    ...(options.provider === undefined ? {} : { provider: options.provider }),
    ...(options.model === undefined ? {} : { model: options.model }),
    ...(options.timeoutMs === undefined ? {} : { timeoutMs: options.timeoutMs }),
    ...(options.prepare === undefined ? {} : { prepare: options.prepare }),
    ...(options.spawnProcess === undefined ? {} : { spawnProcess: options.spawnProcess }),
  });
}
