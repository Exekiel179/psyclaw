import { describe, expect, it } from "vitest";
import { mkdtemp, readFile, writeFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import extension from "../../src/adapters/pi/extension.js";
import { bootstrapProject } from "../../src/project/bootstrap.js";

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
    expect([...commands.keys()]).toEqual(["init", "crosscheck", "verify", "help", "plan", "handoff", "model"]);
  });

  it("registers the full research command surface on a modern Pi API", () => {
    const commands: string[] = [];
    const api = {
      registerCommand(name: string) { commands.push(name); },
      registerTool() {},
    } as any;
    extension(api);
    expect(commands).toEqual([
      "init", "crosscheck", "verify", "help", "plan", "handoff", "grill", "brainstorm", "review", "loop",
      "create-skill", "create-hook", "create-rule", "create-subagent",
      "skill", "ars", "plugin", "mcp", "provider", "pet", "telemetry", "agents",
    ]);
    expect(commands).not.toContain("run");
    expect(commands).not.toContain("brief");
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
    expect(messages[0]?.text).toContain("这是 /brainstorm，不是 /grill");
    expect(messages[0]?.text).toContain("不要加载 academic-grill");
    expect(messages[0]?.text).not.toContain("先调用 psyclaw_skill");
    expect(messages[0]?.text).toContain("头脑风暴主题：生成式 AI 与大学生批判性思维");
    expect(messages[0]?.options).toEqual({});
    expect(notifications[0]).toContain("已启动研究方向头脑风暴");
    expect(notifications[0]).toContain("不经过 /grill");
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
});
