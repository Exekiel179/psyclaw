import { describe, expect, it } from "vitest";
import {
  MODE_STATUS,
  detectChatModeMismatch,
  formatChatModeMismatchNotice,
  nextSessionMode,
  sessionModePrompt,
} from "../../src/session/modes.js";
import { ARS_MODE_STATUS, enterArsModeEditorText, isArsModeEditorText } from "../../src/ars/mode-editor.js";
import { defaultVerifyChecklist, formatVerifyChecklist } from "../../src/verify/checklist.js";

describe("session modes", () => {
  it("cycles chat → analysis → academic → chat", () => {
    expect(nextSessionMode("chat")).toBe("analysis");
    expect(nextSessionMode("analysis")).toBe("academic");
    expect(nextSessionMode("academic")).toBe("chat");
    expect(MODE_STATUS.academic).toBe("academic");
    expect(ARS_MODE_STATUS).toBe("academic");
  });

  it("exposes mode prompts for soft pipeline", () => {
    expect(sessionModePrompt("analysis")).toContain("Priority: get runnable analysis results");
    expect(sessionModePrompt("academic")).toContain("psyclaw_ars_multi_agent");
    expect(sessionModePrompt("chat")).toContain("MUST remind");
  });

  it("detects chat-mode analysis/academic mismatches without switching", () => {
    const stats = detectChatModeMismatch("我想分析数据");
    expect(stats?.target).toBe("analysis");
    expect(stats?.notify).toContain("Shift+Tab");
    expect(stats?.notify).toContain("analysis");

    const academic = detectChatModeMismatch("帮我写论文终稿");
    expect(academic?.target).toBe("academic");

    expect(detectChatModeMismatch("今天天气怎么样")).toBeNull();
    expect(detectChatModeMismatch("/plan status")).toBeNull();

    const notice = formatChatModeMismatchNotice(stats!, "我想分析数据");
    expect(notice).toContain("mandatory");
    expect(notice).toContain("Shift+Tab");
    expect(notice).toContain("我想分析数据");
    expect(notice).not.toContain("/skill:analysis-plan");
  });
});

describe("ARS editor helpers", () => {
  it("detects ars: prefix", () => {
    expect(isArsModeEditorText("ars: hello")).toBe(true);
    expect(enterArsModeEditorText("ars")).toBe("ars: ");
  });
});

describe("verify checklist", () => {
  it("formats AI crosscheck checklist without sha language", () => {
    const text = formatVerifyChecklist(defaultVerifyChecklist("2026-01-01T00:00:00.000Z"));
    expect(text).toContain("AI /crosscheck");
    expect(text).toContain("[ ] n/stats");
    expect(text).toMatch(/\/crosscheck/);
    expect(text).not.toContain("sha256");
  });
});
