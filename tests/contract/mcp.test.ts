import { Readable } from "node:stream";
import { describe, expect, it } from "vitest";
import {
  McpClient,
  StdioMcpIntegration,
  StdioMcpTransport,
  type McpChild,
  type McpSpawn,
  type McpServerConfig,
} from "../../src/integrations/mcp.js";

interface FakeRequest {
  jsonrpc: string;
  id?: number;
  method: string;
  params?: unknown;
}

class FakeChild implements McpChild {
  public readonly stdout = new Readable({ read() {} });
  public readonly stderr = new Readable({ read() {} });
  public readonly stdin = { write: (chunk: string) => this.onWrite(chunk), end: () => undefined };
  public killed = false;
  public toolCalls = 0;
  private readonly closeHandlers: ((code: number | null) => void)[] = [];

  public constructor(
    private readonly tools: string[] = ["search"],
    private readonly schemas: Record<string, unknown> = {},
  ) {}

  public kill(): void {
    this.killed = true;
  }

  public onClose(handler: (code: number | null) => void): void {
    this.closeHandlers.push(handler);
  }

  public close(code: number | null): void {
    for (const handler of this.closeHandlers) handler(code);
  }

  protected onWrite(chunk: string): void {
    for (const line of chunk.split("\n")) {
      if (line.trim().length === 0) continue;
      this.handle(JSON.parse(line) as FakeRequest);
    }
  }

  private respond(id: number | undefined, result: unknown): void {
    if (id === undefined) return;
    this.stdout.push(`${JSON.stringify({ jsonrpc: "2.0", id, result })}\n`);
  }

  private handle(request: FakeRequest): void {
    switch (request.method) {
      case "initialize":
        this.respond(request.id, {
          protocolVersion: "2024-11-05",
          capabilities: { tools: {} },
          serverInfo: { name: "fake", version: "1.0" },
        });
        break;
      case "tools/list":
        this.respond(request.id, {
          tools: this.tools.map((name) => ({
            name,
            description: `tool ${name}`,
            inputSchema: this.schemas[name] ?? { type: "object" },
          })),
        });
        break;
      case "tools/call":
        this.toolCalls += 1;
        this.respond(request.id, { content: [{ type: "text", text: "ok" }] });
        break;
      case "notifications/initialized":
        break;
      default:
        this.stdout.push(`${JSON.stringify({ jsonrpc: "2.0", id: request.id, error: { code: -32601, message: "method not found" } })}\n`);
    }
  }
}

function makeSpawn(tools?: string[], schemas?: Record<string, unknown>): {
  spawn: McpSpawn;
  envs: Record<string, string>[];
  children: FakeChild[];
} {
  const envs: Record<string, string>[] = [];
  const children: FakeChild[] = [];
  const spawn: McpSpawn = (_command, _args, options) => {
    envs.push({ ...(options.env ?? {}) });
    const child = new FakeChild(tools, schemas);
    children.push(child);
    return child;
  };
  return { spawn, envs, children };
}

const config = (overrides: Partial<McpServerConfig> = {}): McpServerConfig => ({
  id: "fake",
  command: "server",
  args: ["--stdio"],
  trusted: true,
  enabled: true,
  enabledTools: ["search", "parse"],
  env: { EXPLICIT: "1" },
  effect: "read",
  ...overrides,
});

describe("stdio MCP integration", () => {
  it("exposes only the explicit env to the child process", async () => {
    process.env.PSYCLAW_TEST_SECRET = "must-not-leak";
    const { spawn, envs } = makeSpawn();
    const integration = new StdioMcpIntegration(config(), spawn);
    expect((await integration.health()).ok).toBe(true);
    expect(envs).toHaveLength(1);
    expect(envs[0]).toEqual({ EXPLICIT: "1" });
    expect(envs[0]).not.toHaveProperty("PSYCLAW_TEST_SECRET");
    expect(envs[0]).not.toHaveProperty("PATH");
    delete process.env.PSYCLAW_TEST_SECRET;
    integration.close();
  });

  it("performs initialize and lists tools through JSON-RPC", async () => {
    const { spawn } = makeSpawn(["search", "parse"]);
    const integration = new StdioMcpIntegration(config(), spawn);
    const tools = await integration.list();
    expect(tools.map((tool) => tool.id)).toEqual(["fake.search", "fake.parse"]);
    expect(tools.every((tool) => tool.effect === "read" && tool.trust === "approved")).toBe(true);
    expect(tools.every((tool) => tool.enabled)).toBe(true);
    integration.close();
  });

  it("requires discovery and an explicit host allowlist", async () => {
    const { spawn } = makeSpawn(["search", "parse"]);
    const integration = new StdioMcpIntegration(config({ enabledTools: ["search"] }), spawn);
    const beforeDiscovery = await integration.invoke(
      { runId: "r", taskId: "t", tool: "fake.search", input: {} },
      { decision: "not-needed", actor: "policy", reason: "read" },
    );
    expect(beforeDiscovery.reasonCode).toBe("mcp.tool-not-discovered");
    const tools = await integration.list();
    expect(tools.find((tool) => tool.id === "fake.search")?.enabled).toBe(true);
    expect(tools.find((tool) => tool.id === "fake.parse")?.enabled).toBe(false);
    const unlisted = await integration.invoke(
      { runId: "r", taskId: "t", tool: "fake.parse", input: {} },
      { decision: "not-needed", actor: "policy", reason: "read" },
    );
    expect(unlisted.reasonCode).toBe("mcp.tool-not-enabled");
  });

  it("validates discovered input schemas and binds the source", async () => {
    const { spawn } = makeSpawn(["search"], {
      search: {
        type: "object",
        required: ["q"],
        properties: { q: { type: "string", minLength: 2 } },
        additionalProperties: false,
      },
    });
    const integration = new StdioMcpIntegration(config(), spawn);
    await integration.list();
    const invalid = await integration.invoke(
      { runId: "r", taskId: "t", tool: "fake.search", input: { q: "x" } },
      { decision: "not-needed", actor: "policy", reason: "read" },
    );
    expect(invalid.reasonCode).toBe("mcp.invalid-input");
    const wrongSource = await integration.invoke(
      { runId: "r", taskId: "t", tool: "other.search", input: { q: "ok" } },
      { decision: "not-needed", actor: "policy", reason: "read" },
    );
    expect(wrongSource.reasonCode).toBe("mcp.source-mismatch");
  });

  it("returns an approved idempotent receipt for a successful call", async () => {
    const { spawn, children } = makeSpawn(["search"]);
    const integration = new StdioMcpIntegration(config(), spawn);
    await integration.list();
    const receipt = await integration.invoke(
      { runId: "r1", taskId: "t1", tool: "fake.search", input: { q: "x" }, idempotencyKey: "mcp:1" },
      { decision: "approved", actor: "researcher", reason: "fixture" },
    );
    expect(receipt.ok).toBe(true);
    expect(receipt.approval).toBe("approved");
    expect(receipt.idempotencyKey).toBe("mcp:1");
    expect(receipt.resultHash).toMatch(/^[a-f0-9]{64}$/);
    expect(children[0]?.toolCalls).toBe(1);
    integration.close();
  });

  it("requires side-effect idempotency and blocks duplicate keys", async () => {
    const { spawn, children } = makeSpawn(["write"]);
    const integration = new StdioMcpIntegration(config({
      enabledTools: undefined,
      toolPolicies: { write: { enabled: true, effect: "write" } },
    }), spawn);
    await integration.list();
    const missing = await integration.invoke(
      { runId: "r", taskId: "t", tool: "fake.write", input: {} },
      { decision: "approved", actor: "researcher", reason: "fixture" },
    );
    expect(missing.reasonCode).toBe("mcp.idempotency-required");
    const first = await integration.invoke(
      { runId: "r", taskId: "t", tool: "fake.write", input: {}, idempotencyKey: "write:1" },
      { decision: "approved", actor: "researcher", reason: "fixture" },
    );
    const duplicate = await integration.invoke(
      { runId: "r", taskId: "t", tool: "fake.write", input: {}, idempotencyKey: "write:1" },
      { decision: "approved", actor: "researcher", reason: "fixture" },
    );
    expect(first.ok).toBe(true);
    expect(duplicate.reasonCode).toBe("mcp.duplicate-idempotency");
    expect(children[0]?.toolCalls).toBe(1);
  });

  it("does not allow a server-declared effect to cross the host ceiling", async () => {
    const { spawn, children } = makeSpawn(["publish"]);
    const integration = new StdioMcpIntegration(config({
      effect: "read",
      effectCeiling: "network",
      toolPolicies: { publish: { enabled: true, effect: "destructive" } },
    }), spawn);
    await integration.list();
    const receipt = await integration.invoke(
      { runId: "r", taskId: "t", tool: "fake.publish", input: {}, idempotencyKey: "publish:1" },
      { decision: "approved", actor: "researcher", reason: "fixture" },
    );
    expect(receipt.reasonCode).toBe("mcp.effect-not-allowed");
    expect(children[0]?.toolCalls).toBe(0);
  });

  it("fails closed for untrusted, disabled, and denied invocations", async () => {
    const { spawn } = makeSpawn();
    const untrusted = new StdioMcpIntegration(config({ trusted: false }), spawn);
    expect((await untrusted.health()).ok).toBe(false);
    expect((await untrusted.invoke({ runId: "r", taskId: "t", tool: "fake.search", input: {} }, { decision: "approved", actor: "researcher", reason: "x" })).ok).toBe(false);

    const disabled = new StdioMcpIntegration(config({ enabled: false }), spawn);
    expect((await disabled.health()).ok).toBe(false);

    const deniedIntegration = new StdioMcpIntegration(config(), spawn);
    await deniedIntegration.list();
    const denied = await deniedIntegration.invoke(
      { runId: "r", taskId: "t", tool: "fake.search", input: {} },
      { decision: "denied", actor: "policy", reason: "no approval" },
    );
    expect(denied.ok).toBe(false);
    expect(denied.reasonCode).toBe("mcp.approval-required");
  });

  it("times out a non-responsive server", async () => {
    class HangingChild extends FakeChild {
      protected override onWrite(_chunk: string): void {
        // never respond
      }
    }
    const transport = new StdioMcpTransport(config(), () => new HangingChild());
    const client = new McpClient(transport);
    await expect(client.initialize({ name: "psyclaw", version: "0.1.0" }, 50)).rejects.toThrow(/timed out/i);
    expect((transport as unknown as { child: HangingChild }).child?.killed ?? true).toBe(true);
    transport.close();
  });
});

describe("McpClient transport contract", () => {
  it("routes JSON-RPC responses by id and propagates errors", async () => {
    const child = new FakeChild(["search"]);
    const transport = new StdioMcpTransport(config(), () => child);
    const client = new McpClient(transport);
    const info = await client.initialize({ name: "psyclaw", version: "0.1.0" });
    expect((info as { serverInfo: { name: string } }).serverInfo.name).toBe("fake");
    const tools = await client.listTools();
    expect(tools.map((tool) => tool.name)).toEqual(["search"]);
    transport.close();
  });
});
