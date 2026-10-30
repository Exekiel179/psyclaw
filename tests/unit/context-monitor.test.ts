import { describe, it, expect } from "vitest";
import { analyzeContext, formatContextWarning, type ContextStats } from "../../dist/src/core/context-monitor.js";
import { DEFAULT_MODEL_CONFIG } from "../../dist/src/core/model-config.js";
import type { Context } from "@earendil-works/pi-ai";

describe("context-monitor", () => {
  it("analyzes empty context", () => {
    const context: Context = { messages: [] };
    const stats = analyzeContext(context, DEFAULT_MODEL_CONFIG.context);
    
    expect(stats.totalTokens).toBe(0);
    expect(stats.messageCount).toBe(0);
    expect(stats.exceedsWarning).toBe(false);
    expect(stats.exceedsCompaction).toBe(false);
  });

  it("analyzes small context", () => {
    const context: Context = {
      messages: [
        { role: "user", content: "Hello" },
        { role: "assistant", content: "Hi there" },
      ],
    };
    const stats = analyzeContext(context, DEFAULT_MODEL_CONFIG.context);
    
    expect(stats.totalTokens).toBeGreaterThan(0);
    expect(stats.totalTokens).toBeLessThan(100);
    expect(stats.messageCount).toBe(2);
    expect(stats.exceedsWarning).toBe(false);
  });

  it("detects context exceeding warning threshold", () => {
    const longMessage = "a".repeat(80_000 * 4); // ~80k tokens
    const context: Context = {
      messages: [{ role: "user", content: longMessage }],
    };
    const stats = analyzeContext(context, DEFAULT_MODEL_CONFIG.context);
    
    expect(stats.exceedsWarning).toBe(true);
    expect(stats.exceedsCompaction).toBe(false);
  });

  it("detects context exceeding compaction threshold", () => {
    const longMessage = "a".repeat(100_000 * 4); // ~100k tokens
    const context: Context = {
      messages: [{ role: "user", content: longMessage }],
    };
    const stats = analyzeContext(context, DEFAULT_MODEL_CONFIG.context);
    
    expect(stats.exceedsWarning).toBe(true);
    expect(stats.exceedsCompaction).toBe(true);
  });

  it("formats warning for compaction threshold", () => {
    const stats: ContextStats = {
      totalTokens: 100_000,
      messageCount: 50,
      exceedsWarning: true,
      exceedsCompaction: true,
    };
    const warning = formatContextWarning(stats, DEFAULT_MODEL_CONFIG.context);
    
    expect(warning).toContain("100k tokens");
    expect(warning).toContain("/compact");
    expect(warning).toContain("HANDOFF");
  });

  it("formats warning for warning threshold", () => {
    const stats: ContextStats = {
      totalTokens: 85_000,
      messageCount: 40,
      exceedsWarning: true,
      exceedsCompaction: false,
    };
    const warning = formatContextWarning(stats, DEFAULT_MODEL_CONFIG.context);
    
    expect(warning).toContain("85k tokens");
    expect(warning).toContain("接近建议阈值");
  });

  it("returns empty string for normal context", () => {
    const stats: ContextStats = {
      totalTokens: 10_000,
      messageCount: 10,
      exceedsWarning: false,
      exceedsCompaction: false,
    };
    const warning = formatContextWarning(stats, DEFAULT_MODEL_CONFIG.context);
    
    expect(warning).toBe("");
  });

  it("respects disabled config", () => {
    const longMessage = "a".repeat(100_000 * 4);
    const context: Context = {
      messages: [{ role: "user", content: longMessage }],
    };
    const stats = analyzeContext(context, {
      ...DEFAULT_MODEL_CONFIG.context,
      enabled: false,
    });
    
    expect(stats.exceedsWarning).toBe(false);
    expect(stats.exceedsCompaction).toBe(false);
  });
});
