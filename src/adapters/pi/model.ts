import type {
  Api,
  AssistantMessage,
  AssistantMessageEventStream,
  Context,
  Model,
  SimpleStreamOptions,
} from "@earendil-works/pi-ai";
import {
  ModelRuntime,
  type ProviderConfig,
} from "@earendil-works/pi-coding-agent";
import { pricingFor } from "../../core/pricing.js";

const PROVIDER_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
// Model ids are opaque provider values. Some registries use namespaces such
// as `org/model` or tags such as `qwen:32b`, so a provider-only identifier
// grammar would reject valid models. They still cannot contain traversal.
const MODEL_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$/;
const ENV_RE = /^[A-Z][A-Z0-9_]{0,127}$/;

export interface ModelRef {
  provider: string;
  id: string;
}

export interface ModelDescriptor extends ModelRef {
  name: string;
  api: string;
  baseUrl: string;
  reasoning: boolean;
  input: readonly ("text" | "image")[];
  contextWindow: number;
  maxTokens: number;
}

export interface ModelGateway {
  list(): readonly ModelDescriptor[];
  resolve(ref: ModelRef): Model<Api>;
  getRuntime(): ModelRuntime;
  stream(model: ModelRef, context: Context, options?: SimpleStreamOptions): AssistantMessageEventStream;
  complete(model: ModelRef, context: Context, options?: SimpleStreamOptions): Promise<AssistantMessage>;
}

export interface PiModelGatewayOptions {
  runtime?: ModelRuntime;
  authPath?: string;
  modelsPath?: string | null;
  /** Network refresh is opt-in; the default is offline/cache-only. */
  allowModelNetwork?: boolean;
  refreshOnCreate?: boolean;
}

function assertProviderId(value: string): void {
  if (!PROVIDER_ID_RE.test(value)) throw new Error("provider must be a short stable identifier");
}

function assertModelId(value: string): void {
  if (!MODEL_ID_RE.test(value) || value.includes("..")) {
    throw new Error("model must be a stable provider identifier");
  }
}

function normalizeEndpoint(value: string): string {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error("Provider endpoint must be a valid URL");
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") {
    throw new Error("Provider endpoint must use http or https");
  }
  if (url.username || url.password || url.hash) {
    throw new Error("Provider endpoint must not contain credentials or a fragment");
  }
  return url.toString().replace(/\/$/, "");
}

function displayEndpoint(value: string): string {
  if (!value) return "";
  try {
    return normalizeEndpoint(value);
  } catch {
    return "<redacted>";
  }
}

function descriptor(model: Model<Api>): ModelDescriptor {
  return Object.freeze({
    provider: model.provider,
    id: model.id,
    name: model.name,
    api: model.api,
    baseUrl: displayEndpoint(model.baseUrl),
    reasoning: model.reasoning,
    input: Object.freeze([...model.input]),
    contextWindow: model.contextWindow,
    maxTokens: model.maxTokens,
  });
}

export class PiModelGateway implements ModelGateway {
  public constructor(private readonly runtime: ModelRuntime) {}

  public static async create(options: PiModelGatewayOptions = {}): Promise<PiModelGateway> {
    const runtime = options.runtime ?? await ModelRuntime.create({
      ...(options.authPath === undefined ? {} : { authPath: options.authPath }),
      ...(options.modelsPath === undefined ? {} : { modelsPath: options.modelsPath }),
      allowModelNetwork: options.allowModelNetwork ?? false,
      refreshOnCreate: options.refreshOnCreate ?? false,
    });
    return new PiModelGateway(runtime);
  }

  public getRuntime(): ModelRuntime {
    return this.runtime;
  }

  public list(): readonly ModelDescriptor[] {
    return Object.freeze(this.runtime.getModels().map((model) => descriptor(model)));
  }

  public resolve(ref: ModelRef): Model<Api> {
    assertProviderId(ref.provider);
    assertModelId(ref.id);
    const model = this.runtime.getModel(ref.provider, ref.id);
    if (!model) throw new Error(`Model not found: ${ref.provider}/${ref.id}`);
    return model;
  }

  public stream(ref: ModelRef, context: Context, options?: SimpleStreamOptions): AssistantMessageEventStream {
    return this.runtime.streamSimple(this.resolve(ref), context, options);
  }

  public complete(ref: ModelRef, context: Context, options?: SimpleStreamOptions): Promise<AssistantMessage> {
    return this.runtime.completeSimple(this.resolve(ref), context, options);
  }
}

export interface OpenAICompatibleModelSpec {
  id: string;
  name?: string;
  reasoning?: boolean;
  input?: ("text" | "image")[];
  contextWindow?: number;
  maxTokens?: number;
  thinkingLevelMap?: Record<string, string | null>;
}

export interface OpenAICompatibleProviderSpec {
  id: string;
  name: string;
  baseUrl: string;
  apiKeyEnv: string;
  models: readonly OpenAICompatibleModelSpec[];
  api?: "openai-completions" | "openai-responses";
  /** Optional compatibility hints; no credentials are accepted here. */
  compat?: Record<string, unknown>;
}

/**
 * Convert an OpenAI-compatible provider description into Pi's provider config.
 * The only credential value emitted is an environment-variable reference; a
 * literal API key is intentionally not representable in this API.
 */
export function toOpenAICompatibleProviderConfig(spec: OpenAICompatibleProviderSpec): ProviderConfig {
  assertProviderId(spec.id);
  if (!ENV_RE.test(spec.apiKeyEnv)) throw new Error("apiKeyEnv must be an uppercase environment variable name");
  const baseUrl = normalizeEndpoint(spec.baseUrl);
  if (spec.models.length === 0) throw new Error("Provider must declare at least one model");
  const api = spec.api ?? "openai-completions";
  const models = spec.models.map((model) => {
    assertModelId(model.id);
    const contextWindow = model.contextWindow ?? 128_000;
    const maxTokens = model.maxTokens ?? 16_384;
    if (!Number.isSafeInteger(contextWindow) || contextWindow < 1) throw new Error(`Invalid contextWindow for ${model.id}`);
    if (!Number.isSafeInteger(maxTokens) || maxTokens < 1) throw new Error(`Invalid maxTokens for ${model.id}`);
    return {
      id: model.id,
      name: model.name ?? model.id,
      reasoning: model.reasoning ?? false,
      input: model.input ?? ["text"],
      contextWindow,
      maxTokens,
      cost: { ...pricingFor(spec.id, model.id) },
      ...(model.thinkingLevelMap === undefined ? {} : { thinkingLevelMap: model.thinkingLevelMap }),
      ...(spec.compat === undefined ? {} : { compat: spec.compat }),
    };
  });
  return {
    name: spec.name,
    baseUrl,
    apiKey: `$${spec.apiKeyEnv}`,
    api,
    authHeader: true,
    models,
  };
}

/** A conservative default profile; users may replace the model list. */
export function deepSeekProviderSpec(options: {
  apiKeyEnv?: string;
  baseUrl?: string;
  models?: readonly OpenAICompatibleModelSpec[];
} = {}): OpenAICompatibleProviderSpec {
  return {
    id: "deepseek",
    name: "DeepSeek",
    baseUrl: options.baseUrl ?? "https://api.deepseek.com/v1",
    apiKeyEnv: options.apiKeyEnv ?? "DEEPSEEK_API_KEY",
    models: options.models ?? [
      { id: "deepseek-v4-flash", name: "DeepSeek V4 Flash" },
      { id: "deepseek-v4-pro", name: "DeepSeek V4 Pro", reasoning: true },
    ],
    api: "openai-completions",
    compat: { thinkingFormat: "deepseek" },
  };
}

export function registerOpenAICompatibleProvider(runtime: ModelRuntime, spec: OpenAICompatibleProviderSpec): void {
  runtime.registerProvider(spec.id, toOpenAICompatibleProviderConfig(spec));
}
