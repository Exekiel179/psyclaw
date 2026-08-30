import { readdir, readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import { McpClient, StdioMcpTransport, type McpServerConfig, type McpTool } from "./mcp.js";

interface RuntimeMcpConfig extends McpServerConfig {
  name?: string;
  transport?: "stdio";
}

interface RuntimeConnection {
  config: RuntimeMcpConfig;
  transport: StdioMcpTransport;
  client: McpClient;
  tools?: McpTool[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function runtimeEnvironment(value: unknown): Record<string, string> {
  const configured = isRecord(value)
    ? Object.fromEntries(Object.entries(value).filter((entry): entry is [string, string] => typeof entry[1] === "string"))
    : {};
  return {
    ...(process.env.PATH ? { PATH: process.env.PATH } : {}),
    ...(process.env.HOME ? { HOME: process.env.HOME } : {}),
    ...(process.env.TMPDIR ? { TMPDIR: process.env.TMPDIR } : {}),
    ...(process.env.LANG ? { LANG: process.env.LANG } : {}),
    ...configured,
  };
}

function asRuntimeConfig(value: unknown): RuntimeMcpConfig | undefined {
  if (!isRecord(value) || typeof value.id !== "string" || typeof value.command !== "string") return undefined;
  if (value.enabled === false || value.trusted === false || (value.transport !== undefined && value.transport !== "stdio")) return undefined;
  const args = Array.isArray(value.args) && value.args.every((item) => typeof item === "string") ? value.args : [];
  return {
    id: value.id,
    command: value.command,
    args,
    env: runtimeEnvironment(value.env),
    trusted: true,
    enabled: true,
    ...(typeof value.name === "string" ? { name: value.name } : {}),
    transport: "stdio",
  };
}

async function configsIn(directory: string): Promise<RuntimeMcpConfig[]> {
  let names: string[];
  try {
    names = (await readdir(directory)).filter((name) => name.endsWith(".json")).sort();
  } catch {
    return [];
  }
  const configs: RuntimeMcpConfig[] = [];
  for (const name of names) {
    try {
      const config = asRuntimeConfig(JSON.parse(await readFile(join(directory, name), "utf8")));
      if (config) configs.push(config);
    } catch { /* Ignore malformed entries; they remain visible in MCP management. */ }
  }
  return configs;
}

export class RuntimeMcpRegistry {
  private readonly connections = new Map<string, RuntimeConnection>();

  public async list(root: string, serverId?: string): Promise<Array<{ serverId: string; serverName: string; tools: McpTool[] }>> {
    const configs = await this.configs(root);
    const selected = serverId ? configs.filter((config) => config.id === serverId) : configs;
    if (serverId && selected.length === 0) throw new Error(`MCP server is not configured or enabled: ${serverId}`);
    return Promise.all(selected.map(async (config) => {
      const connection = await this.connection(root, config);
      connection.tools ??= await connection.client.listTools();
      return { serverId: config.id, serverName: config.name ?? config.id, tools: connection.tools };
    }));
  }

  public async call(root: string, serverId: string, tool: string, input: Record<string, unknown>): Promise<unknown> {
    const config = (await this.configs(root)).find((candidate) => candidate.id === serverId);
    if (!config) throw new Error(`MCP server is not configured or enabled: ${serverId}`);
    const connection = await this.connection(root, config);
    connection.tools ??= await connection.client.listTools();
    if (!connection.tools.some((candidate) => candidate.name === tool)) throw new Error(`MCP tool is not available: ${serverId}.${tool}`);
    return connection.client.callTool(tool, input);
  }

  public close(): void {
    for (const connection of this.connections.values()) connection.client.close();
    this.connections.clear();
  }

  private async configs(root: string): Promise<RuntimeMcpConfig[]> {
    const user = await configsIn(join(homedir(), ".psyclaw", "mcp"));
    const project = await configsIn(join(root, ".psyclaw", "mcp"));
    const merged = new Map(user.map((config) => [config.id, config]));
    for (const config of project) merged.set(config.id, config);
    return [...merged.values()];
  }

  private async connection(root: string, config: RuntimeMcpConfig): Promise<RuntimeConnection> {
    const key = `${root}\u0000${config.id}\u0000${config.command}\u0000${JSON.stringify(config.args)}`;
    const existing = this.connections.get(key);
    if (existing) return existing;
    const transport = new StdioMcpTransport(config);
    const client = new McpClient(transport);
    await client.initialize({ name: "psyclaw", version: process.env.PSYCLAW_VERSION ?? "development" });
    client.initialized();
    const connection = { config, transport, client };
    this.connections.set(key, connection);
    return connection;
  }
}
