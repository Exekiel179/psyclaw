/**
 * Model gateway configuration (retry, fallback, context limits).
 * Persisted in ~/.psyclaw/agent/psyclaw-settings.json.
 */

import { getAgentDir } from "@earendil-works/pi-coding-agent";
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";

export interface RetryConfig {
  maxRetries: number;
  initialDelayMs: number;
  maxDelayMs: number;
  fallbackModel?: { provider: string; id: string };
}

export interface ContextConfig {
  enabled: boolean;
  warningThreshold: number;
  compactionThreshold: number;
  autoCompact: boolean;
}

export interface ModelConfig {
  retry: RetryConfig;
  context: ContextConfig;
}

export const DEFAULT_MODEL_CONFIG: ModelConfig = {
  retry: {
    maxRetries: 3,
    initialDelayMs: 1000,
    maxDelayMs: 8000,
    fallbackModel: { provider: "deepseek", id: "deepseek-chat" },
  },
  context: {
    enabled: true,
    warningThreshold: 80_000,
    compactionThreshold: 100_000,
    autoCompact: false,
  },
};

function settingsPath(): string {
  return join(getAgentDir(), "psyclaw-settings.json");
}

export async function readModelConfig(): Promise<ModelConfig> {
  try {
    const content = await readFile(settingsPath(), "utf8");
    const settings = JSON.parse(content) as { modelConfig?: Partial<ModelConfig> };
    return {
      retry: { ...DEFAULT_MODEL_CONFIG.retry, ...settings.modelConfig?.retry },
      context: { ...DEFAULT_MODEL_CONFIG.context, ...settings.modelConfig?.context },
    };
  } catch {
    return DEFAULT_MODEL_CONFIG;
  }
}

export async function writeModelConfig(config: Partial<ModelConfig>): Promise<void> {
  const path = settingsPath();
  let existing: Record<string, unknown> = {};
  try {
    existing = JSON.parse(await readFile(path, "utf8")) as Record<string, unknown>;
  } catch {
    /* settings file does not exist yet */
  }
  const updated = {
    ...existing,
    modelConfig: {
      ...DEFAULT_MODEL_CONFIG,
      ...existing.modelConfig as Record<string, unknown>,
      ...config,
    },
  };
  await writeFile(path, `${JSON.stringify(updated, null, 2)}\n`);
}
