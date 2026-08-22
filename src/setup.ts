import { getAgentDir } from "@earendil-works/pi-coding-agent";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
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
  let existing: { providers?: Record<string, unknown> } = {};
  try {
    const parsed = JSON.parse(await readFile(modelsPath, "utf8")) as { providers?: unknown };
    if (parsed.providers && typeof parsed.providers === "object" && !Array.isArray(parsed.providers)) {
      existing.providers = parsed.providers as Record<string, unknown>;
    }
  } catch { /* start with a new catalog */ }
  await mkdir(agentDir, { recursive: true });
  await writeFile(modelsPath, `${JSON.stringify({ providers: { ...existing.providers, [input.id]: providerConfig(input) } }, null, 2)}\n`, "utf8");
  if (input.apiKey?.trim()) {
    // AuthStorage is intentionally not part of Pi's public root export. Resolve
    // the locked runtime's implementation without reading or logging secrets.
    const entry = fileURLToPath(import.meta.resolve("@earendil-works/pi-coding-agent"));
    const { AuthStorage } = await import(pathToFileURL(join(dirname(entry), "core", "auth-storage.js")).href);
    const auth = AuthStorage.create(join(agentDir, "auth.json"));
    await auth.modify(input.id, async () => ({ type: "api_key", key: input.apiKey!.trim() }));
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
    providers[id] = providerToJson(preset);
  }

  let existing: { providers?: Record<string, unknown> } = {};
  try {
    const parsed = JSON.parse(await readFile(modelsPath, "utf8")) as unknown;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      const candidate = (parsed as { providers?: unknown }).providers;
      if (candidate && typeof candidate === "object" && !Array.isArray(candidate)) {
        existing = { providers: candidate as Record<string, unknown> };
      }
    }
  } catch {
    // Missing or malformed file: start from the presets.
  }

  await mkdir(agentDir, { recursive: true });
  const merged = { ...existing.providers, ...providers };
  await writeFile(modelsPath, `${JSON.stringify({ providers: merged }, null, 2)}\n`, "utf8");
  return { path: modelsPath, providers: Object.keys(providers) };
}

/** Whether any provider has been written to `models.json` yet. */
export async function hasConfiguredProvider(options: { agentDir?: string } = {}): Promise<boolean> {
  const agentDir = options.agentDir ?? getAgentDir();
  const modelsPath = join(agentDir, "models.json");
  try {
    const parsed = JSON.parse(await readFile(modelsPath, "utf8")) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return false;
    const providers = (parsed as { providers?: unknown }).providers;
    return providers !== undefined &&
      typeof providers === "object" &&
      !Array.isArray(providers) &&
      Object.keys(providers as object).length > 0;
  } catch {
    return false;
  }
}
