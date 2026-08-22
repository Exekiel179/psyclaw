import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import { estimateUsageCost, estimateUsageCostCny, USD_CNY_RATE } from "../core/pricing.js";

export interface UsageRow {
  key: string;
  provider: string;
  model: string;
  input: number;
  output: number;
  cacheRead: number;
  cacheWrite: number;
  tokens: number;
  cost: number;
  estimatedCost: number;
  /** 人民币：实际费用按汇率折算（Pi 记录为 USD） */
  costCny: number;
  /** 人民币：国内厂商按官方价，其余按汇率 */
  estimatedCostCny: number;
}

export interface DailyUsageRow {
  date: string;
  key: string;
  provider: string;
  model: string;
  tokens: number;
  cost: number;
  estimatedCost: number;
  costCny: number;
  estimatedCostCny: number;
}

export interface TokenUsageReport {
  schemaVersion: "psyclaw/token-usage/v1";
  generatedAt: string;
  totals: { input: number; output: number; cacheRead: number; cacheWrite: number; tokens: number; cost: number; estimatedCost: number; costCny: number; estimatedCostCny: number };
  byModel: UsageRow[];
  daily: DailyUsageRow[];
}

interface UsageShape {
  input?: unknown;
  output?: unknown;
  cacheRead?: unknown;
  cacheWrite?: unknown;
  cost?: { input?: unknown; output?: unknown; cacheRead?: unknown; cacheWrite?: unknown; total?: unknown };
}

function num(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

/** Estimated cost in USD for one usage record (re-export from core pricing). */
export const estimateCost = estimateUsageCost;

/** 人民币估算：官方人民币价或汇率折算。 */
export const estimateCostCny = estimateUsageCostCny;

function usageOf(value: unknown): UsageShape | undefined {
  if (!value || typeof value !== "object") return undefined;
  const usage = value as UsageShape;
  if (typeof usage.input !== "number" && typeof usage.output !== "number" && typeof usage.cacheRead !== "number") {
    return undefined;
  }
  return usage;
}

function extractUsage(entry: unknown): { provider: string; model: string; date: string; usage: UsageShape } | undefined {
  if (!entry || typeof entry !== "object") return undefined;
  const record = entry as { type?: unknown; message?: unknown; usage?: unknown; timestamp?: unknown };
  let usage: UsageShape | undefined;
  let provider = "?";
  let model = "?";
  let timestamp: unknown = record.timestamp;
  if (record.type === "message" && record.message && typeof record.message === "object") {
    const message = record.message as { usage?: unknown; provider?: unknown; model?: unknown; responseModel?: unknown; timestamp?: unknown };
    usage = usageOf(message.usage);
    if (message.timestamp) timestamp = message.timestamp;
    provider = typeof message.provider === "string" ? message.provider : "?";
    model = typeof message.responseModel === "string" ? message.responseModel : typeof message.model === "string" ? message.model : "?";
  } else if ((record.type === "branch_summary" || record.type === "compaction") && record.usage) {
    usage = usageOf(record.usage);
    provider = "summaries";
    model = "summaries";
  }
  if (!usage) return undefined;
  const date = typeof timestamp === "string" && /^\d{4}-\d{2}-\d{2}/.test(timestamp) ? timestamp.slice(0, 10) : "unknown";
  return { provider, model, date, usage };
}

function addRow(map: Map<string, UsageRow>, key: string, provider: string, model: string, usage: UsageShape): void {
  let row = map.get(key);
  if (!row) {
    row = { key, provider, model, input: 0, output: 0, cacheRead: 0, cacheWrite: 0, tokens: 0, cost: 0, estimatedCost: 0, costCny: 0, estimatedCostCny: 0 };
    map.set(key, row);
  }
  const input = num(usage.input);
  const output = num(usage.output);
  const cacheRead = num(usage.cacheRead);
  const cacheWrite = num(usage.cacheWrite);
  row.input += input;
  row.output += output;
  row.cacheRead += cacheRead;
  row.cacheWrite += cacheWrite;
  row.tokens += input + output + cacheRead + cacheWrite;
  const cost = num(usage.cost?.total);
  row.cost += cost;
  row.costCny += cost * USD_CNY_RATE;
  row.estimatedCost += estimateCost(usage, provider, model);
  row.estimatedCostCny += estimateCostCny(usage, provider, model);
}

/** Aggregate token usage from raw pi session entries (pure, testable). */
export function aggregateUsageEntries(entries: readonly unknown[]): TokenUsageReport {
  const byModel = new Map<string, UsageRow>();
  const daily = new Map<string, DailyUsageRow>();
  for (const entry of entries) {
    const extracted = extractUsage(entry);
    if (!extracted) continue;
    addRow(byModel, `${extracted.provider}/${extracted.model}`, extracted.provider, extracted.model, extracted.usage);
    const dailyKey = `${extracted.date}|${extracted.provider}/${extracted.model}`;
    let day = daily.get(dailyKey);
    if (!day) {
      day = { date: extracted.date, key: `${extracted.provider}/${extracted.model}`, provider: extracted.provider, model: extracted.model, tokens: 0, cost: 0, estimatedCost: 0, costCny: 0, estimatedCostCny: 0 };
      daily.set(dailyKey, day);
    }
    const tokens = num(extracted.usage.input) + num(extracted.usage.output) + num(extracted.usage.cacheRead) + num(extracted.usage.cacheWrite);
    day.tokens += tokens;
    const cost = num(extracted.usage.cost?.total);
    day.cost += cost;
    day.costCny += cost * USD_CNY_RATE;
    day.estimatedCost += estimateCost(extracted.usage, extracted.provider, extracted.model);
    day.estimatedCostCny += estimateCostCny(extracted.usage, extracted.provider, extracted.model);
  }
  const totals = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, tokens: 0, cost: 0, estimatedCost: 0, costCny: 0, estimatedCostCny: 0 };
  for (const row of byModel.values()) {
    totals.input += row.input;
    totals.output += row.output;
    totals.cacheRead += row.cacheRead;
    totals.cacheWrite += row.cacheWrite;
    totals.tokens += row.tokens;
    totals.cost += row.cost;
    totals.costCny += row.costCny;
    totals.estimatedCost += row.estimatedCost;
    totals.estimatedCostCny += row.estimatedCostCny;
  }
  const sortRows = (rows: UsageRow[]): UsageRow[] => [...rows].sort((a, b) => b.tokens - a.tokens);
  return {
    schemaVersion: "psyclaw/token-usage/v1",
    generatedAt: new Date().toISOString(),
    totals,
    byModel: sortRows([...byModel.values()]),
    daily: [...daily.values()].sort((a, b) => b.date.localeCompare(a.date) || b.tokens - a.tokens),
  };
}

/** Walk a pi session directory and aggregate usage, capped to avoid scanning everything. */
export async function readSessionUsage(sessionsDir: string, maxBytes = 64 * 1024 * 1024): Promise<TokenUsageReport> {
  const entries: unknown[] = [];
  let bytes = 0;
  const walk = async (directory: string): Promise<void> => {
    let files: import("node:fs").Dirent[] = [];
    try { files = await readdir(directory, { withFileTypes: true }); } catch { return; }
    for (const file of files) {
      if (bytes >= maxBytes) return;
      const absolute = join(directory, file.name);
      if (file.isDirectory()) {
        await walk(absolute);
      } else if (file.isFile() && file.name.endsWith(".jsonl")) {
        try {
          const content = await readFile(absolute, "utf8");
          bytes += content.length;
          for (const line of content.split(/\r?\n/)) {
            if (!line.trim()) continue;
            try { entries.push(JSON.parse(line)); } catch { /* skip malformed lines */ }
          }
        } catch { /* skip unreadable files */ }
      }
    }
  };
  await walk(sessionsDir);
  return aggregateUsageEntries(entries);
}
