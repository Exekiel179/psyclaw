/**
 * Context size monitoring and compaction suggestions.
 */

import type { Context } from "@earendil-works/pi-ai";
import type { ContextConfig } from "./model-config.js";

export interface ContextStats {
  totalTokens: number;
  messageCount: number;
  exceedsWarning: boolean;
  exceedsCompaction: boolean;
}

function estimateTokens(text: string): number {
  // Rough estimate: ~4 characters per token for multilingual text
  return Math.ceil(text.length / 4);
}

function extractText(item: unknown): string {
  if (typeof item === "string") return item;
  if (Array.isArray(item)) return item.map(extractText).join(" ");
  if (item && typeof item === "object") {
    const obj = item as Record<string, unknown>;
    if ("text" in obj && typeof obj.text === "string") return obj.text;
    if ("content" in obj) return extractText(obj.content);
    return Object.values(obj).map(extractText).join(" ");
  }
  return "";
}

export function analyzeContext(context: Context, config: ContextConfig): ContextStats {
  let totalTokens = 0;
  let messageCount = 0;

  for (const message of context.messages) {
    messageCount += 1;
    const text = extractText(message.content);
    totalTokens += estimateTokens(text);
  }

  return {
    totalTokens,
    messageCount,
    exceedsWarning: config.enabled && totalTokens >= config.warningThreshold,
    exceedsCompaction: config.enabled && totalTokens >= config.compactionThreshold,
  };
}

export function formatContextWarning(stats: ContextStats, config: ContextConfig): string {
  const tokenK = Math.round(stats.totalTokens / 1000);
  const thresholdK = Math.round(config.compactionThreshold / 1000);
  
  if (stats.exceedsCompaction) {
    return `当前会话上下文已达 ~${tokenK}k tokens（${stats.messageCount} 条消息），超过建议阈值 ${thresholdK}k。建议：\n` +
           `1. 使用 /compact 压缩历史对话\n` +
           `2. 或结束本次会话，从 HANDOFF 继续新会话\n` +
           `3. 或在 ~/.psyclaw/agent/psyclaw-settings.json 中调整 modelConfig.context.compactionThreshold`;
  }
  
  if (stats.exceedsWarning) {
    const warningK = Math.round(config.warningThreshold / 1000);
    return `当前会话上下文约 ${tokenK}k tokens（${stats.messageCount} 条消息），接近建议阈值 ${warningK}k。长会话可能增加成本和延迟。`;
  }
  
  return "";
}
