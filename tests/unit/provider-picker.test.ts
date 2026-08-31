import { describe, expect, it, vi } from "vitest";
import { SecretInputComponent } from "../../src/tui/provider-picker.js";

describe("Provider secret input", () => {
  it("completes only once when submit input is repeated", () => {
    const done = vi.fn();
    const component = new SecretInputComponent(
      "Provider",
      "TEST_API_KEY",
      { requestRender: vi.fn() } as never,
      { fg: (_color: string, text: string) => text, bold: (text: string) => text } as never,
      {
        matches: (data: string, action: string) => action === "tui.input.submit" && data === "\r",
      } as never,
      done,
    );
    component.handleInput("secret");
    component.handleInput("\r");
    component.handleInput("\r");
    expect(done).toHaveBeenCalledTimes(1);
    expect(done).toHaveBeenCalledWith({ type: "submit", value: "secret" });
  });
});
