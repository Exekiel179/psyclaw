import { describe, expect, it } from "vitest";
import { mkdtemp, readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import extension from "../../src/adapters/pi/extension.js";

describe("Pi extension contract", () => {
  it("registers only the small research command surface", async () => {
    const commands = new Map<string, { handler: (args: string, ctx: any) => Promise<void> }>();
    const api = {
      registerCommand(name: string, options: { handler: (args: string, ctx: any) => Promise<void> }) {
        commands.set(name, options);
      },
    } as any;
    extension(api);
    expect([...commands.keys()]).toEqual(["init", "verify", "brief", "trace", "model", "agents"]);
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
    await initHandler?.("--paradigm qualitative-thematic A bounded goal", {
      cwd: root,
      ui: { notify: (message: string) => notifications.push(message) },
    });
    const project = JSON.parse(await readFile(join(root, ".psyclaw", "project.json"), "utf8"));
    expect(project.paradigm).toBe("qualitative-thematic");
    expect(notifications[0]).toContain("Initialized");
  });

  it("does not reinterpret malformed flags as a research goal", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-extension-invalid-"));
    let initHandler: ((args: string, ctx: any) => Promise<void>) | undefined;
    const api = {
      registerCommand(name: string, options: { handler: (args: string, ctx: any) => Promise<void> }) {
        if (name === "init") initHandler = options.handler;
      },
    } as any;
    extension(api);
    const notifications: string[] = [];
    await initHandler?.("--paradigm survey-observational", {
      cwd: root,
      ui: { notify: (message: string) => notifications.push(message) },
    });
    expect(notifications[0]).toContain("Usage:");
    await expect(readFile(join(root, ".psyclaw", "project.json"), "utf8")).rejects.toThrow();
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
    ]));
    expect(commands.every((command) => Boolean(command.description?.trim()))).toBe(true);
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
    expect(notifications[0]).toContain("每轮只处理一个关键决策");
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
    expect(notifications[0]).toContain("Initialize a psyclaw project");
    expect(existsSync(join(root, ".psyclaw"))).toBe(false);
  });
});
