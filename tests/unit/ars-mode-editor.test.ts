import { describe, expect, it } from "vitest";
import { ARS_MODE_STATUS, enterArsModeEditorText, isArsModeEditorText } from "../../src/ars/mode-editor.js";

describe("ARS conversation mode editor helpers", () => {
  it("exposes footer status label academic mode", () => {
    expect(ARS_MODE_STATUS).toBe("academic mode");
  });

  it("detects ars: prefix case-insensitively", () => {
    expect(isArsModeEditorText("ars: hello")).toBe(true);
    expect(isArsModeEditorText("ARS: ")).toBe(true);
    expect(isArsModeEditorText("ars")).toBe(false);
    expect(isArsModeEditorText("/ars start")).toBe(false);
  });

  it("expands bare ars into ars: mode text for compatibility", () => {
    expect(enterArsModeEditorText("ars")).toBe("ars: ");
    expect(enterArsModeEditorText("/ars")).toBe("ars: ");
    expect(enterArsModeEditorText("")).toBe("ars: ");
    expect(enterArsModeEditorText("ars: keep")).toBe("ars: keep");
  });
});
