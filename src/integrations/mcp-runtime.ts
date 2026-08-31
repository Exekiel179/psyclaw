import { readdir, readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import { McpClient, StdioMcpTransport, type McpServerConfig, type McpTool } from "./mcp.js";
import { atomicWriteFile } from "../project/jsonl.js";

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

export interface UserMcpConfigEntry {
  id: string;
  name: string;
  command: string;
  /** Raw `enabled` flag from the config file; disabled servers stay visible for management. */
  enabled: boolean;
  path: string;
  scope: "user" | "project";
}

/**
 * Read every MCP config JSON in the user and project directories without the
 * enabled/trusted filter, so the management page can show and toggle disabled
 * servers too.  Malformed entries are skipped but still reported by id.
 */
async function rawConfigsIn(directory: string, scope: "user" | "project"): Promise<UserMcpConfigEntry[]> {
  let names: string[];
  try {
    names = (await readdir(directory)).filter((name) => name.endsWith(".json")).sort();
  } catch {
    return [];
  }
  const entries: UserMcpConfigEntry[] = [];
  for (const name of names) {
    try {
      const value = JSON.parse(await readFile(join(directory, name), "utf8")) as Record<string, unknown>;
      if (typeof value.id !== "string" || typeof value.command !== "string") continue;
      entries.push({
        id: value.id,
        name: typeof value.name === "string" ? value.name : value.id,
        command: value.command,
        enabled: value.enabled !== false,
        path: join(directory, name),
        scope,
      });
    } catch { /* Ignore malformed entries. */ }
  }
  return entries;
}

/** Rewrite a user MCP config file, preserving every other field. */
export async function setUserMcpConfigEnabled(entry: UserMcpConfigEntry, enabled: boolean): Promise<void> {
  const value = JSON.parse(await readFile(entry.path, "utf8")) as Record<string, unknown>;
  value.enabled = enabled;
  await atomicWriteFile(entry.path, `${JSON.stringify(value, null, 2)}\n`);
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

  /** All user/project MCP config files (enabled and disabled) for management. */
  public async listUserConfigs(root: string): Promise<UserMcpConfigEntry[]> {
    const user = await rawConfigsIn(join(homedir(), ".psyclaw", "mcp"), "user");
    const project = await rawConfigsIn(join(root, ".psyclaw", "mcp"), "project");
    const merged = new Map(user.map((entry) => [entry.path, entry]));
    for (const entry of project) merged.set(entry.path, entry);
    return [...merged.values()].sort((left, right) => left.id.localeCompare(right.id));
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
