import { EventEmitter } from "node:events";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";
import type { PreparedAgentLaunch } from "../../src/chat.js";
import { FULL_AGENT_TOOLS, READ_ONLY_AGENT_TOOLS } from "../../src/chat.js";
import { parseHeadlessRunArgs } from "../../src/headless/cli.js";
import { buildHeadlessPiArgs, runHeadlessAgent } from "../../src/headless/run.js";

function mockPrepared(cwd: string, readOnly: boolean): PreparedAgentLaunch {
  return {
    piCli: "/fake/pi-cli.js",
    cwd,
    root: cwd,
    agentDir: join(cwd, "agent"),
    sessionDir: join(cwd, "agent", "sessions"),
    networkPreloadPath: join(cwd, "network-routing.js"),
    baseArgs: [
      "--no-skills",
      "--extension", "/fake/extension.js",
      "--extension", "/fake/panel.js",
      "--skill", "/fake/skills",
      "--tools", readOnly ? READ_ONLY_AGENT_TOOLS : FULL_AGENT_TOOLS,
      "--system-prompt", "PsyClaw identity",
    ],
    spawnEnv: { ...process.env, PI_SKIP_VERSION_CHECK: "1" },
    identityPrompt: "PsyClaw identity",
    nodeArgvPrefix: ["--import", "file:///fake/network-routing.js", "/fake/pi-cli.js"],
  };
}

describe("headless full agent run", () => {
  it("parses prompt flags, file input, and positional words", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-headless-parse-"));
    const file = join(root, "prompt.md");
    await writeFile(file, "summarize notes\n", "utf8");
    await expect(parseHeadlessRunArgs(["--file", file, "--read-only", "--timeout-ms", "120000"])).resolves.toMatchObject({
      prompt: "summarize notes\n",
      readOnly: true,
      timeoutMs: 120_000,
      mode: "json",
    });
    await expect(parseHeadlessRunArgs(["hello", "world", "--mode", "text"])).resolves.toMatchObject({
      prompt: "hello world",
      readOnly: false,
      mode: "text",
    });
    await expect(parseHeadlessRunArgs(["--prompt", "x", "--allow-write"])).resolves.toMatchObject({
      prompt: "x",
      readOnly: false,
    });
  });

  it("builds Pi --print args with full tool stack and prompt after --", () => {
    const prepared = mockPrepared("/proj", false);
    const args = buildHeadlessPiArgs(
      {
        prompt: "evaluate this agent",
        mode: "json",
        provider: "openai",
        model: "gpt-test",
      },
      prepared.baseArgs,
    );
    expect(args).toContain("--print");
    expect(args).toContain("--mode");
    expect(args).toContain("json");
    expect(args).toContain("--no-session");
    expect(args).toContain("--approve");
    expect(args).toContain("--provider");
    expect(args).toContain("openai");
    expect(args).toContain("--tools");
    expect(args[args.indexOf("--tools") + 1]).toBe(FULL_AGENT_TOOLS);
    expect(args[args.length - 2]).toBe("--");
    expect(args[args.length - 1]).toBe("evaluate this agent");
  });

  it("uses read-only tool allowlist when requested", () => {
    const prepared = mockPrepared("/proj", true);
    expect(prepared.baseArgs[prepared.baseArgs.indexOf("--tools") + 1]).toBe(READ_ONLY_AGENT_TOOLS);
  });

  it("spawns full agent --print and returns a structured receipt", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-headless-run-"));
    const outPath = join(root, "receipt.json");
    const captured: { argv?: string[] } = {};

    const spawnProcess = vi.fn((_cmd: string, argv: string[]) => {
      captured.argv = argv;
      const stdout = new EventEmitter() as EventEmitter & { setEncoding: (enc: string) => void };
      const stderr = new EventEmitter() as EventEmitter & { setEncoding: (enc: string) => void };
      stdout.setEncoding = () => undefined;
      stderr.setEncoding = () => undefined;
      const child = new EventEmitter() as EventEmitter & {
        stdout: typeof stdout;
        stderr: typeof stderr;
        kill: (signal?: string) => boolean;
        killed: boolean;
      };
      child.stdout = stdout;
      child.stderr = stderr;
      child.killed = false;
      child.kill = () => {
        child.killed = true;
        return true;
      };
      queueMicrotask(() => {
        const promptIndex = argv.lastIndexOf("--");
        const prompt = promptIndex >= 0 ? argv[promptIndex + 1] : "";
        stdout.emit(
          "data",
          `${JSON.stringify({ type: "assistant", text: `headless-ok:${prompt}` })}\n`,
        );
        child.emit("close", 0);
      });
      return child;
    });
    const result = await runHeadlessAgent({
      cwd: root,
      prompt: "list project files",
      outPath,
      timeoutMs: 10_000,
      prepare: async ({ cwd, readOnly }) => mockPrepared(cwd, readOnly),
      spawnProcess: spawnProcess as never,
    });

    expect(result.ok).toBe(true);
    expect(result.schemaVersion).toBe("psyclaw/headless-agent-run/v1");
    expect(result.stdout).toContain("headless-ok:list project files");
    expect(result.parsedJson).toMatchObject({ type: "assistant", text: "headless-ok:list project files" });
    expect(captured.argv).toContain("--print");
    expect(captured.argv).toContain("--extension");
    expect(captured.argv).toContain("--skill");
    expect(captured.argv?.includes("--no-skills")).toBe(true);

    const onDisk = JSON.parse(await readFile(outPath, "utf8")) as { schemaVersion: string; ok: boolean };
    expect(onDisk.schemaVersion).toBe("psyclaw/headless-agent-run/v1");
    expect(onDisk.ok).toBe(true);
  });

  it("drops streaming message_update lines from json receipts, even when split across chunks", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-headless-run-"));
    const spawnProcess = vi.fn(() => {
      const stdout = new EventEmitter() as EventEmitter & { setEncoding: (enc: string) => void };
      const stderr = new EventEmitter() as EventEmitter & { setEncoding: (enc: string) => void };
      stdout.setEncoding = () => undefined;
      stderr.setEncoding = () => undefined;
      const child = Object.assign(new EventEmitter(), { stdout, stderr, killed: false, kill: () => true });
      queueMicrotask(() => {
        stdout.emit("data", '{"type":"tool_execution_start","toolCallId":"a"}\n{"type":"message_upd');
        stdout.emit("data", 'ate","delta":"x"}\n{"type":"message_end","message":{"role":"assistant"}}\n');
        stdout.emit("data", '{"type":"agent_settled"}');
        child.emit("close", 0);
      });
      return child;
    });
    const result = await runHeadlessAgent({
      cwd: root,
      prompt: "x",
      timeoutMs: 10_000,
      prepare: async ({ cwd, readOnly }) => mockPrepared(cwd, readOnly),
      spawnProcess: spawnProcess as never,
    });

    expect(result.stdout).not.toContain("message_update");
    expect(result.stdout).toContain('"type":"tool_execution_start"');
    expect(result.stdout).toContain('"type":"message_end"');
    expect(result.parsedJson).toEqual({ type: "agent_settled" });
  });
});
