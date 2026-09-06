import { describe, expect, it } from "vitest";
import { MODE_STATUS, nextSessionMode, sessionModePrompt } from "../../src/session/modes.js";
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
  });
});

describe("ARS editor helpers", () => {
  it("detects ars: prefix", () => {
    expect(isArsModeEditorText("ars: hello")).toBe(true);
    expect(enterArsModeEditorText("ars")).toBe("ars: ");
  });
});

describe("verify checklist", () => {
  it("formats human verify items without sha language", () => {
    const text = formatVerifyChecklist(defaultVerifyChecklist("2026-01-01T00:00:00.000Z"));
    expect(text).toContain("[ ] n:");
    expect(text).toContain("/verify");
    expect(text).not.toContain("sha256");
  });
});
