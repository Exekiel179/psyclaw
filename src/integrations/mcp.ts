import { spawn as nodeSpawn } from "node:child_process";
import { createInterface } from "node:readline";
import type { Readable } from "node:stream";
import { sha256Text } from "../core/hash.js";
import { PSYCLAW_VERSION } from "../branding.js";
import { denyByDefault } from "./contracts.js";
import type { Approval, Integration, ToolCall, ToolDescriptor } from "./contracts.js";
import type { Effect, ToolReceipt } from "../core/contracts.js";

/** Host-side policy for one discovered tool. Server metadata never supplies this policy. */
export interface McpToolPolicy {
  /** Only an explicit `true` enables invocation. */
  enabled: boolean;
  /** Effect assigned by the host, not by the MCP server. */
  effect?: Effect;
  /** Optional host-pinned schema. Otherwise the discovered schema is checked. */
  inputSchema?: unknown;
  /** Require researcher/policy approval even for a read effect. */
  approvalRequired?: boolean;
}

export type McpToolPolicyMap = Readonly<Record<string, McpToolPolicy | boolean>>;

export interface McpServerConfig {
  id: string;
  command: string;
  args: string[];
  /** The only environment the child sees. Never merged with `process.env`. */
  env?: Record<string, string>;
  trusted: boolean;
  enabled: boolean;
  /** Host-assigned default effect for explicitly enabled tools. */
  effect?: Effect;
  /** Optional host-side ceiling. Server-reported effects are ignored. */
  effectCeiling?: Effect | readonly Effect[];
  /** Optional exact host-side effect allowlist. */
  allowedEffects?: readonly Effect[] | ReadonlySet<Effect>;
  /** Explicit tool names. Names may be bare (`search`) or qualified (`id.search`). */
  enabledTools?: readonly string[];
  /** Alias retained for configuration files and security review terminology. */
  toolAllowlist?: readonly string[];
  /** Alias for `toolAllowlist`. */
  allowedTools?: readonly string[];
  /** Generic alias for an explicit allowlist (names or policies). */
  allowlist?: readonly string[] | McpToolPolicyMap;
  /** Per-tool host policy. A boolean is shorthand for `{ enabled: boolean }`. */
  toolPolicies?: McpToolPolicyMap;
  /** Alias for `toolPolicies`. */
  tools?: readonly string[] | McpToolPolicyMap;
  /** Singular alias for `toolPolicies`. */
  toolPolicy?: McpToolPolicyMap;
  /** Explicit opt-in for a trusted, reviewed server whose discovered tools are all read-only. */
  allowAllDiscoveredTools?: boolean;
  /** Per-request timeout. Individual client methods may override it. */
  requestTimeoutMs?: number;
}

/** A narrow structural view of a spawned MCP child, injectable for tests. */
export interface McpChild {
  stdout: Readable;
  stderr: Readable;
  stdin: { write(chunk: string): void; end(): void };
  kill(): void;
  onClose(handler: (code: number | null) => void): void;
}

export type McpSpawn = (
  command: string,
  args: string[],
  options: { env?: Record<string, string> },
) => McpChild;

/**
 * The secure default: argv (never a shell) and an explicit env. The child
 * inherits nothing from `process.env`, so a provider secret in the parent
 * cannot leak into a tool subprocess unless the caller names it explicitly.
 */
const defaultSpawn: McpSpawn = (command, args, options) => {
  const child = nodeSpawn(command, args, {
    env: options.env ?? {},
    stdio: ["pipe", "pipe", "pipe"],
    shell: false,
    windowsHide: true,
  });
  return {
    stdout: child.stdout,
    stderr: child.stderr,
    stdin: { write: (chunk) => child.stdin.write(chunk), end: () => child.stdin.end() },
    kill: () => child.kill(),
    onClose: (handler) => child.on("close", handler),
  };
};

export interface McpTransport {
  send(message: unknown): void;
  onMessage(handler: (message: unknown) => void): void;
  /** Called exactly once when the transport is explicitly or externally closed. */
  onClose?(handler: () => void): void;
  close(): void;
}

/** Line-delimited JSON-RPC transport over a spawned child. */
export class StdioMcpTransport implements McpTransport {
  private readonly child: McpChild;
  private readonly handlers: ((message: unknown) => void)[] = [];
  private readonly closeHandlers: (() => void)[] = [];
  private closed = false;

  public constructor(config: McpServerConfig, spawn: McpSpawn = defaultSpawn) {
    this.child = spawn(config.command, config.args, { env: config.env ?? {} });
    createInterface({ input: this.child.stdout, crlfDelay: Infinity }).on("line", (line) => {
      const trimmed = line.trim();
      if (trimmed.length === 0) return;
      let parsed: unknown;
      try {
        parsed = JSON.parse(trimmed);
      } catch {
        // Malformed server output is ignored. The request will fail by timeout
        // and the timeout path terminates this transport.
        return;
      }
      for (const handler of this.handlers) handler(parsed);
    });
    // stderr is drained for diagnostics but never logged verbatim; a server
    // must not be able to inject log text that the host then persists.
    createInterface({ input: this.child.stderr, crlfDelay: Infinity }).on("line", () => undefined);
    this.child.onClose(() => this.markClosed());
  }

  public send(message: unknown): void {
    if (this.closed) throw new McpTransportClosedError();
    this.child.stdin.write(`${JSON.stringify(message)}\n`);
  }

  public onMessage(handler: (message: unknown) => void): void {
    this.handlers.push(handler);
  }

  public onClose(handler: () => void): void {
    if (this.closed) {
      handler();
      return;
    }
    this.closeHandlers.push(handler);
  }

  public close(): void {
    if (this.closed) return;
    this.closed = true;
    try {
      this.child.stdin.end();
    } catch {
      // The child may have already closed its pipe.
    }
    try {
      this.child.kill();
    } catch {
      // A failed kill is still represented as a closed transport.
    }
    this.notifyClosed();
  }

  private markClosed(): void {
    if (this.closed) return;
    this.closed = true;
    this.notifyClosed();
  }

  private notifyClosed(): void {
    const handlers = this.closeHandlers.splice(0);
    for (const handler of handlers) handler();
  }
}

export class McpTimeoutError extends Error {
  public readonly code = "mcp.timeout" as const;

  public constructor(public readonly method: string) {
    super("MCP request timed out");
    this.name = "McpTimeoutError";
  }
}

export class McpTransportClosedError extends Error {
  public readonly code = "mcp.transport-closed" as const;

  public constructor() {
    super("MCP transport closed");
    this.name = "McpTransportClosedError";
  }
}

class McpRemoteError extends Error {
  public readonly code = "mcp.remote-error" as const;

  public constructor() {
    // Never copy the server's error text. It can contain credentials or data.
    super("MCP server returned an error");
    this.name = "McpRemoteError";
  }
}

export interface McpTool {
  name: string;
  description?: string;
  inputSchema?: unknown;
}

interface PendingRequest {
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
  timer: ReturnType<typeof setTimeout>;
}

/** Minimal JSON-RPC client for the MCP initialize/list/call sequence. */
export class McpClient {
  private nextId = 1;
  private readonly pending = new Map<number, PendingRequest>();
  private closed = false;

  public constructor(private readonly transport: McpTransport) {
    transport.onMessage((message) => this.handle(message));
    transport.onClose?.(() => {
      this.closed = true;
      this.rejectPending(new McpTransportClosedError());
    });
  }

  public initialize(clientInfo: { name: string; version: string }, timeoutMs = 10000): Promise<unknown> {
    return this.request("initialize", {
      protocolVersion: "2024-11-05",
      capabilities: {},
      clientInfo,
    }, timeoutMs);
  }

  public initialized(): void {
    this.transport.send({ jsonrpc: "2.0", method: "notifications/initialized" });
  }

  public listTools(timeoutMs = 10000): Promise<McpTool[]> {
    return this.request("tools/list", undefined, timeoutMs).then((result) => {
      const tools = (result as { tools?: unknown } | undefined)?.tools;
      if (!Array.isArray(tools)) return [];
      // A malformed descriptor makes the discovery set ambiguous. Do not
      // silently drop it and expose a partially trusted server.
      if (tools.some((tool) => !isMcpTool(tool))) throw new Error("invalid MCP tool descriptor");
      return tools as McpTool[];
    });
  }

  public callTool(name: string, args: unknown, timeoutMs = 30000): Promise<unknown> {
    return this.request("tools/call", { name, arguments: args }, timeoutMs);
  }

  public close(): void {
    if (this.closed) return;
    this.closed = true;
    try {
      this.transport.close();
    } catch {
      // Treat an already-dead transport as closed.
    }
    this.rejectPending(new McpTransportClosedError());
  }

  private request(method: string, params: unknown, timeoutMs: number): Promise<unknown> {
    if (this.closed) return Promise.reject(new McpTransportClosedError());
    const timeout = Number.isFinite(timeoutMs) && timeoutMs > 0 ? Math.floor(timeoutMs) : 10000;
    const id = this.nextId;
    this.nextId += 1;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        const entry = this.pending.get(id);
        if (!entry) return;
        this.pending.delete(id);
        clearTimeout(entry.timer);
        // A timed-out side effect is indeterminate. Closing the transport is
        // mandatory so a late response/child cannot be mistaken for a retry.
        try {
          this.transport.close();
        } catch {
          // The request is still rejected below; a broken close implementation
          // must not leave the caller hanging.
        }
        reject(new McpTimeoutError(method));
      }, timeout);
      this.pending.set(id, { resolve, reject, timer });
      try {
        this.transport.send({
          jsonrpc: "2.0",
          id,
          method,
          ...(params === undefined ? {} : { params }),
        });
      } catch {
        const entry = this.pending.get(id);
        if (entry) {
          this.pending.delete(id);
          clearTimeout(entry.timer);
        }
        reject(new McpTransportClosedError());
      }
    });
  }

  private rejectPending(error: Error): void {
    const entries = [...this.pending.values()];
    this.pending.clear();
    for (const entry of entries) {
      clearTimeout(entry.timer);
      entry.reject(error);
    }
  }

  private handle(message: unknown): void {
    if (!isRecord(message)) return;
    const id = message.id;
    if (typeof id !== "number" || !this.pending.has(id)) return;
    const entry = this.pending.get(id);
    if (!entry) return;
    this.pending.delete(id);
    clearTimeout(entry.timer);
    if (message.error !== undefined && message.error !== null) {
      entry.reject(new McpRemoteError());
      return;
    }
    entry.resolve(message.result);
  }
}

interface ResolvedToolPolicy {
  enabled: boolean;
  effect: Effect;
  inputSchema?: unknown;
  approvalRequired: boolean;
}

interface CachedTool {
  name: string;
  schema: unknown;
  policy?: ResolvedToolPolicy;
  descriptor: ToolDescriptor;
}

/** A real stdio MCP integration behind the shared `Integration` contract. */
export class StdioMcpIntegration implements Integration {
  private transport: McpTransport | undefined;
  private client: McpClient | undefined;
  private initialized = false;
  private discoveryAttempted = false;
  private readonly discovered = new Map<string, CachedTool>();
  /** Reservations survive a failed/timeout call to prevent blind replay. */
  private readonly idempotency = new Map<string, string>();
  private readonly defaultEffect: Effect;

  public constructor(
    private readonly config: McpServerConfig,
    private readonly spawn: McpSpawn = defaultSpawn,
  ) {
    // Omitted host policy is read-only. A caller must opt into network/write
    // effects in the host config and still provide approval/idempotency.
    this.defaultEffect = isEffect(config.effect) ? config.effect : "read";
  }

  public async list(): Promise<readonly ToolDescriptor[]> {
    if (!this.config.enabled || !this.config.trusted) return [];
    if (this.discoveryAttempted) return this.descriptorSnapshot();
    try {
      const client = await this.connectAndInitialize();
      const tools = await client.listTools(this.timeoutFor("list"));
      const seen = new Set<string>();
      const next = new Map<string, CachedTool>();
      for (const tool of tools) {
        if (!isSafeToolName(tool.name) || seen.has(tool.name)) {
          // Duplicate/invalid names make the discovery set ambiguous. Do not
          // expose a partially trusted set.
          this.resetConnection(true);
          return [];
        }
        seen.add(tool.name);
        const policy = resolvePolicy(this.config, tool.name, this.defaultEffect);
        const effect = policy?.effect ?? this.defaultEffect;
        const allowed = policy !== undefined && policy.enabled && effectAllowed(this.config, effect);
        const resolved = policy === undefined
          ? undefined
          : {
              // Keep explicit host enablement separate from the effect
              // ceiling. Invocation can then report the precise blocked
              // reason instead of conflating it with an unknown tool.
              enabled: policy.enabled,
              effect,
              ...(policy.inputSchema !== undefined ? { inputSchema: policy.inputSchema } : {}),
              approvalRequired: policy.approvalRequired === true,
            } satisfies ResolvedToolPolicy;
        const descriptor: ToolDescriptor = {
          id: `${this.config.id}.${tool.name}`,
          description: typeof tool.description === "string" ? tool.description.slice(0, 1000) : "",
          // This effect is always host-assigned. Any server-provided effect
          // field is intentionally not represented in McpTool.
          effect,
          source: this.config.id,
          trust: "approved",
          enabled: allowed,
        };
        next.set(tool.name, {
          name: tool.name,
          schema: tool.inputSchema,
          ...(resolved === undefined ? {} : { policy: resolved }),
          descriptor,
        });
      }
      this.discovered.clear();
      for (const [name, cached] of next) this.discovered.set(name, cached);
      this.discoveryAttempted = true;
      return this.descriptorSnapshot();
    } catch {
      this.resetConnection(true);
      return [];
    }
  }

  public async health(): Promise<{ ok: boolean; reason?: string }> {
    if (!this.config.enabled) return { ok: false, reason: "server disabled" };
    if (!this.config.trusted) return { ok: false, reason: "server not trusted" };
    try {
      await this.connectAndInitialize();
      return { ok: true };
    } catch (error) {
      this.resetConnection(true);
      return { ok: false, reason: failureCode(error) };
    }
  }

  public async invoke(call: ToolCall, approval: Approval): Promise<ToolReceipt> {
    const fallback = this.defaultEffect;
    const safeCall = sanitizeCall(call);
    if (!isValidCallEnvelope(call)) {
      return denyByDefault(safeCall, fallback, "mcp.invalid-call", "mcp.invalid-call");
    }
    if (!this.config.enabled || !this.config.trusted) {
      return denyByDefault(safeCall, fallback, "mcp.untrusted", "mcp.untrusted");
    }
    if (!isValidApproval(approval)) {
      return denyByDefault(safeCall, fallback, "mcp.invalid-approval", "mcp.invalid-approval");
    }
    if (!this.discoveryAttempted) {
      return denyByDefault(safeCall, fallback, "mcp.tool-not-discovered", "mcp.tool-not-discovered");
    }
    const parsed = parseToolId(call.tool, this.config.id);
    if (parsed === undefined) {
      return denyByDefault(safeCall, fallback, "mcp.source-mismatch", "mcp.source-mismatch");
    }
    const cached = this.discovered.get(parsed);
    if (cached === undefined) {
      return denyByDefault(safeCall, fallback, "mcp.tool-not-discovered", "mcp.tool-not-discovered");
    }
    const policy = cached.policy;
    if (policy === undefined || !policy.enabled || cached.descriptor.source !== this.config.id) {
      return denyByDefault(safeCall, cached.descriptor.effect, "mcp.tool-not-enabled", "mcp.tool-not-enabled");
    }
    const requested = (call as ToolCall & { effect?: unknown }).effect;
    if (requested !== undefined && requested !== policy.effect) {
      return denyByDefault(safeCall, policy.effect, "mcp.effect-mismatch", "mcp.effect-mismatch");
    }
    const requestedSource = (call as ToolCall & { source?: unknown }).source;
    if (requestedSource !== undefined && requestedSource !== this.config.id) {
      return denyByDefault(safeCall, policy.effect, "mcp.source-mismatch", "mcp.source-mismatch");
    }
    if (!effectAllowed(this.config, policy.effect)) {
      return denyByDefault(safeCall, policy.effect, "mcp.effect-not-allowed", "mcp.effect-not-allowed");
    }
    if (approval.decision === "denied") {
      return denyByDefault(safeCall, policy.effect, "mcp.approval-required", "mcp.approval-required");
    }
    if ((policy.effect !== "read" || policy.approvalRequired) && approval.decision !== "approved") {
      return denyByDefault(safeCall, policy.effect, "mcp.approval-required", "mcp.approval-required");
    }
    const schema = policy.inputSchema ?? cached.schema;
    if (!validateToolInput(schema, call.input)) {
      return denyByDefault(safeCall, policy.effect, "mcp.invalid-input", "mcp.invalid-input");
    }

    const suppliedIdempotencyKey = validIdempotencyKey(call.idempotencyKey) ? call.idempotencyKey : undefined;
    let idempotencyKey: string | undefined = suppliedIdempotencyKey;
    if (policy.effect !== "read") {
      if (idempotencyKey === undefined) {
        return denyByDefault(safeCall, policy.effect, "mcp.idempotency-required", "mcp.idempotency-required");
      }
      let inputCanonical: string | undefined;
      try {
        inputCanonical = canonicalJson(call.input);
      } catch {
        inputCanonical = undefined;
      }
      if (inputCanonical === undefined) {
        return denyByDefault(safeCall, policy.effect, "mcp.invalid-input", "mcp.invalid-input");
      }
      const fingerprint = sha256Text(`${call.tool}\n${policy.effect}\n${inputCanonical}`);
      const previous = this.idempotency.get(idempotencyKey);
      if (previous !== undefined) {
        return denyByDefault(safeCall, policy.effect,
          previous === fingerprint ? "mcp.duplicate-idempotency" : "mcp.idempotency-conflict",
          previous === fingerprint ? "mcp.duplicate-idempotency" : "mcp.idempotency-conflict");
      }
      // Reserve before crossing the transport boundary. The reservation is
      // intentionally retained after errors and timeouts.
      this.idempotency.set(idempotencyKey, fingerprint);
    }

    try {
      const client = await this.connectAndInitialize();
      const result = await client.callTool(parsed, call.input, this.timeoutFor("call"));
      const now = new Date().toISOString();
      const resultText = canonicalJson(result) ?? "<invalid-result>";
      return {
        schemaVersion: "psyclaw/tool-receipt/v1",
        runId: safeCall.runId,
        taskId: safeCall.taskId,
        tool: safeCall.tool,
        effect: policy.effect,
        approval: approval.decision,
        ...(idempotencyKey === undefined ? {} : { idempotencyKey }),
        ok: true,
        resultHash: sha256Text(resultText),
        startedAt: now,
        finishedAt: now,
      };
    } catch (error) {
      // A disconnect/timeout/error invalidates the discovery session. Never
      // retry automatically: a side effect may have happened remotely.
      this.resetConnection(true);
      return denyByDefault(safeCall, policy.effect, failureCode(error), failureCode(error));
    }
  }

  public close(): void {
    this.resetConnection(true);
  }

  private descriptorSnapshot(): readonly ToolDescriptor[] {
    return [...this.discovered.values()].map((entry) => ({ ...entry.descriptor }));
  }

  private timeoutFor(kind: "list" | "call"): number {
    const configured = this.config.requestTimeoutMs;
    if (Number.isFinite(configured) && configured !== undefined && configured > 0) return Math.floor(configured);
    return kind === "list" ? 10000 : 30000;
  }

  private async connectAndInitialize(): Promise<McpClient> {
    if (this.client === undefined) {
      this.transport = new StdioMcpTransport(this.config, this.spawn);
      this.client = new McpClient(this.transport);
      this.initialized = false;
    }
    if (!this.initialized) {
      await this.client.initialize({ name: "psyclaw", version: PSYCLAW_VERSION }, this.timeoutFor("list"));
      this.client.initialized();
      this.initialized = true;
    }
    return this.client;
  }

  private resetConnection(invalidateDiscovery: boolean): void {
    try {
      this.client?.close();
    } catch {
      // The boundary remains invalidated even if a custom transport throws.
    }
    this.client = undefined;
    this.transport = undefined;
    this.initialized = false;
    if (invalidateDiscovery) {
      this.discoveryAttempted = false;
      this.discovered.clear();
    }
  }
}

/**
 * Deliberately lazy MCP boundary retained for M1/M2 compatibility. Discovery
 * is data-only; invocation is denied until `StdioMcpIntegration` is approved.
 */
export class LazyMcpIntegration implements Integration {
  public constructor(private readonly config: McpServerConfig) {}

  async list(): Promise<readonly ToolDescriptor[]> {
    if (!this.config.enabled || !this.config.trusted) return [];
    return [];
  }

  async health(): Promise<{ ok: boolean; reason?: string }> {
    if (!this.config.enabled) return { ok: false, reason: "server disabled" };
    if (!this.config.trusted) return { ok: false, reason: "server not trusted" };
    return { ok: false, reason: "stdio adapter not enabled in M1" };
  }

  async invoke(call: ToolCall, approval: Approval): Promise<ToolReceipt> {
    const approved = approval.decision === "approved";
    return denyByDefault(
      sanitizeCall(call),
      "network",
      approved ? "mcp.transport-disabled" : "mcp.approval-required",
      approved ? "mcp.transport-disabled" : "mcp.approval-required",
    );
  }
}

const EFFECTS: readonly Effect[] = ["read", "write", "network", "destructive"];

function isEffect(value: unknown): value is Effect {
  return typeof value === "string" && (EFFECTS as readonly string[]).includes(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isMcpTool(value: unknown): value is McpTool {
  if (!isRecord(value) || typeof value.name !== "string") return false;
  if (value.description !== undefined && typeof value.description !== "string") return false;
  return true;
}

function isSafeToolName(value: string): boolean {
  return value.length > 0 && value.length <= 256 && !/[\u0000-\u001f\u007f]/.test(value);
}

function parseToolId(tool: string, serverId: string): string | undefined {
  if (!isSafeToolName(tool)) return undefined;
  const prefix = `${serverId}.`;
  if (!tool.startsWith(prefix)) return undefined;
  const name = tool.slice(prefix.length);
  return isSafeToolName(name) ? name : undefined;
}

function validIdempotencyKey(value: unknown): value is string {
  return typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/.test(value);
}

function isValidApproval(value: unknown): value is Approval {
  if (!isRecord(value)) return false;
  const decision = value.decision;
  const actor = value.actor;
  const reason = value.reason;
  return (decision === "not-needed" || decision === "approved" || decision === "denied") &&
    (actor === "policy" || actor === "researcher") &&
    typeof reason === "string" && reason.length <= 2000;
}

function isValidCallEnvelope(value: unknown): value is ToolCall {
  return isRecord(value) &&
    typeof value.runId === "string" && value.runId.length > 0 && value.runId.length <= 256 &&
    typeof value.taskId === "string" && value.taskId.length > 0 && value.taskId.length <= 256 &&
    typeof value.tool === "string";
}

function sanitizeCall(call: ToolCall | unknown): ToolCall {
  const record = isRecord(call) ? call : {};
  const rawTool = typeof record.tool === "string" ? record.tool : "";
  const tool = isSafeToolName(rawTool) ? rawTool : "mcp.invalid-tool";
  const idempotencyKey = validIdempotencyKey(record.idempotencyKey) ? record.idempotencyKey : undefined;
  return {
    runId: typeof record.runId === "string" && record.runId.length <= 256 ? record.runId : "mcp.invalid-run",
    taskId: typeof record.taskId === "string" && record.taskId.length <= 256 ? record.taskId : "mcp.invalid-task",
    tool,
    input: record.input,
    ...(idempotencyKey === undefined ? {} : { idempotencyKey }),
  };
}

function resolvePolicy(
  config: McpServerConfig,
  name: string,
  defaultEffect: Effect,
): ResolvedToolPolicy | undefined {
  const canonical = `${config.id}.${name}`;
  const maps: readonly (McpToolPolicyMap | undefined)[] = [
    config.toolPolicies,
    config.toolPolicy,
    isPolicyMap(config.tools) ? config.tools : undefined,
    isPolicyMap(config.allowlist) ? config.allowlist : undefined,
  ];
  for (const map of maps) {
    if (map === undefined) continue;
    const entry = map[name] ?? map[canonical];
    if (entry === undefined) continue;
    if (typeof entry === "boolean") {
      return { enabled: entry, effect: defaultEffect, approvalRequired: false };
    }
    if (!isRecord(entry)) return undefined;
    const enabled = entry.enabled === true;
    const effect = isEffect(entry.effect) ? entry.effect : defaultEffect;
    const inputSchema = Object.prototype.hasOwnProperty.call(entry, "inputSchema") ? entry.inputSchema : undefined;
    return {
      enabled,
      effect,
      ...(inputSchema === undefined ? {} : { inputSchema }),
      approvalRequired: entry.approvalRequired === true,
    };
  }

  const explicitLists: readonly (readonly string[] | undefined)[] = [
    config.enabledTools,
    config.toolAllowlist,
    config.allowedTools,
    Array.isArray(config.tools) ? config.tools : undefined,
    Array.isArray(config.allowlist) ? config.allowlist : undefined,
  ];
  const hasList = explicitLists.some((list) => list !== undefined);
  if (hasList) {
    const enabled = explicitLists.some((list) => list?.some((entry) => entry === name || entry === canonical));
    return enabled ? { enabled: true, effect: defaultEffect, approvalRequired: false } : undefined;
  }
  if (config.allowAllDiscoveredTools === true && defaultEffect === "read" && effectAllowed(config, "read")) {
    return { enabled: true, effect: defaultEffect, approvalRequired: false };
  }
  return undefined;
}

function isPolicyMap(value: McpServerConfig["tools"]): value is McpToolPolicyMap {
  return isRecord(value);
}

function effectAllowed(config: McpServerConfig, effect: Effect): boolean {
  if (!isEffect(effect)) return false;
  if (config.allowedEffects !== undefined) {
    const configured = config.allowedEffects instanceof Set
      ? [...config.allowedEffects]
      : config.allowedEffects;
    if (!Array.isArray(configured) || configured.some((item) => !isEffect(item))) return false;
    return configured.includes(effect);
  }
  if (config.effectCeiling !== undefined) {
    const ceiling = config.effectCeiling;
    if (Array.isArray(ceiling)) {
      return ceiling.length > 0 && ceiling.every((item) => isEffect(item)) && ceiling.includes(effect);
    }
    if (!isEffect(ceiling)) return false;
    const allowed: readonly Effect[] = ceiling === "read"
      ? ["read"]
      : ceiling === "write"
        ? ["read", "write"]
        : ceiling === "network"
          ? ["read", "network"]
          : EFFECTS;
    return allowed.includes(effect);
  }
  return true;
}

function failureCode(error: unknown): string {
  if (error instanceof McpTimeoutError) return error.code;
  if (error instanceof McpTransportClosedError) return error.code;
  if (error instanceof McpRemoteError) return error.code;
  return "mcp.call-failed";
}

function canonicalJson(value: unknown, seen = new Set<object>(), depth = 0): string | undefined {
  if (depth > 40) return undefined;
  if (value === null) return "null";
  if (typeof value === "string") return JSON.stringify(value);
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return Number.isFinite(value) ? JSON.stringify(value) : undefined;
  if (typeof value !== "object") return undefined;
  if (seen.has(value)) return undefined;
  seen.add(value);
  let result: string | undefined;
  if (Array.isArray(value)) {
    const parts: string[] = [];
    for (const item of value) {
      const encoded = canonicalJson(item, seen, depth + 1);
      if (encoded === undefined) return undefined;
      parts.push(encoded);
    }
    result = `[${parts.join(",")}]`;
  } else {
    const record = value as Record<string, unknown>;
    const parts: string[] = [];
    for (const key of Object.keys(record).sort()) {
      const encoded = canonicalJson(record[key], seen, depth + 1);
      if (encoded === undefined) return undefined;
      parts.push(`${JSON.stringify(key)}:${encoded}`);
    }
    result = `{${parts.join(",")}}`;
  }
  seen.delete(value);
  return result;
}

function validateToolInput(schema: unknown, input: unknown): boolean {
  try {
    if (canonicalJson(input) === undefined) return false;
    const schemaText = canonicalJson(schema);
    if (schemaText === undefined || schemaText.length > 65_536) return false;
    return validateSchema(schema, input, 0, new Set<object>());
  } catch {
    // Accessors/proxies and cyclic values are untrusted caller input.
    return false;
  }
}

/** A bounded JSON-Schema subset sufficient for MCP tool arguments. */
function validateSchema(schema: unknown, value: unknown, depth: number, seen: Set<object>): boolean {
  if (!isRecord(schema) || depth > 32) return false;
  if (seen.has(schema)) return false;
  seen.add(schema);
  try {
    for (const keyword of ["allOf", "anyOf", "oneOf"] as const) {
      if (schema[keyword] !== undefined) {
        if (!Array.isArray(schema[keyword]) || schema[keyword].some((item) => !isRecord(item))) return false;
        const matches = schema[keyword].filter((item) => validateSchema(item, value, depth + 1, seen)).length;
        if (keyword === "allOf" && matches !== schema[keyword].length) return false;
        if (keyword === "anyOf" && matches < 1) return false;
        if (keyword === "oneOf" && matches !== 1) return false;
      }
    }
    if (schema.enum !== undefined) {
      if (!Array.isArray(schema.enum) || !schema.enum.some((entry) => canonicalJson(entry) === canonicalJson(value))) return false;
    }
    if (Object.prototype.hasOwnProperty.call(schema, "const") && canonicalJson(schema.const) !== canonicalJson(value)) return false;
    if (schema.type !== undefined) {
      const types = Array.isArray(schema.type) ? schema.type : [schema.type];
      if (!types.every((item) => typeof item === "string")) return false;
      if (!types.some((type) => typeMatches(type, value))) return false;
    }
    if (typeof value === "string") {
      if (schema.minLength !== undefined && (!isFiniteInteger(schema.minLength) || value.length < schema.minLength)) return false;
      if (schema.maxLength !== undefined && (!isFiniteInteger(schema.maxLength) || value.length > schema.maxLength)) return false;
      if (schema.pattern !== undefined) {
        if (typeof schema.pattern !== "string") return false;
        if (schema.pattern.length > 512) return false;
        try {
          if (!new RegExp(schema.pattern).test(value)) return false;
        } catch {
          return false;
        }
      }
    }
    if (typeof value === "number") {
      if (schema.minimum !== undefined && (typeof schema.minimum !== "number" || value < schema.minimum)) return false;
      if (schema.maximum !== undefined && (typeof schema.maximum !== "number" || value > schema.maximum)) return false;
    }
    if (Array.isArray(value)) {
      if (schema.minItems !== undefined && (!isFiniteInteger(schema.minItems) || value.length < schema.minItems)) return false;
      if (schema.maxItems !== undefined && (!isFiniteInteger(schema.maxItems) || value.length > schema.maxItems)) return false;
      if (schema.items !== undefined) {
        if (!isRecord(schema.items) || !value.every((item) => validateSchema(schema.items, item, depth + 1, seen))) return false;
      }
    }
    if (isRecord(value)) {
      if (schema.required !== undefined) {
        if (!Array.isArray(schema.required) || schema.required.some((item) => typeof item !== "string")) return false;
        if (schema.required.some((key) => !Object.prototype.hasOwnProperty.call(value, key))) return false;
      }
      let properties: Record<string, unknown> = {};
      if (schema.properties !== undefined) {
        if (!isRecord(schema.properties)) return false;
        if (Object.keys(schema.properties).length > 256) return false;
        properties = schema.properties;
        for (const [key, child] of Object.entries(properties)) {
          if (Object.prototype.hasOwnProperty.call(value, key) && !validateSchema(child, value[key], depth + 1, seen)) return false;
        }
      }
      if (schema.additionalProperties === false) {
        if (Object.keys(value).some((key) => !Object.prototype.hasOwnProperty.call(properties, key))) return false;
      } else if (isRecord(schema.additionalProperties)) {
        for (const key of Object.keys(value)) {
          if (!Object.prototype.hasOwnProperty.call(properties, key) && !validateSchema(schema.additionalProperties, value[key], depth + 1, seen)) return false;
        }
      } else if (schema.additionalProperties !== undefined && schema.additionalProperties !== true) {
        return false;
      }
    }
    return true;
  } finally {
    seen.delete(schema);
  }
}

function typeMatches(type: string, value: unknown): boolean {
  switch (type) {
    case "null": return value === null;
    case "boolean": return typeof value === "boolean";
    case "object": return isRecord(value);
    case "array": return Array.isArray(value);
    case "string": return typeof value === "string";
    case "number": return typeof value === "number" && Number.isFinite(value);
    case "integer": return typeof value === "number" && Number.isInteger(value);
    default: return false;
  }
}

function isFiniteInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= 1_000_000;
}
