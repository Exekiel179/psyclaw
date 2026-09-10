import { getAgentDir } from "@earendil-works/pi-coding-agent";
import { execFile } from "node:child_process";
import { mkdir, readFile, rename, rm, stat, writeFile } from "node:fs/promises";
import { basename, join } from "node:path";
import { dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { randomUUID } from "node:crypto";
import { DEFAULT_PRICING, PROVIDER_PRICING } from "./core/pricing.js";

export interface ProviderPreset {
  id: string;
  name: string;
  baseUrl: string;
  api: "openai-completions" | "anthropic-messages";
  apiKeyEnv: string;
  models: readonly { id: string; name: string; reasoning?: boolean }[];
}

/**
 * Generic, provider-neutral presets. None of these embed a literal API key:
 * the `apiKey` is written as an environment-variable reference (`$ENV`), so
 * the user supplies the secret in their shell environment, never on disk.
 */
export const PROVIDER_PRESETS: readonly ProviderPreset[] = [
  {
    id: "google",
    name: "Google Gemini",
    baseUrl: "https://generativelanguage.googleapis.com/v1beta/openai",
    api: "openai-completions",
    apiKeyEnv: "GEMINI_API_KEY",
    models: [
      { id: "gemini-2.5-pro", name: "Gemini 2.5 Pro", reasoning: true },
      { id: "gemini-2.5-flash", name: "Gemini 2.5 Flash" },
    ],
  },
  {
    id: "deepseek",
    name: "DeepSeek",
    baseUrl: "https://api.deepseek.com",
    api: "openai-completions",
    apiKeyEnv: "DEEPSEEK_API_KEY",
    models: [
      { id: "deepseek-v4-flash", name: "DeepSeek V4 Flash" },
      { id: "deepseek-v4-pro", name: "DeepSeek V4 Pro", reasoning: true },
    ],
  },
  {
    id: "openai",
    name: "OpenAI",
    baseUrl: "https://api.openai.com/v1",
    api: "openai-completions",
    apiKeyEnv: "OPENAI_API_KEY",
    models: [
      { id: "gpt-5.5", name: "GPT-5.5" },
      { id: "gpt-5.5-pro", name: "GPT-5.5 Pro", reasoning: true },
    ],
  },
  {
    id: "opencode-go",
    name: "OpenCode Go 订阅",
    baseUrl: "https://opencode.ai/zen/go/v1",
    api: "openai-completions",
    apiKeyEnv: "OPENCODE_API_KEY",
    models: [
      { id: "deepseek-v4-flash", name: "DeepSeek V4 Flash", reasoning: true },
      { id: "deepseek-v4-pro", name: "DeepSeek V4 Pro", reasoning: true },
      { id: "glm-5.1", name: "GLM-5.1", reasoning: true },
    ],
  },
  {
    id: "anthropic",
    name: "Anthropic",
    baseUrl: "https://api.anthropic.com",
    api: "anthropic-messages",
    apiKeyEnv: "ANTHROPIC_API_KEY",
    models: [
      { id: "claude-sonnet-4-6", name: "Claude Sonnet 4.6" },
      { id: "claude-opus-4-8", name: "Claude Opus 4.8", reasoning: true },
    ],
  },
  {
    id: "qwen",
    name: "通义千问",
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode",
    api: "openai-completions",
    apiKeyEnv: "DASHSCOPE_API_KEY",
    models: [
      { id: "qwen3.6-plus", name: "Qwen 3.6 Plus" },
      { id: "qwen3.7-max", name: "Qwen 3.7 Max", reasoning: true },
      { id: "qwen3.6-flash", name: "Qwen 3.6 Flash" },
    ],
  },
  {
    id: "zhipu",
    name: "智谱 GLM",
    baseUrl: "https://open.bigmodel.cn/api/paas/v4",
    api: "openai-completions",
    apiKeyEnv: "ZHIPU_API_KEY",
    models: [
      { id: "glm-5", name: "GLM-5", reasoning: true },
      { id: "glm-5.1", name: "GLM-5.1", reasoning: true },
      { id: "glm-5-turbo", name: "GLM-5 Turbo" },
    ],
  },
  {
    id: "moonshot",
    name: "月之暗面 Kimi",
    baseUrl: "https://api.moonshot.cn/v1",
    api: "openai-completions",
    apiKeyEnv: "MOONSHOT_API_KEY",
    models: [
      { id: "kimi-k2.6", name: "Kimi K2.6", reasoning: true },
      { id: "kimi-k2.5", name: "Kimi K2.5" },
    ],
  },
  {
    id: "ollama",
    name: "Ollama（本地）",
    baseUrl: "http://localhost:11434/v1",
    api: "openai-completions",
    apiKeyEnv: "OLLAMA_API_KEY",
    models: [
      { id: "qwen3:8b", name: "Qwen3 8B" },
      { id: "qwen3:14b", name: "Qwen3 14B" },
      { id: "deepseek-r1:8b", name: "DeepSeek R1 8B", reasoning: true },
    ],
  },
  {
    id: "custom",
    name: "自定义 OpenAI 兼容接口",
    baseUrl: "",
    api: "openai-completions",
    apiKeyEnv: "PSYCLAW_CUSTOM_API_KEY",
    models: [],
  },
];

function providerToJson(preset: ProviderPreset): Record<string, unknown> {
  const pricing = PROVIDER_PRICING[preset.id] ?? DEFAULT_PRICING;
  return {
    baseUrl: preset.baseUrl,
    api: preset.api,
    apiKey: `$${preset.apiKeyEnv}`,
    models: preset.models.map((model) => ({
      id: model.id,
      name: model.name,
      ...(model.reasoning === undefined ? {} : { reasoning: model.reasoning }),
      cost: { ...pricing },
    })),
  };
}

export interface SetupOptions {
  agentDir?: string;
  /** Provider ids to write; defaults to all presets (the generic guide). */
  providers?: readonly string[];
}

export interface SetupResult {
  path: string;
  providers: string[];
}

export interface ProviderConfigInput {
  id: string;
  name: string;
  baseUrl: string;
  api: "openai-completions" | "anthropic-messages";
  apiKeyEnv: string;
  models: readonly { id: string; name?: string; reasoning?: boolean }[];
  apiKey?: string;
}

export type CredentialSource = "process-env" | "macos-launchctl" | "auth-store" | "missing";

export function missingApiKeyUserMessage(apiKeyEnv: string): string {
  assertApiKeyEnv(apiKeyEnv);
  return `未找到 ${apiKeyEnv}；请输入 API Key 后再继续`;
}

export function missingProviderCredentialMessage(providerId: string): string {
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(providerId)) throw new Error("Invalid provider id");
  return `未找到 ${providerId} 的可用凭据；请重新运行 /provider 并输入 API Key`;
}

export type ProviderKeyPromptDecision =
  | { kind: "cancel" }
  | { kind: "need-key"; message: string }
  | { kind: "proceed"; apiKey?: string };

/**
 * Empty key submission keeps an existing credential. An empty submission with
 * no credential is expected setup UX, not a thrown failure.
 */
export function decideProviderKeyPrompt(
  submitted: string | undefined,
  credential: CredentialSource,
  apiKeyEnv: string,
): ProviderKeyPromptDecision {
  if (submitted === undefined) return { kind: "cancel" };
  if (!submitted && credential === "missing") {
    return { kind: "need-key", message: missingApiKeyUserMessage(apiKeyEnv) };
  }
  return submitted ? { kind: "proceed", apiKey: submitted } : { kind: "proceed" };
}

// These providers are implemented by Pi itself. PsyClaw only exposes their
// credentials and selection; writing a simplified models.json entry would
// discard Pi's native model/API metadata (some providers expose more than one
// API protocol).
const PI_NATIVE_PROVIDERS = new Set(["opencode-go"]);

function execFileText(file: string, args: readonly string[]): Promise<string | undefined> {
  return new Promise((resolve) => {
    execFile(file, [...args], { encoding: "utf8", timeout: 3_000, maxBuffer: 64 * 1024, windowsHide: true }, (error, stdout) => {
      const value = error ? "" : stdout.trim();
      resolve(value || undefined);
    });
  });
}

function assertApiKeyEnv(apiKeyEnv: string): void {
  if (!/^[A-Z][A-Z0-9_]{0,127}$/.test(apiKeyEnv)) throw new Error("Invalid API key environment name");
}

export async function readMacOsLaunchctlCredential(apiKeyEnv: string): Promise<string | undefined> {
  assertApiKeyEnv(apiKeyEnv);
  if (process.platform !== "darwin") return undefined;
  return execFileText("/bin/launchctl", ["getenv", apiKeyEnv]);
}

/** Explicit import only: a login shell may execute user-controlled profile code. */
export async function readMacOsLoginShellCredential(apiKeyEnv: string): Promise<string | undefined> {
  assertApiKeyEnv(apiKeyEnv);
  if (process.platform !== "darwin") return undefined;
  const shell = process.env.SHELL?.trim() || "/bin/zsh";
  if (shell !== "/bin/zsh" && shell !== "/bin/bash") throw new Error("Only /bin/zsh and /bin/bash login shells are supported");
  const nonce = randomUUID().replaceAll("-", "");
  const start = `__PSYCLAW_KEY_${nonce}__`;
  const end = `__PSYCLAW_END_${nonce}__`;
  const output = await execFileText(shell, ["-lc", `command printf '${start}%s${end}' "\${${apiKeyEnv}-}"`]);
  if (!output) return undefined;
  if (!output.startsWith(start) || !output.endsWith(end)
    || output.indexOf(start, start.length) >= 0 || output.indexOf(end) !== output.length - end.length) {
    throw new Error("Login shell produced unexpected output; import was refused");
  }
  const value = output.slice(start.length, -end.length);
  if (!value || /[\u0000-\u001f\u007f]/u.test(value)) throw new Error("Login shell credential is empty or contains control characters");
  return value;
}

async function hasStoredCredential(providerId: string, agentDir: string): Promise<boolean> {
  try {
    const entry = fileURLToPath(import.meta.resolve("@earendil-works/pi-coding-agent"));
    const { readStoredCredential } = await import(pathToFileURL(join(dirname(entry), "core", "auth-storage.js")).href);
    return readStoredCredential(providerId, join(agentDir, "auth.json")) !== undefined;
  } catch {
    return false;
  }
}

/** Detect a provider credential without returning or logging its value. */
export async function providerCredentialSource(
  preset: Pick<ProviderPreset, "id" | "apiKeyEnv">,
  options: { agentDir?: string; platform?: NodeJS.Platform } = {},
): Promise<CredentialSource> {
  assertApiKeyEnv(preset.apiKeyEnv);
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(preset.id)) throw new Error("Invalid provider id");
  const processValue = process.env[preset.apiKeyEnv]?.trim();
  if (processValue) return "process-env";
  const platform = options.platform ?? process.platform;
  if (platform === "darwin") {
    const launchctlValue = await execFileText("/bin/launchctl", ["getenv", preset.apiKeyEnv]);
    if (launchctlValue) return "macos-launchctl";
  }
  return await hasStoredCredential(preset.id, options.agentDir ?? getAgentDir()) ? "auth-store" : "missing";
}

const modelWriteQueues = new Map<string, Promise<unknown>>();
const STALE_MODELS_LOCK_MS = 30_000;

async function withModelsLock<T>(modelsPath: string, operation: () => Promise<T>): Promise<T> {
  const previous = modelWriteQueues.get(modelsPath) ?? Promise.resolve();
  const queued = previous.catch(() => undefined).then(async () => {
    const lockPath = `${modelsPath}.psyclaw.lock`;
    const deadline = Date.now() + 10_000;
    while (true) {
      try { await mkdir(lockPath); break; }
      catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
        const ageMs = await stat(lockPath).then((value) => Date.now() - value.mtimeMs).catch(() => 0);
        if (ageMs > STALE_MODELS_LOCK_MS) {
          const stalePath = `${lockPath}.stale.${process.pid}.${randomUUID()}`;
          try {
            await rename(lockPath, stalePath);
            await rm(stalePath, { recursive: true, force: true });
          } catch (staleError) {
            if ((staleError as NodeJS.ErrnoException).code !== "ENOENT") throw staleError;
          }
          continue;
        }
        if (Date.now() >= deadline) throw new Error(`Provider catalog is locked: ${modelsPath}`);
        await new Promise((resolve) => setTimeout(resolve, 50));
      }
    }
    try {
      await writeFile(join(lockPath, "owner.json"), `${JSON.stringify({ pid: process.pid, createdAt: new Date().toISOString() })}\n`, { encoding: "utf8", flag: "wx" });
      return await operation();
    }
    finally { await rm(lockPath, { recursive: true, force: true }); }
  });
  modelWriteQueues.set(modelsPath, queued);
  try { return await queued; }
  finally { if (modelWriteQueues.get(modelsPath) === queued) modelWriteQueues.delete(modelsPath); }
}

async function atomicJsonWrite(path: string, value: unknown): Promise<void> {
  const suffix = `${process.pid}.${randomUUID()}`;
  const temporary = join(dirname(path), `.${basename(path)}.${suffix}.tmp`);
  const backup = join(dirname(path), `.${basename(path)}.${suffix}.bak`);
  await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, { encoding: "utf8", flag: "wx" });
  let backedUp = false;
  try {
    try { await rename(temporary, path); }
    catch (error) {
      if (!(["EEXIST", "EPERM", "EACCES"] as const).includes((error as NodeJS.ErrnoException).code as "EEXIST")) throw error;
      await rename(path, backup);
      backedUp = true;
      try { await rename(temporary, path); }
      catch (replaceError) {
        await rename(backup, path).catch(() => undefined);
        throw replaceError;
      }
    }
  } finally {
    await rm(temporary, { force: true }).catch(() => undefined);
    if (backedUp) await rm(backup, { force: true }).catch(() => undefined);
  }
}

async function readProviderCatalog(modelsPath: string): Promise<Record<string, unknown>> {
  try {
    const parsed = JSON.parse(await readFile(modelsPath, "utf8")) as { providers?: unknown };
    if (parsed.providers === undefined) return {};
    if (!parsed.providers || typeof parsed.providers !== "object" || Array.isArray(parsed.providers)) {
      throw new Error(`Invalid provider catalog: ${modelsPath}`);
    }
    return parsed.providers as Record<string, unknown>;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return {};
    throw error;
  }
}

function providerConfig(input: ProviderConfigInput): Record<string, unknown> {
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(input.id)) throw new Error("Invalid provider id");
  if (!/^[A-Z][A-Z0-9_]{0,127}$/.test(input.apiKeyEnv)) throw new Error("Invalid API key environment name");
  if (input.baseUrl) {
    const url = new URL(input.baseUrl);
    if (url.protocol !== "http:" && url.protocol !== "https:") throw new Error("Provider endpoint must use http or https");
    if (url.username || url.password || url.hash) throw new Error("Provider endpoint must not contain credentials or fragments");
  }
  if (input.models.length === 0) throw new Error("At least one model is required");
  const pricing = PROVIDER_PRICING[input.id] ?? DEFAULT_PRICING;
  return {
    baseUrl: input.baseUrl,
    api: input.api,
    apiKey: `$${input.apiKeyEnv}`,
    models: input.models.map((model) => ({
      id: model.id,
      name: model.name ?? model.id,
      ...(model.reasoning === undefined ? {} : { reasoning: model.reasoning }),
      cost: { ...pricing },
    })),
  };
}

/** Persist provider metadata and, when supplied, the key in Pi's auth store. */
export async function saveProviderConfig(input: ProviderConfigInput, options: { agentDir?: string } = {}): Promise<SetupResult> {
  const agentDir = options.agentDir ?? getAgentDir();
  const modelsPath = join(agentDir, "models.json");
  assertApiKeyEnv(input.apiKeyEnv);
  await mkdir(agentDir, { recursive: true });
  const apiKey = input.apiKey?.trim();
  if (apiKey) {
    // AuthStorage is intentionally not part of Pi's public root export. Resolve
    // the locked runtime's implementation without reading or logging secrets.
    const entry = fileURLToPath(import.meta.resolve("@earendil-works/pi-coding-agent"));
    const { AuthStorage } = await import(pathToFileURL(join(dirname(entry), "core", "auth-storage.js")).href);
    const auth = AuthStorage.create(join(agentDir, "auth.json"));
    await auth.modify(input.id, async () => ({ type: "api_key", key: apiKey }));
  }
  if (!PI_NATIVE_PROVIDERS.has(input.id)) {
    await withModelsLock(modelsPath, async () => {
      const existing = await readProviderCatalog(modelsPath);
      await atomicJsonWrite(modelsPath, { providers: { ...existing, [input.id]: providerConfig(input) } });
    });
  }
  return { path: modelsPath, providers: [input.id] };
}

/**
 * Write Pi's `models.json` with the selected provider presets, merging into
 * any existing providers rather than clobbering them. No API key literal is
 * ever written — only `$ENV_VAR` references.
 */
export async function setupProviders(options: SetupOptions = {}): Promise<SetupResult> {
  const agentDir = options.agentDir ?? getAgentDir();
  const modelsPath = join(agentDir, "models.json");
  const selected = options.providers && options.providers.length > 0
    ? options.providers
    : PROVIDER_PRESETS.map((preset) => preset.id);

  const providers: Record<string, unknown> = {};
  for (const id of selected) {
    const preset = PROVIDER_PRESETS.find((candidate) => candidate.id === id);
    if (!preset) throw new Error(`Unknown provider: ${id}`);
    if (!PI_NATIVE_PROVIDERS.has(id)) providers[id] = providerToJson(preset);
  }

  await mkdir(agentDir, { recursive: true });
  if (Object.keys(providers).length > 0) {
    await withModelsLock(modelsPath, async () => {
      const existing = await readProviderCatalog(modelsPath);
      await atomicJsonWrite(modelsPath, { providers: { ...existing, ...providers } });
    });
  }
  return { path: modelsPath, providers: [...selected] };
}

/** Whether a custom or built-in provider is ready for an interactive launch. */
export async function hasConfiguredProvider(options: { agentDir?: string } = {}): Promise<boolean> {
  const agentDir = options.agentDir ?? getAgentDir();
  const modelsPath = join(agentDir, "models.json");
  try {
    const parsed = JSON.parse(await readFile(modelsPath, "utf8")) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return false;
    const providers = (parsed as { providers?: unknown }).providers;
    if (providers !== undefined &&
      typeof providers === "object" &&
      !Array.isArray(providers) &&
      Object.keys(providers as object).length > 0) return true;
  } catch {
    // Built-in providers do not require models.json.
  }
  for (const preset of PROVIDER_PRESETS) {
    if (preset.id === "custom" || preset.id === "ollama") continue;
    if (await providerCredentialSource(preset, { agentDir }) !== "missing") return true;
  }
  return false;
}
