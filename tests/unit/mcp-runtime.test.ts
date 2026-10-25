import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Readable } from "node:stream";
import { describe, expect, it } from "vitest";
import type { McpChild, McpSpawn } from "../../src/integrations/mcp.js";
import { RuntimeMcpRegistry } from "../../src/integrations/mcp-runtime.js";

class FakeChild implements McpChild {
  public readonly stdout = new Readable({ read() {} });
  public readonly stderr = new Readable({ read() {} });
  public readonly stdin = { write: (chunk: string) => this.onWrite(chunk), end: () => undefined };
  private readonly closeHandlers: ((code: number | null) => void)[] = [];

  public constructor(private readonly hangOnCall: boolean) {}

  public kill(): void {
    for (const handler of this.closeHandlers) handler(null);
  }

  public onClose(handler: (code: number | null) => void): void {
    this.closeHandlers.push(handler);
  }

  private onWrite(chunk: string): void {
    for (const line of chunk.split("\n")) {
      if (line.trim().length === 0) continue;
      const request = JSON.parse(line) as { id?: number; method: string };
      if (request.id === undefined) continue;
      if (request.method === "tools/call" && this.hangOnCall) continue;
      const result = request.method === "initialize"
        ? { protocolVersion: "2024-11-05", capabilities: { tools: {} }, serverInfo: { name: "fake", version: "1.0" } }
        : request.method === "tools/list"
          ? { tools: [{ name: "ask", description: "slow tool", inputSchema: { type: "object" } }] }
          : { content: [{ type: "text", text: "answer" }] };
      this.stdout.push(`${JSON.stringify({ jsonrpc: "2.0", id: request.id, result })}\n`);
    }
  }
}

async function projectWithServer(requestTimeoutMs: number): Promise<string> {
  const root = await mkdtemp(join(tmpdir(), "psyclaw-mcp-runtime-"));
  await mkdir(join(root, ".psyclaw", "mcp"), { recursive: true });
  await writeFile(join(root, ".psyclaw", "mcp", "slow.json"), JSON.stringify({
    id: "psyclaw-test-slow",
    command: "fake",
    args: [],
    requestTimeoutMs,
  }));
  return root;
}

describe("RuntimeMcpRegistry", () => {
  it("starts a fresh server after a call times out instead of reusing the closed transport", async () => {
    const root = await projectWithServer(50);
    const children: FakeChild[] = [];
    const spawn: McpSpawn = () => {
      const child = new FakeChild(children.length === 0);
      children.push(child);
      return child;
    };
    const registry = new RuntimeMcpRegistry(spawn);

    await expect(registry.call(root, "psyclaw-test-slow", "ask", {})).rejects.toThrow("MCP request timed out");
    await expect(registry.call(root, "psyclaw-test-slow", "ask", {})).resolves.toEqual({ content: [{ type: "text", text: "answer" }] });
    expect(children).toHaveLength(2);
    registry.close();
  });
});
