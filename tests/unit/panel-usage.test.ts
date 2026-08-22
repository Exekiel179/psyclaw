import { describe, expect, it } from "vitest";
import { aggregateUsageEntries } from "../../src/panel/usage.js";
import { estimateUsageCostCny, USD_CNY_RATE } from "../../src/core/pricing.js";

describe("token usage aggregation", () => {
  it("groups assistant usage by provider/model and totals tokens and cost", () => {
    const report = aggregateUsageEntries([
      {
        type: "message",
        message: {
          role: "assistant",
          provider: "deepseek",
          model: "deepseek-v4-flash",
          timestamp: "2026-08-14T14:09:35.000Z",
          usage: { input: 100, output: 50, cacheRead: 10, cacheWrite: 5, cost: { total: 0.01 } },
        },
      },
      {
        type: "message",
        message: {
          role: "assistant",
          provider: "deepseek",
          responseModel: "deepseek-v4-flash",
          timestamp: "2026-08-15T10:00:00.000Z",
          usage: { input: 20, output: 30, cacheRead: 0, cacheWrite: 0, cost: { total: 0.002 } },
        },
      },
      // user messages carry no usage and must be ignored
      { type: "message", message: { role: "user", content: "hello", timestamp: "2026-08-14T14:09:30.000Z" } },
      {
        type: "compaction",
        timestamp: "2026-08-15T11:00:00.000Z",
        usage: { input: 500, output: 10, cacheRead: 0, cacheWrite: 0, cost: { total: 0.05 } },
      },
    ]);

    expect(report.totals.tokens).toBe(100 + 50 + 10 + 5 + 20 + 30 + 500 + 10);
    expect(report.totals.cost).toBeCloseTo(0.01 + 0.002 + 0.05, 6);

    const deepseek = report.byModel.find((row) => row.key === "deepseek/deepseek-v4-flash")!;
    expect(deepseek.tokens).toBe(100 + 50 + 10 + 5 + 20 + 30);
    expect(deepseek.provider).toBe("deepseek");
    // deepseek pricing: input 0.27, output 1.1, cacheRead 0.07, cacheWrite 0.27 per 1M tokens
    const dsEstimate = ((100 * 0.27 + 50 * 1.1 + 10 * 0.07 + 5 * 0.27) + (20 * 0.27 + 30 * 1.1)) / 1e6;
    expect(deepseek.estimatedCost).toBeCloseTo(dsEstimate, 10);
    // 人民币：DeepSeek 官方人民币价 input 2 / output 8 / cacheRead 0.5 / cacheWrite 2（元/百万）
    const dsEstimateCny = ((100 * 2 + 50 * 8 + 10 * 0.5 + 5 * 2) + (20 * 2 + 30 * 8)) / 1e6;
    expect(deepseek.estimatedCostCny).toBeCloseTo(dsEstimateCny, 10);
    expect(deepseek.costCny).toBeCloseTo((0.01 + 0.002) * USD_CNY_RATE, 10);

    const summaries = report.byModel.find((row) => row.key === "summaries/summaries")!;
    expect(summaries.tokens).toBe(510);
    expect(summaries.estimatedCost).toBeCloseTo((500 * 1 + 10 * 3) / 1e6, 10);

    expect(report.totals.estimatedCost).toBeCloseTo(dsEstimate + (500 * 1 + 10 * 3) / 1e6, 10);
    expect(report.totals.estimatedCostCny).toBeCloseTo(dsEstimateCny + (500 * 1 + 10 * 3) / 1e6 * USD_CNY_RATE, 10);
    expect(report.totals.costCny).toBeCloseTo((0.01 + 0.002 + 0.05) * USD_CNY_RATE, 10);

    // one daily row per (date, provider/model)
    expect(report.daily.length).toBe(3);
    const day = report.daily.find((row) => row.date === "2026-08-15" && row.key === "deepseek/deepseek-v4-flash")!;
    expect(day.tokens).toBe(50);
    expect(day.estimatedCost).toBeCloseTo((20 * 0.27 + 30 * 1.1) / 1e6, 10);
    expect(day.estimatedCostCny).toBeCloseTo((20 * 2 + 30 * 8) / 1e6, 10);
  });

  it("ignores entries without usage", () => {
    const report = aggregateUsageEntries([
      { type: "model_change", provider: "deepseek", modelId: "deepseek-v4-flash" },
      { type: "session", version: 3 },
      { type: "message", message: { role: "toolResult", content: "ok" } },
    ]);
    expect(report.totals.tokens).toBe(0);
    expect(report.totals.estimatedCost).toBe(0);
    expect(report.totals.estimatedCostCny).toBe(0);
    expect(report.byModel).toEqual([]);
    expect(report.daily).toEqual([]);
  });
});

describe("CNY pricing", () => {
  it("uses official RMB list price for deepseek and rate fallback for openai", () => {
    const usage = { input: 1e6, output: 0, cacheRead: 0, cacheWrite: 0 };
    expect(estimateUsageCostCny(usage, "deepseek", "deepseek-chat")).toBeCloseTo(2, 6); // 2 元/百万
    // OpenAI 无官方人民币价 → USD×汇率
    expect(estimateUsageCostCny(usage, "openai", "gpt-5.5")).toBeCloseTo(1.25 * USD_CNY_RATE, 6);
  });
});
