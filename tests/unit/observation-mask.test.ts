import { describe, expect, it } from "vitest";
import { maskToolObservations, type MaskableMessage } from "../../src/adapters/pi/observation-mask.js";

function tool(toolName: string, text: string, isError = false): MaskableMessage {
  return { role: "toolResult", toolName, isError, content: [{ type: "text", text }] };
}

function text(message: MaskableMessage | undefined): string {
  const content = message?.content;
  if (!Array.isArray(content)) return "";
  const part = content.find((item) => item && typeof item === "object" && item.type === "text");
  return part && typeof part === "object" && "text" in part && typeof part.text === "string" ? part.text : "";
}

describe("maskToolObservations", () => {
  it("leaves a short recent trajectory unchanged", () => {
    const messages = [
      { role: "user", content: "run the model" },
      tool("bash", "n = 659"),
      tool("read", "beta = 0.05"),
    ];
    expect(maskToolObservations(messages)).toBe(messages);
  });

  it("keeps the tail of an old tool result and the latest result intact", () => {
    const old = `${"A".repeat(3_000)}RESULT 0.051`;
    const latest = "p = .010";
    const messages = [
      tool("bash", old),
      ...Array.from({ length: 6 }, (_, index) => tool("bash", `step ${index}`)),
      tool("bash", latest),
    ];
    const masked = maskToolObservations(messages);
    expect(masked).not.toBe(messages);
    expect(text(masked[0])).toContain("psyclaw:observation-masked omitted");
    expect(text(masked[0]).endsWith("RESULT 0.051")).toBe(true);
    expect(text(masked[0]).length).toBeLessThan(old.length);
    expect(text(masked.at(-1))).toBe(latest);
    expect(masked[1]).toBe(messages[1]);
  });

  it("sends only the later copy of an identical tool result", () => {
    const body = "figure written\n".repeat(400);
    const messages = [
      tool("bash", body),
      tool("bash", "edited 60_figures.R"),
      tool("bash", body),
    ];
    const masked = maskToolObservations(messages, { keepRecent: 6 });
    expect(text(masked[0])).toContain("duplicate bash omitted");
    expect(text(masked[0])).not.toContain("figure written");
    expect(text(masked[2])).toBe(body);
    expect(maskToolObservations(masked, { keepRecent: 6 })[2]).toBe(masked[2]);
  });

  it("keeps an error even when its text matches a later success", () => {
    const body = "exit 1";
    const messages = [tool("bash", body, true), tool("bash", body, false)];
    expect(maskToolObservations(messages)).toBe(messages);
  });

  it("caps an oversized recent result without dropping its ending", () => {
    const body = `${"H".repeat(20_000)}p = .012`;
    const masked = maskToolObservations([tool("Rscript", body)], { recentChars: 1_000 });
    const kept = text(masked[0]);
    expect(kept.endsWith("p = .012")).toBe(true);
    expect(kept.length).toBeLessThan(body.length);
    expect(maskToolObservations(masked, { recentChars: 1_000 })).toBe(masked);
  });
});
