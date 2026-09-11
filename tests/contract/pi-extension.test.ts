import { describe, expect, it } from "vitest";
import { mkdtemp, readFile, writeFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import extension from "../../src/adapters/pi/extension.js";
import { bootstrapProject } from "../../src/project/bootstrap.js";

describe("Pi extension contract", () => {
  it("registers only the small research command surface", async () => {
    const commands = new Map<string, { handler: (args: string, ctx: any) => Promise<void> }>();
    const api = {
      registerCommand(name: string, options: { handler: (args: string, ctx: any) => Promise<void> }) {
        commands.set(name, options);
      },
    } as any;
    extension(api);
    expect([...commands.keys()]).toEqual(["init", "verify", "brief", "model", "agents"]);
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
    expect(notifications[0]).toContain("研究项目已初始化");
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
      expect.objectContaining({ name: "telemetry" }),
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

  it("manages agent personas and gates /agents run behind developer mode", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-extension-agents-"));
    let agentsHandler: ((args: string, ctx: any) => Promise<void>) | undefined;
    const api = {
      registerCommand(name: string, options: { handler: (args: string, ctx: any) => Promise<void> }) {
        if (name === "agents") agentsHandler = options.handler;
      },
    } as any;
    extension(api);
    const notifications: string[] = [];
    const ctx = {
      cwd: root,
      hasUI: true,
      ui: {
        confirm: async () => { throw new Error("confirmation should not be requested"); },
        notify: (message: string) => notifications.push(message),
      },
    };

    await agentsHandler?.("", ctx);
    expect(notifications.at(-1)).toMatch(/无人设|Usage|用法/);

    await agentsHandler?.("set reviewer 你是严格的方法学审稿人，不编造证据。", ctx);
    expect(notifications.at(-1)).toContain("reviewer");

    await agentsHandler?.("use reviewer", ctx);
    expect(notifications.at(-1)).toContain("reviewer");

    await agentsHandler?.("run inspect the local project", ctx);
    expect(notifications.at(-1)).toMatch(/开发者模式|--developer/);

    const previous = process.env.PSYCLAW_DEVELOPER_COMMANDS;
    process.env.PSYCLAW_DEVELOPER_COMMANDS = "1";
    try {
      await agentsHandler?.("run inspect the local project", ctx);
      expect(notifications.at(-1)).toMatch(/\/init/);
      expect(existsSync(join(root, ".psyclaw", "plans"))).toBe(false);
    } finally {
      if (previous === undefined) delete process.env.PSYCLAW_DEVELOPER_COMMANDS;
      else process.env.PSYCLAW_DEVELOPER_COMMANDS = previous;
    }
  });

  it("activates /run from compliant analysis documents without /init", async () => {
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
    let entry: Record<string, unknown> | undefined;
    let sentMessage: string | undefined;
    const api = {
      registerCommand(name: string, options: { handler: (args: string, ctx: any) => Promise<void> }) {
        if (name === "run") runHandler = options.handler;
      },
      registerTool() {},
      appendEntry(_key: string, value: Record<string, unknown>) { entry = value; },
      sendUserMessage(text: string) { sentMessage = text; },
    } as any;
    extension(api);

    const notifications: string[] = [];
    await runHandler?.("", {
      cwd: root,
      isIdle: () => true,
      ui: { notify: (message: string) => notifications.push(message) },
    });

    expect(existsSync(join(root, ".psyclaw", "project.json"))).toBe(true);
    const project = JSON.parse(await readFile(join(root, ".psyclaw", "project.json"), "utf8"));
    expect(project.goal).toContain("自我效能");
    expect(existsSync(join(root, ".psyclaw", "controlled-run.json"))).toBe(true);
    expect(entry).toMatchObject({ projectId: project.id });
    expect(sentMessage).toContain("受控研究流程已由用户通过 /run 明确启动");
    expect(notifications.some((message) => message.includes("合规的分析文档"))).toBe(true);
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

  it("asks for a missing provider API key without throwing", async () => {
    const previous = process.env.OPENCODE_API_KEY;
    delete process.env.OPENCODE_API_KEY;
    let providerHandler: ((args: string, ctx: any) => Promise<void>) | undefined;
    const api = {
      registerCommand(name: string, options: { handler: (args: string, ctx: any) => Promise<void> }) {
        if (name === "provider") providerHandler = options.handler;
      },
      registerTool() {},
      setModel: async () => {
        throw new Error("setModel should not run when the API key is missing");
      },
    } as any;
    extension(api);
    const notifications: Array<{ message: string; level?: string }> = [];
    let customCalls = 0;
    try {
      await providerHandler?.("opencode-go", {
        hasUI: true,
        model: undefined,
        modelRegistry: {
          getAll: () => [],
          refresh: async () => undefined,
        },
        ui: {
          notify: (message: string, level?: string) => notifications.push({ message, level }),
          custom: async () => {
            customCalls += 1;
            if (customCalls === 1) return { type: "select", id: "deepseek-v4-flash" };
            return { type: "submit", value: "" };
          },
        },
      });
    } finally {
      if (previous === undefined) delete process.env.OPENCODE_API_KEY;
      else process.env.OPENCODE_API_KEY = previous;
    }
    expect(customCalls).toBe(2);
    expect(notifications[0]?.level).toBe("warning");
    expect(notifications[0]?.message).toBe("未找到 OPENCODE_API_KEY；请输入 API Key 后再继续");
  });
});
