import { afterEach, describe, expect, it } from "vitest";
import { mkdtemp, readFile, writeFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import extension from "../../src/adapters/pi/extension.js";
import { bootstrapProject } from "../../src/project/bootstrap.js";
import { setObservabilityHandleForTests, shutdownObservability } from "../../src/observability/index.js";

describe("Pi extension contract", () => {
  it("registers only the small legacy research command surface without registerTool", async () => {
    const commands = new Map<string, { handler: (args: string, ctx: any) => Promise<void> }>();
    const api = {
      registerCommand(name: string, options: { handler: (args: string, ctx: any) => Promise<void> }) {
        commands.set(name, options);
      },
    } as any;
    extension(api);
    // With a legacy Pi API (no registerTool) the extension keeps a minimal
    // research surface: /verify and /model stay reachable for the CLI/simple
    // hosts, while UI-gated research commands (agents/grill/...) are not
    // registered at all.
    expect([...commands.keys()]).toEqual(["exit", "init", "data-access", "crosscheck", "verify", "help", "plan", "handoff", "model"]);
  });

  it("registers the full research command surface on a modern Pi API", () => {
    const commands: string[] = [];
    const api = {
      registerCommand(name: string) { commands.push(name); },
      registerTool() {},
    } as any;
    extension(api);
    expect(commands).toEqual([
      "exit", "init", "data-access", "crosscheck", "verify", "help", "plan", "handoff", "grill", "brainstorm", "review", "loop",
      "create-skill", "create-hook", "create-rule", "create-subagent",
      "skill", "skill-preference", "biosignal", "ars", "plugin", "mcp", "provider", "pet", "telemetry", "agents",
    ]);
    expect(commands).not.toContain("run");
    expect(commands).not.toContain("brief");
  });

  it("blocks a direct read of script-only data and redacts grep lines", async () => {
    let command: ((args: string, ctx: any) => Promise<void>) | undefined;
    const handlers = new Map<string, (event: any, ctx: any) => Promise<any>>();
    const api = {
      registerCommand(name: string, options: { handler: (args: string, ctx: any) => Promise<void> }) {
        if (name === "data-access") command = options.handler;
      },
      registerTool() {},
      on(name: string, handler: (event: any, ctx: any) => Promise<any>) {
        handlers.set(name, handler);
      },
    } as any;
    extension(api);
    const root = await mkdtemp(join(tmpdir(), "psyclaw-data-access-hook-"));
    await mkdir(join(root, "data/secret"), { recursive: true });
    await writeFile(join(root, "data/secret/scores.csv"), "id,score\n1,99\n", "utf8");
    const notes: string[] = [];
    const ctx = { cwd: root, hasUI: true, ui: { notify(message: string) { notes.push(message); } } };
    const blocked = await handlers.get("tool_call")!({ toolName: "read", toolCallId: "1", input: { path: "data/secret/scores.csv" } }, ctx);
    expect(blocked).toMatchObject({ block: true });
    expect(blocked.reason).toContain("script-only");
    expect(blocked.terminate).toBeUndefined();
    expect(notes.join("\n")).not.toContain("99");

    await command!("set data/scores.csv script-only", ctx);
    const script = await handlers.get("tool_call")!(
      { toolName: "bash", toolCallId: "2", input: { command: "Rscript analysis/scripts/run_all.R data/scores.csv" } },
      ctx,
    );
    expect(script).toBeUndefined();
    const redacted = await handlers.get("tool_result")!(
      {
        toolName: "grep",
        content: [{ type: "text", text: "data/clean/ready.csv:1: ok\ndata/secret/scores.csv:2: 1,99" }],
        isError: false,
      },
      ctx,
    );
    expect(redacted.content[0].text).toContain("data/clean/ready.csv:1: ok");
    expect(redacted.content[0].text).not.toContain("99");

    const long = `HEAD\n${"m".repeat(3_000)}\nBETA 0.42\n${"z".repeat(3_000)}\nTAIL`;
    const saved = await handlers.get("tool_result")!({
      toolName: "bash",
      toolCallId: "call-middle",
      content: [{ type: "text", text: long }],
      isError: false,
    }, ctx);
    expect(saved.content[0].text).toContain("BETA 0.42");
    expect(saved.content[0].text).toContain(".psyclaw/cache/tool-output/call-middle.txt");
    expect(await readFile(join(root, ".psyclaw/cache/tool-output/call-middle.txt"), "utf8")).toContain("BETA 0.42");
  });

  it("reads the persisted analysis mode on input when no mode editor exists (headless)", async () => {
    const handlers = new Map<string, (event: any, ctx: any) => Promise<any>>();
    const api = {
      registerCommand() {},
      registerTool() {},
      on(name: string, handler: (event: any, ctx: any) => Promise<any>) {
        handlers.set(name, handler);
      },
    } as any;
    extension(api);
    const root = await mkdtemp(join(tmpdir(), "psyclaw-headless-mode-"));
    await bootstrapProject({ root, goal: "headless mode", paradigm: "survey-observational" });
    const ctxWith = (branch: unknown[]) => ({ cwd: root, hasUI: false, ui: { notify() {} }, sessionManager: { getBranch: () => branch } });
    const event = { text: "帮我分析数据 data/wave.csv", source: "interactive" };

    const analysis = await handlers.get("input")!(event, ctxWith([
      { type: "custom", customType: "psyclaw-session-mode", data: { mode: "analysis" } },
    ]));
    expect(analysis.text).toContain("/skill:analysis-plan");
    expect(analysis.text).not.toContain("PsyClaw mode notice");

    const chat = await handlers.get("input")!(event, ctxWith([]));
    expect(chat.text).toContain("PsyClaw mode notice");
  });

  it("adds the unattended-run rules to the analysis system prompt only without a UI", async () => {
    const handlers = new Map<string, (event: any, ctx: any) => any>();
    const api = {
      registerCommand() {},
      registerTool() {},
      on(name: string, handler: (event: any, ctx: any) => any) {
        handlers.set(name, handler);
      },
    } as any;
    extension(api);
    const analysisBranch = [{ type: "custom", customType: "psyclaw-session-mode", data: { mode: "analysis" } }];
    const ctxWith = (hasUI: boolean, branch: unknown[]) => ({ cwd: tmpdir(), hasUI, ui: { notify() {} }, sessionManager: { getBranch: () => branch } });
    const event = { systemPrompt: "base" };

    const headless = await handlers.get("before_agent_start")!(event, ctxWith(false, analysisBranch));
    expect(headless.systemPrompt).toContain("## PsyClaw mode: analysis");
    expect(headless.systemPrompt).toContain("## Unattended run");

    const interactive = await handlers.get("before_agent_start")!(event, ctxWith(true, analysisBranch));
    expect(interactive.systemPrompt).toContain("## PsyClaw mode: analysis");
    expect(interactive.systemPrompt).not.toContain("## Unattended run");

    const chatBranch = [{ type: "custom", customType: "psyclaw-session-mode", data: { mode: "chat" } }];
    const chat = await handlers.get("before_agent_start")!(event, ctxWith(false, chatBranch));
    expect(chat.systemPrompt).not.toContain("## Unattended run");
  });

  it("supports /exit as a graceful alias for /quit", async () => {
    let exitHandler: ((args: string, ctx: any) => Promise<void>) | undefined;
    const api = {
      registerCommand(name: string, options: { handler: (args: string, ctx: any) => Promise<void> }) {
        if (name === "exit") exitHandler = options.handler;
      },
    } as any;
    extension(api);
    let shutdownCalls = 0;
    await exitHandler?.("", { shutdown: () => { shutdownCalls += 1; } });
    expect(shutdownCalls).toBe(1);
  });

  it("lets the init command bootstrap through the Pi context cwd", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-extension-"));
    let initHandler: ((args: string, ctx: any) => Promise<void>) | undefined;
    const api = {
      registerCommand(name: string, options: { handler: (args: string, ctx: any) => Promise<void> }) {
        if (name === "init") initHandler = options.handler;
      },
    } as any;
    extension(api);
    const notifications: string[] = [];
    await initHandler?.("A bounded goal", {
      cwd: root,
      ui: { notify: (message: string) => notifications.push(message) },
    });
    const project = JSON.parse(await readFile(join(root, ".psyclaw", "project.json"), "utf8"));
    expect(project.paradigm).toBe("survey-observational");
    expect(project.goal).toBe("A bounded goal");
    expect(notifications[0]).toContain("工作仓库已初始化");
  });

  it("allows bare init without a goal string", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-extension-invalid-"));
    let initHandler: ((args: string, ctx: any) => Promise<void>) | undefined;
    const api = {
      registerCommand(name: string, options: { handler: (args: string, ctx: any) => Promise<void> }) {
        if (name === "init") initHandler = options.handler;
      },
    } as any;
    extension(api);
    const notifications: string[] = [];
    await initHandler?.("", {
      cwd: root,
      ui: { notify: (message: string) => notifications.push(message) },
    });
    expect(notifications[0]).toContain("工作仓库已初始化");
    const project = JSON.parse(await readFile(join(root, ".psyclaw", "project.json"), "utf8"));
    expect(project.goal).toBe("未命名研究项目");
  });

  it("lists models without exposing credentials", async () => {
    let modelHandler: ((args: string, ctx: any) => Promise<void>) | undefined;
    const api = {
      registerCommand(name: string, options: { handler: (args: string, ctx: any) => Promise<void> }) {
        if (name === "model") modelHandler = options.handler;
      },
    } as any;
    extension(api);
    const notifications: string[] = [];
    await modelHandler?.("", {
      model: undefined,
      modelRegistry: { getAll: () => [] },
      ui: { notify: (message: string) => notifications.push(message) },
    });
    expect(notifications[0]).toContain("current=none");
    expect(notifications[0]).not.toMatch(/sk-[A-Za-z0-9]/);
  });

  it("registers every PsyClaw slash command with a short description", () => {
    const commands: Array<{ name: string; description?: string }> = [];
    const api = {
      registerCommand(name: string, options: { description?: string }) { commands.push({ name, description: options.description }); },
      registerTool() {},
    } as any;
    extension(api);
    expect(commands).toEqual(expect.arrayContaining([
      expect.objectContaining({ name: "grill" }),
      expect.objectContaining({ name: "loop" }),
      expect.objectContaining({ name: "provider" }),
      expect.objectContaining({ name: "pet" }),
      expect.objectContaining({ name: "telemetry" }),
      expect.objectContaining({ name: "skill" }),
      expect.objectContaining({ name: "plugin" }),
    ]));
    expect(commands.some((command) => command.name === "skills")).toBe(false);
    expect(commands.every((command) => Boolean(command.description?.trim()))).toBe(true);
  });

  it("starts explicit research brainstorming with the requested subject", async () => {
    let brainstormHandler: ((args: string, ctx: any) => Promise<void>) | undefined;
    const messages: Array<{ text: string; options?: { deliverAs?: string } }> = [];
    const api = {
      registerCommand(name: string, options: { handler: (args: string, ctx: any) => Promise<void> }) {
        if (name === "brainstorm") brainstormHandler = options.handler;
      },
      registerTool() {},
      sendUserMessage(text: string, options?: { deliverAs?: string }) { messages.push({ text, options }); },
    } as any;
    extension(api);

    const notifications: string[] = [];
    await brainstormHandler?.("生成式 AI 与大学生批判性思维", {
      isIdle: () => true,
      ui: { notify: (message: string) => notifications.push(message) },
    });

    expect(messages).toHaveLength(1);
    expect(messages[0]?.text).toContain("这是 /brainstorm");
    expect(messages[0]?.text).not.toContain("不是 /grill");
    expect(messages[0]?.text).toContain("不要加载 academic-grill");
    expect(messages[0]?.text).not.toContain("先调用 psyclaw_skill");
    expect(messages[0]?.text).toContain("头脑风暴主题：生成式 AI 与大学生批判性思维");
    expect(messages[0]?.options).toEqual({});
    expect(notifications[0]).toContain("已启动研究方向头脑风暴");
    expect(notifications[0]).not.toContain("不经过 /grill");
  });

  it("starts the academic grill with the requested subject", async () => {
    let grillHandler: ((args: string, ctx: any) => Promise<void>) | undefined;
    const messages: Array<{ text: string; options?: { deliverAs?: string } }> = [];
    const api = {
      registerCommand(name: string, options: { handler: (args: string, ctx: any) => Promise<void> }) {
        if (name === "grill") grillHandler = options.handler;
      },
      registerTool() {},
      sendUserMessage(text: string, options?: { deliverAs?: string }) { messages.push({ text, options }); },
    } as any;
    extension(api);

    const notifications: string[] = [];
    await grillHandler?.("生成式 AI 使用与大学生批判性思维", {
      isIdle: () => false,
      ui: { notify: (message: string) => notifications.push(message) },
    });

    expect(messages).toHaveLength(1);
    expect(messages[0]?.text).toContain("psyclaw_skill");
    expect(messages[0]?.text).toContain("academic-grill");
    expect(messages[0]?.text).toContain("生成式 AI 使用与大学生批判性思维");
    expect(messages[0]?.options).toEqual({ deliverAs: "followUp" });
    expect(notifications[0]).toContain("已启动学术追问");
  });

  it("exposes /crosscheck as process AI review and /verify as substance AI review", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-extension-verify-"));
    await bootstrapProject({ root, goal: "verify split", paradigm: "survey-observational" });
    let crosscheckHandler: ((args: string, ctx: any) => Promise<void>) | undefined;
    let verifyHandler: ((args: string, ctx: any) => Promise<void>) | undefined;
    const messages: string[] = [];
    const api = {
      registerCommand(name: string, options: { handler: (args: string, ctx: any) => Promise<void> }) {
        if (name === "crosscheck") crosscheckHandler = options.handler;
        if (name === "verify") verifyHandler = options.handler;
      },
      registerTool() {},
      sendUserMessage(text: string) { messages.push(text); },
    } as any;
    extension(api);

    const processNotes: string[] = [];
    await crosscheckHandler?.("tables and DOIs", {
      cwd: root,
      isIdle: () => true,
      ui: { notify: (message: string) => processNotes.push(message) },
    });
    expect(messages[0]).toContain("过程性交叉核对");
    expect(messages[0]).toContain("引文真实性");
    expect(processNotes[0]).toContain("过程性 /crosscheck");

    const substanceNotes: string[] = [];
    await verifyHandler?.("primary effect claims", {
      cwd: root,
      isIdle: () => true,
      ui: { notify: (message: string) => substanceNotes.push(message) },
    });
    expect(messages[1]).toContain("整体性实质验证");
    expect(messages[1]).toContain("分析结果是否属实");
    expect(substanceNotes[0]).toContain("整体性 /verify");
  });

  it("opens the MCP manager as a custom page and preserves status fallback", async () => {
    let mcpHandler: ((args: string, ctx: any) => Promise<void>) | undefined;
    const api = {
      registerCommand(name: string, options: { handler: (args: string, ctx: any) => Promise<void> }) {
        if (name === "mcp") mcpHandler = options.handler;
      },
      registerTool() {},
    } as any;
    extension(api);

    let customCalls = 0;
    await mcpHandler?.("", {
      cwd: await mkdtemp(join(tmpdir(), "psyclaw-extension-mcp-ui-")),
      hasUI: true,
      ui: {
        custom: async () => {
          customCalls += 1;
          return { type: "close" };
        },
        notify: () => undefined,
      },
    });
    expect(customCalls).toBe(1);

    const notifications: string[] = [];
    await mcpHandler?.("status", {
      cwd: await mkdtemp(join(tmpdir(), "psyclaw-extension-mcp-status-")),
      hasUI: false,
      ui: { notify: (message: string) => notifications.push(message) },
    });
    expect(notifications[0]).toContain("paper-search-mcp");
    expect(notifications[0]).toContain("[off]");
  });

  it("fails closed before creating an agent run for an uninitialized project", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-extension-agents-"));
    let agentsHandler: ((args: string, ctx: any) => Promise<void>) | undefined;
    const api = {
      registerCommand(name: string, options: { handler: (args: string, ctx: any) => Promise<void> }) {
        if (name === "agents") agentsHandler = options.handler;
      },
      registerTool() {},
    } as any;
    extension(api);
    const notifications: string[] = [];
    await agentsHandler?.("inspect the local project", {
      cwd: root,
      hasUI: true,
      ui: {
        confirm: async () => { throw new Error("confirmation should not be requested"); },
        notify: (message: string) => notifications.push(message),
      },
    });
    expect(notifications[0]).toContain("请先使用 /init 初始化研究项目");
    expect(existsSync(join(root, ".psyclaw"))).toBe(false);
  });

  it("does not register /run or /brief", () => {
    const names: string[] = [];
    const api = {
      registerCommand(name: string) { names.push(name); },
      registerTool() {},
    } as any;
    extension(api);
    expect(names).not.toContain("run");
    expect(names).not.toContain("brief");
    expect(names).toContain("init");
    expect(names).toContain("verify");
  });

  describe("interactive LLM telemetry", () => {
    afterEach(async () => {
      await shutdownObservability();
    });

    function modernApi() {
      const handlers = new Map<string, Array<(event: any, ctx: any) => unknown>>();
      const api = {
        registerCommand() {},
        registerTool() {},
        on(event: string, handler: (event: any, ctx: any) => unknown) {
          const list = handlers.get(event) ?? [];
          list.push(handler);
          handlers.set(event, list);
        },
      } as any;
      return { api, handlers };
    }

    async function emit(handlers: Map<string, Array<(event: any, ctx: any) => unknown>>, event: string, payload: unknown, ctx: unknown) {
      for (const handler of handlers.get(event) ?? []) {
        await handler(payload, ctx);
      }
    }

    it("captures $ai_generation and cli.llm_call on turn_end and skips duplicate agent_end", async () => {
      const generations: unknown[] = [];
      const spans: Array<{ name: string; attributes: Record<string, string>; ended?: Record<string, string> }> = [];
      setObservabilityHandleForTests({
        captureEvent() {},
        captureError() {},
        captureLlmGeneration(input) { generations.push(input); },
        startSpan(name, attributes) {
          const span = { name, attributes };
          spans.push(span);
          return {
            setAttributes(next) { Object.assign(span.attributes, next); },
            end(next) { span.ended = next ?? {}; },
          };
        },
        async flush() {},
      });
      const { api, handlers } = modernApi();
      extension(api);
      const ctx = { hasUI: true, mode: "tui", model: { provider: "deepseek", id: "deepseek-v4-flash" } };
      await emit(handlers, "agent_start", { type: "agent_start" }, ctx);
      await emit(handlers, "turn_start", { type: "turn_start", turnIndex: 0, timestamp: Date.now() - 40 }, ctx);
      await emit(handlers, "turn_end", {
        type: "turn_end",
        turnIndex: 0,
        message: { provider: "deepseek", model: "deepseek-v4-flash", usage: { input: 8, output: 2 } },
        toolResults: [],
      }, ctx);
      await emit(handlers, "agent_end", {
        type: "agent_end",
        messages: [{ provider: "deepseek", model: "deepseek-v4-flash", usage: { input: 8, output: 2 } }],
      }, ctx);

      expect(generations).toHaveLength(1);
      expect(generations[0]).toMatchObject({
        provider: "deepseek",
        model: "deepseek-v4-flash",
        usage: { input: 8, output: 2 },
        surface: "cli",
        spanName: "pi-turn",
      });
      expect((generations[0] as { latencyMs?: number }).latencyMs).toBeGreaterThanOrEqual(40);
      expect(spans).toHaveLength(1);
      expect(spans[0]).toMatchObject({
        name: "cli.llm_call",
        attributes: { phase: "pi_turn", provider: "deepseek", model: "deepseek-v4-flash" },
      });
      expect(spans[0]?.ended).toMatchObject({ phase: "pi_turn", provider: "deepseek", model: "deepseek-v4-flash" });
    });

    it("falls back to agent_end when turn_end has no usage metadata", async () => {
      const generations: unknown[] = [];
      setObservabilityHandleForTests({
        captureEvent() {},
        captureError() {},
        captureLlmGeneration(input) { generations.push(input); },
        async flush() {},
      });
      const { api, handlers } = modernApi();
      extension(api);
      const ctx = { hasUI: false, mode: "rpc", model: { provider: "openai", id: "gpt-5" } };
      await emit(handlers, "agent_start", { type: "agent_start" }, ctx);
      await emit(handlers, "turn_end", {
        type: "turn_end",
        turnIndex: 0,
        message: { role: "assistant", content: [{ type: "text", text: "ok" }] },
        toolResults: [],
      }, ctx);
      await emit(handlers, "agent_end", {
        type: "agent_end",
        messages: [
          { role: "user", content: "研究目标" },
          { usage: { input: 3, output: 1 } },
        ],
      }, ctx);
      expect(generations).toHaveLength(1);
      expect(generations[0]).toMatchObject({
        provider: "openai",
        model: "gpt-5",
        usage: { input: 3, output: 1 },
        surface: "cli",
        spanName: "pi-turn",
      });
    });
  });

  it("hard-blocks wsl --unregister on tool_call even without an active project", async () => {
    const handlers = new Map<string, Array<(event: any, ctx: any) => Promise<unknown>>>();
    const api = {
      registerCommand() {},
      registerTool() {},
      on(event: string, handler: (event: any, ctx: any) => Promise<unknown>) {
        const list = handlers.get(event) ?? [];
        list.push(handler);
        handlers.set(event, list);
      },
    } as any;
    extension(api);
    const toolHandlers = handlers.get("tool_call") ?? [];
    expect(toolHandlers.length).toBeGreaterThan(0);
    const notifications: string[] = [];
    const result = await toolHandlers[0]!({
      toolName: "bash",
      toolCallId: "call_wsl",
      input: { command: "wsl --unregister Ubuntu" },
    }, {
      cwd: await mkdtemp(join(tmpdir(), "psyclaw-wsl-block-")),
      hasUI: true,
      ui: { notify: (message: string) => notifications.push(message) },
    });
    expect(result).toMatchObject({ block: true, terminate: true });
    expect(String((result as { reason?: string }).reason)).toContain("不可逆主机操作");
    expect(notifications.some((n) => n.includes("wsl --unregister"))).toBe(true);
  });

  it("gives shell commands a default time limit and explains a timeout to the agent", async () => {
    const handlers = new Map<string, (event: any, ctx: any) => Promise<any>>();
    const api = {
      registerCommand() {},
      registerTool() {},
      on(name: string, handler: (event: any, ctx: any) => Promise<any>) {
        handlers.set(name, handler);
      },
    } as any;
    extension(api);
    const ctx = { cwd: await mkdtemp(join(tmpdir(), "psyclaw-shell-timeout-")), hasUI: true, ui: { notify() {} } };
    const plain = { command: "Rscript results/analysis.R" };
    await handlers.get("tool_call")!({ toolName: "bash", toolCallId: "t1", input: plain }, ctx);
    expect(plain).toMatchObject({ timeout: 600 });
    const long = { command: "Rscript boot.R", timeout: 7_200 };
    await handlers.get("tool_call")!({ toolName: "bash", toolCallId: "t2", input: long }, ctx);
    expect(long.timeout).toBe(1_800);
    const short = { command: "ls", timeout: 30 };
    await handlers.get("tool_call")!({ toolName: "bash", toolCallId: "t3", input: short }, ctx);
    expect(short.timeout).toBe(30);
    const read = { path: "results/report.md" } as Record<string, unknown>;
    await handlers.get("tool_call")!({ toolName: "read", toolCallId: "t4", input: read }, ctx);
    expect(read.timeout).toBeUndefined();

    const result = await handlers.get("tool_result")!({
      toolName: "bash",
      toolCallId: "t1",
      content: [{ type: "text", text: "fitting...\n\nCommand timed out after 600 seconds" }],
      isError: true,
    }, ctx);
    expect(result.content[0].text).toContain("Command timed out after 600 seconds");
    expect(result.content[0].text).toContain("subsample");
  });

  it("loads a user skill headlessly and records a same-name skip", async () => {
    const handlers = new Map<string, (event: any, ctx: any) => Promise<any>>();
    const entries: unknown[] = [];
    const api = {
      registerCommand() {},
      registerTool() {},
      appendEntry(type: string, data: unknown) { entries.push({ type, data }); },
      on(name: string, handler: (event: any, ctx: any) => Promise<any>) { handlers.set(name, handler); },
    } as any;
    extension(api);
    const root = await mkdtemp(join(tmpdir(), "psyclaw-skill-resolution-"));
    const userSkill = join(root, "skills", "project-moderation");
    const sameName = join(root, ".psyclaw", "skills", "analysis-plan");
    await mkdir(userSkill, { recursive: true });
    await mkdir(sameName, { recursive: true });
    await writeFile(join(userSkill, "SKILL.md"), "---\nname: project-moderation\ndescription: Project moderation\ntopics:\n  - interactions\n---\n", "utf8");
    await writeFile(join(sameName, "SKILL.md"), "---\nname: analysis-plan\ndescription: Duplicate\n---\n", "utf8");

    const discovered = await handlers.get("resources_discover")!({ cwd: root });
    expect(discovered.skillPaths).toContain(userSkill);
    expect(discovered.skillPaths).not.toContain(sameName);

    const notes: string[] = [];
    await handlers.get("session_start")!({}, {
      cwd: root,
      hasUI: true,
      ui: { notify(message: string) { notes.push(message); }, setStatus() {} },
    });
    expect(notes.join("\n")).toContain(sameName);
    expect(entries.some((entry) => (entry as { type: string }).type === "psyclaw-skill-resolution")).toBe(true);

    const quiet: string[] = [];
    const headlessRoot = await mkdtemp(join(tmpdir(), "psyclaw-skill-resolution-quiet-"));
    const quietSkill = join(headlessRoot, ".psyclaw", "skills", "method-interactions");
    await mkdir(quietSkill, { recursive: true });
    await writeFile(join(quietSkill, "SKILL.md"), "---\nname: method-interactions\ndescription: Duplicate\n---\n", "utf8");
    await handlers.get("session_start")!({}, {
      cwd: headlessRoot,
      hasUI: false,
      ui: { notify(message: string) { quiet.push(message); } },
    });
    expect(quiet).toEqual([]);
    const saved = JSON.parse(await readFile(join(headlessRoot, ".psyclaw/skill-resolution.json"), "utf8")) as {
      skipped: Array<{ path: string; reason: string }>;
    };
    expect(saved.skipped).toContainEqual({ name: "method-interactions", path: quietSkill, reason: "core-name" });
  });

  it("injects the interactions skill into an analysis-mode turn and does not inject it again", async () => {
    const handlers = new Map<string, (event: any, ctx: any) => Promise<any>>();
    const api = {
      registerCommand() {},
      registerTool() {},
      appendEntry() {},
      on(name: string, handler: (event: any, ctx: any) => Promise<any>) { handlers.set(name, handler); },
    } as any;
    extension(api);
    const root = await mkdtemp(join(tmpdir(), "psyclaw-method-inject-"));
    await bootstrapProject({ root, goal: "method injection", paradigm: "survey-observational" });
    const ctx = {
      cwd: root,
      hasUI: false,
      ui: { notify() {} },
      sessionManager: { getBranch: () => [{ type: "custom", customType: "psyclaw-session-mode", data: { mode: "analysis" } }] },
    };
    const first = await handlers.get("input")!({ text: "做一下调节分析", source: "interactive" }, ctx);
    expect(first.text).toContain("/skill:analysis-plan");
    expect(first.text).toContain("topic=interactions");
    const second = await handlers.get("input")!({ text: "再做一次调节分析", source: "interactive" }, ctx);
    expect(second.text).not.toContain("[psyclaw:method-skill");
  });
});
