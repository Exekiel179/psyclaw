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
import { lastPiGeneration, trackLlmGeneration, withAgentSpan } from "../../observability/index.js";
import { normalizeEndpoint } from "../../core/provider-endpoint.js";
import { readModelConfig, type ModelConfig } from "../../core/model-config.js";
import { analyzeContext, formatContextWarning } from "../../core/context-monitor.js";

export { normalizeEndpoint } from "../../core/provider-endpoint.js";

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
  /** Optional retry config; defaults to reading from settings. */
  modelConfig?: ModelConfig;
}

function assertProviderId(value: string): void {
  if (!PROVIDER_ID_RE.test(value)) throw new Error("provider must be a short stable identifier");
}

function assertModelId(value: string): void {
  if (!MODEL_ID_RE.test(value) || value.includes("..")) {
    throw new Error("model must be a stable provider identifier");
  }
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
  private modelConfig: ModelConfig | undefined;
  private configPromise: Promise<ModelConfig> | undefined;

  public constructor(
    private readonly runtime: ModelRuntime,
    modelConfig?: ModelConfig,
  ) {
    if (modelConfig) {
      this.modelConfig = modelConfig;
    }
  }

  public static async create(options: PiModelGatewayOptions = {}): Promise<PiModelGateway> {
    const runtime = options.runtime ?? await ModelRuntime.create({
      ...(options.authPath === undefined ? {} : { authPath: options.authPath }),
      ...(options.modelsPath === undefined ? {} : { modelsPath: options.modelsPath }),
      allowModelNetwork: options.allowModelNetwork ?? false,
      refreshOnCreate: options.refreshOnCreate ?? false,
    });
    return new PiModelGateway(runtime, options.modelConfig);
  }

  private async getConfig(): Promise<ModelConfig> {
    if (this.modelConfig) return this.modelConfig;
    if (!this.configPromise) {
      this.configPromise = readModelConfig();
    }
    this.modelConfig = await this.configPromise;
    return this.modelConfig;
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

  public async complete(ref: ModelRef, context: Context, options?: SimpleStreamOptions): Promise<AssistantMessage> {
    const startedAt = Date.now();
    const config = await this.getConfig();
    
    // Check context size and warn if needed
    const stats = analyzeContext(context, config.context);
    if (stats.exceedsWarning) {
      const warning = formatContextWarning(stats, config.context);
      if (warning) {
        console.warn(`\n⚠️  ${warning}\n`);
      }
    }
    
    const maxRetries = config.retry.maxRetries;
    const initialDelayMs = config.retry.initialDelayMs;
    const maxDelayMs = config.retry.maxDelayMs;
    
    let lastError: unknown;
    for (let attempt = 0; attempt <= maxRetries; attempt += 1) {
      try {
        const message = await withAgentSpan(
          "cli.llm_call",
          { phase: "pi_complete", provider: ref.provider, model: ref.id, attempt: String(attempt) },
          () => this.runtime.completeSimple(this.resolve(ref), context, options),
        );
        const generation = lastPiGeneration([{ type: "message", message }]);
        void trackLlmGeneration({
          provider: generation?.provider ?? ref.provider,
          model: generation?.model ?? ref.id,
          ...(generation?.usage === undefined ? {} : { usage: generation.usage }),
          latencyMs: Date.now() - startedAt,
          surface: "cli",
          spanName: "pi-complete",
        });
        return message;
      } catch (error) {
        lastError = error;
        const isTransient = this.isTransientError(error);
        const shouldRetry = isTransient && attempt < maxRetries;
        
        const httpStatus = this.extractHttpStatus(error);
        void trackLlmGeneration({
          provider: ref.provider,
          model: ref.id,
          latencyMs: Date.now() - startedAt,
          error: true,
          errorName: error instanceof Error ? error.name : "Error",
          ...(httpStatus === undefined ? {} : { httpStatus }),
          surface: "cli",
          spanName: "pi-complete",
        });
        
        if (!shouldRetry) break;
        
        const delayMs = Math.min(initialDelayMs * Math.pow(2, attempt), maxDelayMs);
        await new Promise((resolve) => setTimeout(resolve, delayMs));
      }
    }
    
    // Try fallback if configured and primary provider is a known default
    const fallbackModel = config.retry.fallbackModel;
    if (fallbackModel && this.isDefaultProvider(ref.provider)) {
      try {
        console.warn(`\n⚠️  模型 ${ref.provider}/${ref.id} 调用失败，正在尝试备用模型 ${fallbackModel.provider}/${fallbackModel.id}...\n`);
        const fallbackMessage = await withAgentSpan(
          "cli.llm_call",
          { phase: "pi_complete_fallback", provider: fallbackModel.provider, model: fallbackModel.id },
          () => this.runtime.completeSimple(this.resolve(fallbackModel), context, options),
        );
        const generation = lastPiGeneration([{ type: "message", message: fallbackMessage }]);
        void trackLlmGeneration({
          provider: generation?.provider ?? fallbackModel.provider,
          model: generation?.model ?? fallbackModel.id,
          ...(generation?.usage === undefined ? {} : { usage: generation.usage }),
          latencyMs: Date.now() - startedAt,
          surface: "cli",
          spanName: "pi-complete-fallback",
        });
        return fallbackMessage;
      } catch (fallbackError) {
        const fallbackHttpStatus = this.extractHttpStatus(fallbackError);
        void trackLlmGeneration({
          provider: fallbackModel.provider,
          model: fallbackModel.id,
          latencyMs: Date.now() - startedAt,
          error: true,
          errorName: fallbackError instanceof Error ? fallbackError.name : "Error",
          ...(fallbackHttpStatus === undefined ? {} : { httpStatus: fallbackHttpStatus }),
          surface: "cli",
          spanName: "pi-complete-fallback",
        });
      }
    }
    
    // Report final failure to telemetry
    const { captureAgentError: reportError } = await import("../../observability/index.js");
    const errorMessage = lastError instanceof Error ? lastError.message : String(lastError);
    void reportError(lastError, { 
      phase: "llm_call_failed",
      provider: ref.provider,
      model: ref.id,
      attempts: String(maxRetries + 1),
    });
    
    throw new Error(`模型调用最终失败（尝试 ${maxRetries + 1} 次）：${errorMessage}`);
  }
  
  private isTransientError(error: unknown): boolean {
    if (!(error instanceof Error)) return false;
    const message = error.message.toLowerCase();
    const name = error.name.toLowerCase();
    
    // Check for 5xx status codes
    if (message.includes("500") || message.includes("502") || message.includes("503") || message.includes("504")) {
      return true;
    }
    
    // Check for timeout errors
    if (
      name.includes("timeout") ||
      message.includes("timeout") ||
      message.includes("timed out") ||
      message.includes("etimedout") ||
      message.includes("econnreset") ||
      message.includes("econnrefused")
    ) {
      return true;
    }
    
    return false;
  }
  
  private extractHttpStatus(error: unknown): number | undefined {
    if (!(error instanceof Error)) return undefined;
    const message = error.message;
    
    // Try to extract HTTP status from error message
    const match = message.match(/\b(5\d{2})\b/);
    if (match?.[1]) return Number.parseInt(match[1], 10);
    
    return undefined;
  }
  
  private isDefaultProvider(providerId: string): boolean {
    // Only allow fallback for known default providers, never for custom user configs
    return providerId === "deepseek" || providerId === "openai" || providerId === "anthropic";
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
      { id: "deepseek-chat", name: "DeepSeek Chat" },
      { id: "deepseek-reasoner", name: "DeepSeek Reasoner", reasoning: true },
    ],
    api: "openai-completions",
    compat: { thinkingFormat: "deepseek" },
  };
}

export function registerOpenAICompatibleProvider(runtime: ModelRuntime, spec: OpenAICompatibleProviderSpec): void {
  runtime.registerProvider(spec.id, toOpenAICompatibleProviderConfig(spec));
}
