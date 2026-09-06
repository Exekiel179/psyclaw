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
    // hosts, while UI-gated research commands (run/agents/grill/...) are not
    // registered at all.
    expect([...commands.keys()]).toEqual(["init", "verify", "brief", "model"]);
  });

  it("registers the full research command surface on a modern Pi API", () => {
    const commands: string[] = [];
    const api = {
      registerCommand(name: string) { commands.push(name); },
      registerTool() {},
    } as any;
    extension(api);
    expect(commands).toEqual([
      "init", "verify", "run", "brief", "grill", "review", "loop",
      "create-skill", "create-hook", "create-rule", "create-subagent",
      "skill", "ars", "plugin", "mcp", "provider", "pet", "agents",
    ]);
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
    expect(notifications[0]).toContain("工作仓库已初始化");
  });

  it("allows paradigm-only init without a goal string", async () => {
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
      expect.objectContaining({ name: "skill" }),
      expect.objectContaining({ name: "plugin" }),
    ]));
    expect(commands.some((command) => command.name === "skills")).toBe(false);
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
    expect(notifications[0]).toContain("已启动学术追问");
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

  it("keeps ordinary mode when /run has compliant analysis documents but no /init project", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-extension-run-docs-"));
    await mkdir(join(root, "notes"), { recursive: true });
    await writeFile(join(root, "notes", "research-spec.md"), [
      "---",
      "schemaVersion: psyclaw/research-spec/v1",
      "documentVersion: 1.0.0",
      "---",
      "- Status: confirmed",
      "- Initial goal: 大学生自我效能的纵向研究",
      "- Paradigm: survey-observational",
    ].join("\n"), "utf8");
    await writeFile(join(root, "notes", "plan.md"), [
      "---",
      "schemaVersion: psyclaw/hitl-plan/v1",
      "documentVersion: 1.0.0",
      "---",
      "- Status: approved",
      "- Goal: 大学生自我效能的纵向研究",
    ].join("\n"), "utf8");

    let runHandler: ((args: string, ctx: any) => Promise<void>) | undefined;
    let entryCalls = 0;
    let sentMessages = 0;
    const api = {
      registerCommand(name: string, options: { handler: (args: string, ctx: any) => Promise<void> }) {
        if (name === "run") runHandler = options.handler;
      },
      registerTool() {},
      appendEntry() { entryCalls += 1; },
      sendUserMessage() { sentMessages += 1; },
    } as any;
    extension(api);

    const notifications: string[] = [];
    await runHandler?.("", {
      cwd: root,
      isIdle: () => true,
      ui: { notify: (message: string) => notifications.push(message) },
    });

    // Analysis documents alone must not silently start a controlled run: /run
    // only activates a project that was explicitly established via /init, so
    // ordinary conversation mode is preserved with a clear pointer to /init.
    expect(notifications.some((message) => message.includes("/init"))).toBe(true);
    expect(existsSync(join(root, ".psyclaw", "project.json"))).toBe(false);
    expect(existsSync(join(root, ".psyclaw", "controlled-run.json"))).toBe(false);
    expect(entryCalls).toBe(0);
    expect(sentMessages).toBe(0);
  });

  it("still warns when /run has neither project.json nor compliant analysis documents", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-extension-run-none-"));
    let runHandler: ((args: string, ctx: any) => Promise<void>) | undefined;
    const api = {
      registerCommand(name: string, options: { handler: (args: string, ctx: any) => Promise<void> }) {
        if (name === "run") runHandler = options.handler;
      },
      registerTool() {},
      appendEntry() {},
      sendUserMessage() {},
    } as any;
    extension(api);
    const notifications: string[] = [];
    await runHandler?.("", {
      cwd: root,
      isIdle: () => true,
      ui: { notify: (message: string) => notifications.push(message) },
    });
    expect(notifications.some((message) => message.includes("research-spec.md") || message.includes("/init"))).toBe(true);
    expect(existsSync(join(root, ".psyclaw", "project.json"))).toBe(false);
  });

  it("stores a deduplicated per-run Skill selection without changing global Skill state", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-extension-run-skills-"));
    await bootstrapProject({ root, goal: "Skill-assisted review", paradigm: "qualitative-thematic" });
    let runHandler: ((args: string, ctx: any) => Promise<void>) | undefined;
    let sentMessage = "";
    const api = {
      registerCommand(name: string, options: { handler: (args: string, ctx: any) => Promise<void> }) {
        if (name === "run") runHandler = options.handler;
      },
      registerTool() {},
      appendEntry() {},
      sendUserMessage(text: string) { sentMessage = text; },
      on() {},
    } as any;
    extension(api);

    await runHandler?.("--skills academic-grill,academic-grill Focus the review", {
      cwd: root,
      hasUI: false,
      isIdle: () => true,
      ui: { notify() {} },
    });

    const state = JSON.parse(await readFile(join(root, ".psyclaw", "controlled-run.json"), "utf8"));
    expect(state).toMatchObject({ objective: "Focus the review", selectedSkills: ["academic-grill"] });
    expect(sentMessage).toContain("本次运行由用户选择的优化 Skill：academic-grill");
  });
});
