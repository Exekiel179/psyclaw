import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { join } from "node:path";

export type PiRpcCommand =
  | { type: "prompt"; message: string }
  | { type: "get_state" }
  | { type: "get_messages" }
  | { type: "abort" }
  | { type: "set_model"; provider: string; modelId: string };

export interface PiRpcMessage {
  type: string;
  id?: string;
  [key: string]: unknown;
}

export interface PiRpcOptions {
  cwd: string;
  cliPath?: string;
  command?: string;
  provider?: string;
  model?: string;
  agentDir?: string;
  env?: Record<string, string>;
  tools?: readonly string[];
  timeoutMs?: number;
  maxLineBytes?: number;
}

export type PiRpcEventListener = (event: PiRpcMessage) => void;

interface PendingRequest {
  resolve: (value: PiRpcMessage) => void;
  reject: (error: Error) => void;
  timer: ReturnType<typeof setTimeout>;
}

const SAFE_TOOL_NAMES = new Set(["read", "grep", "find", "ls"]);
const SAFE_ENV_NAMES = new Set([
  "PATH", "Path", "SystemRoot", "WINDIR", "ComSpec", "TEMP", "TMP",
  "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "LANG", "LC_ALL",
]);

function assertAbsolute(value: string, label: string): void {
  if (!/^([A-Za-z]:[\\/]|[\\/]{1,2})/.test(value)) throw new Error(`${label} must be an absolute path`);
}

function assertSafeName(value: string, label: string): void {
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value)) throw new Error(`${label} is invalid`);
}

function jsonLine(value: unknown): string {
  return `${JSON.stringify(value)}\n`;
}

/**
 * Minimal, strict JSONL client for Pi RPC. It intentionally builds a narrow
 * child environment and read-only tool allowlist for research workers.
 */
export class PiRpcClient {
  private process: ChildProcessWithoutNullStreams | undefined;
  private buffer = "";
  private sequence = 0;
  private readonly pending = new Map<string, PendingRequest>();
  private readonly listeners = new Set<PiRpcEventListener>();
  private readonly options: Required<Pick<PiRpcOptions, "timeoutMs" | "maxLineBytes">>;
  private stderr = "";

  public constructor(private readonly config: PiRpcOptions) {
    assertAbsolute(config.cwd, "cwd");
    if (config.agentDir !== undefined) assertAbsolute(config.agentDir, "agentDir");
    if (config.provider !== undefined) assertSafeName(config.provider, "provider");
    if (config.model !== undefined && (!/^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$/.test(config.model) || config.model.includes(".."))) {
      throw new Error("model is invalid");
    }
    const tools = config.tools ?? [...SAFE_TOOL_NAMES];
    if (tools.some((tool) => !SAFE_TOOL_NAMES.has(tool))) {
      throw new Error("Pi RPC workers may only use read-only tools");
    }
    this.options = {
      timeoutMs: config.timeoutMs ?? 120_000,
      maxLineBytes: config.maxLineBytes ?? 2 * 1024 * 1024,
    };
  }

  public getStderr(): string {
    return this.stderr;
  }

  public onEvent(listener: PiRpcEventListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  public async start(): Promise<void> {
    if (this.process !== undefined) throw new Error("Pi RPC client already started");
    const args = ["--mode", "rpc"];
    if (this.config.provider !== undefined) args.push("--provider", this.config.provider);
    if (this.config.model !== undefined) args.push("--model", this.config.model);
    args.push(
      "--no-session",
      "--no-extensions",
      "--no-skills",
      "--no-context-files",
      "--tools",
      (this.config.tools ?? [...SAFE_TOOL_NAMES]).join(","),
    );
    const defaultCommand = process.platform === "win32" ? "pi.cmd" : "pi";
    const rawCommand = this.config.cliPath === undefined ? (this.config.command ?? defaultCommand) : process.execPath;
    const rawArgs = this.config.cliPath === undefined ? args : [this.config.cliPath, ...args];
    const command = process.platform === "win32" ? (process.env.ComSpec ?? "cmd.exe") : rawCommand;
    const commandArgs = process.platform === "win32" ? ["/d", "/c", rawCommand, ...rawArgs] : rawArgs;
    const childEnv = this.buildEnvironment();
    const child = spawn(command, commandArgs, {
      cwd: this.config.cwd,
      env: childEnv,
      shell: false,
      stdio: ["pipe", "pipe", "pipe"],
    });
    this.process = child;
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => this.acceptChunk(chunk));
    child.stderr.on("data", (chunk: string) => {
      this.stderr = `${this.stderr}${chunk}`.slice(-16_384);
    });
    child.on("error", (error) => this.failPending(new Error(`Pi RPC process error: ${error.message}`)));
    child.on("exit", (code, signal) => {
      if (this.process !== child) return;
      this.process = undefined;
      this.failPending(new Error(`Pi RPC process exited (${code ?? "?"}/${signal ?? "none"})`));
    });
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("Pi RPC process did not start")), 5_000);
      child.once("spawn", () => {
        clearTimeout(timer);
        resolve();
      });
      child.once("error", (error) => {
        clearTimeout(timer);
        reject(error);
      });
    });
  }

  public async stop(): Promise<void> {
    const child = this.process;
    if (!child) return;
    this.process = undefined;
    this.failPending(new Error("Pi RPC client stopped"));
    child.kill("SIGTERM");
    await new Promise<void>((resolve) => {
      const timer = setTimeout(() => {
        if (!child.killed) child.kill("SIGKILL");
        resolve();
      }, 1_000);
      child.once("exit", () => {
        clearTimeout(timer);
        resolve();
      });
    });
  }

  public async send(command: PiRpcCommand, timeoutMs = this.options.timeoutMs): Promise<PiRpcMessage> {
    const child = this.process;
    if (!child?.stdin.writable) throw new Error("Pi RPC client is not running");
    const id = `psyclaw-${++this.sequence}`;
    return new Promise<PiRpcMessage>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error("Pi RPC request timed out"));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      child.stdin.write(jsonLine({ ...command, id }));
    });
  }

  public async promptAndWait(message: string, timeoutMs = this.options.timeoutMs): Promise<PiRpcMessage[]> {
    const events: PiRpcMessage[] = [];
    let settled = false;
    let resolveWait: (() => void) | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const unsubscribe = this.onEvent((event) => {
      events.push(event);
      if (!settled && (event.type === "agent_end" || event.type === "agent_settled")) {
        settled = true;
        if (timer !== undefined) clearTimeout(timer);
        resolveWait?.();
      }
    });
    try {
      const wait = new Promise<void>((resolve, reject) => {
        resolveWait = resolve;
        timer = setTimeout(() => {
          if (settled) return;
          settled = true;
          reject(new Error("Pi RPC prompt timed out"));
        }, timeoutMs);
      });
      await this.send({ type: "prompt", message }, timeoutMs);
      await wait;
      return events;
    } finally {
      if (timer !== undefined) clearTimeout(timer);
      resolveWait = undefined;
      unsubscribe();
    }
  }

  private buildEnvironment(): NodeJS.ProcessEnv {
    const env: NodeJS.ProcessEnv = {};
    for (const key of SAFE_ENV_NAMES) {
      const value = process.env[key];
      if (value !== undefined) env[key] = value;
    }
    for (const [key, value] of Object.entries(this.config.env ?? {})) {
      if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) throw new Error(`Invalid child environment name: ${key}`);
      env[key] = value;
    }
    if (this.config.agentDir !== undefined) {
      env.PI_CODING_AGENT_DIR = this.config.agentDir;
      env.PI_CODING_AGENT_SESSION_DIR = join(this.config.agentDir, "sessions");
    }
    return env;
  }

  private acceptChunk(chunk: string): void {
    this.buffer += chunk;
    if (Buffer.byteLength(this.buffer, "utf8") > this.options.maxLineBytes * 2) {
      this.failPending(new Error("Pi RPC output buffer exceeded limit"));
      void this.stop();
      return;
    }
    while (true) {
      const newline = this.buffer.indexOf("\n");
      if (newline < 0) return;
      const line = this.buffer.slice(0, newline).replace(/\r$/, "");
      this.buffer = this.buffer.slice(newline + 1);
      if (Buffer.byteLength(line, "utf8") > this.options.maxLineBytes) {
        this.failPending(new Error("Pi RPC record exceeded limit"));
        void this.stop();
        return;
      }
      if (!line.trim()) continue;
      let event: PiRpcMessage;
      try {
        const parsed: unknown = JSON.parse(line);
        if (!parsed || typeof parsed !== "object" || typeof (parsed as { type?: unknown }).type !== "string") {
          throw new Error("invalid event shape");
        }
        event = parsed as PiRpcMessage;
      } catch {
        this.failPending(new Error("Pi RPC emitted invalid JSONL"));
        void this.stop();
        return;
      }
      if (event.type === "response" && typeof event.id === "string") {
        const pending = this.pending.get(event.id);
        if (pending) {
          clearTimeout(pending.timer);
          this.pending.delete(event.id);
          if (event.success === false) pending.reject(new Error("Pi RPC command rejected"));
          else pending.resolve(event);
          continue;
        }
      }
      for (const listener of this.listeners) listener(event);
    }
  }

  private failPending(error: Error): void {
    for (const [id, pending] of this.pending) {
      clearTimeout(pending.timer);
      pending.reject(error);
      this.pending.delete(id);
    }
  }
}
