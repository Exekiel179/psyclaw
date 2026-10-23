import { describe, expect, it } from "vitest";
import { maskToolObservations, maskToolObservationsStable, type MaskableMessage } from "../../src/adapters/pi/observation-mask.js";

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

function payload(messages: readonly MaskableMessage[]): string {
  return messages.map((message) => {
    if (message.role === "toolResult") return `T:${text(message)}`;
    const content = message.content;
    return `${message.role}:${typeof content === "string" ? content : ""}`;
  }).join("\n");
}

function commonPrefix(left: string, right: string): number {
  const limit = Math.min(left.length, right.length);
  let index = 0;
  while (index < limit && left.charCodeAt(index) === right.charCodeAt(index)) index += 1;
  return index;
}

function replay(mask: (messages: MaskableMessage[]) => MaskableMessage[]): { sent: number; hit: number; miss: number; hitRate: number } {
  const figure = `FIGURE\n${"row,value\n".repeat(700)}`;
  const history: MaskableMessage[] = [{ role: "user", content: "analyze the study" }];
  let previous = "";
  let sent = 0;
  let hit = 0;
  let miss = 0;
  for (let step = 0; step < 16; step += 1) {
    const body = step === 3 || step === 10 ? figure : `STEP ${step}\n${"x".repeat(7_000)}TAIL ${step}`;
    history.push({ role: "assistant", content: `run ${step}` });
    history.push(tool("bash", body));
    const current = payload(mask([...history]));
    const prefix = commonPrefix(previous, current);
    sent += current.length;
    hit += prefix;
    miss += current.length - prefix;
    previous = current;
  }
  return { sent, hit, miss, hitRate: hit / sent };
}

describe("stable observation mask", () => {
  it("clips a seen result once and leaves that clip unchanged on the next turn", () => {
    const big = `${"A".repeat(5_000)}END`;
    const seen = maskToolObservationsStable([
      { role: "user", content: "go" },
      { role: "assistant", content: "1" },
      tool("bash", big),
      { role: "assistant", content: "2" },
      tool("bash", "small-2"),
    ]);
    const later = maskToolObservationsStable([
      { role: "user", content: "go" },
      { role: "assistant", content: "1" },
      tool("bash", big),
      { role: "assistant", content: "2" },
      tool("bash", "small-2"),
      { role: "assistant", content: "3" },
      tool("bash", "small-3"),
    ]);
    expect(text(seen[2])).toContain("psyclaw:observation-masked omitted");
    expect(text(seen[2]).endsWith("END")).toBe(true);
    expect(text(later[2])).toBe(text(seen[2]));
    expect(text(seen[4])).toBe("small-2");
    expect(text(later[4])).toBe("small-2");
    expect(text(later.at(-1))).toBe("small-3");
  });

  it("keeps a settled confirmatory table, including its middle", () => {
    const middle = `${"M".repeat(2_000)}BETA 0.42${"M".repeat(2_000)}`;
    const masked = maskToolObservationsStable([
      { role: "assistant", content: "1" },
      tool("psyclaw_read_results", middle),
      { role: "assistant", content: "2" },
      tool("bash", "next"),
    ]);
    expect(text(masked[1])).toBe(middle);
    expect(text(masked[1])).toContain("BETA 0.42");
  });

  it("stubs the new duplicate and keeps the earlier result", () => {
    const body = "Z".repeat(4_000);
    const masked = maskToolObservationsStable([
      { role: "assistant", content: "1" },
      tool("bash", body),
      { role: "assistant", content: "2" },
      tool("bash", body),
    ]);
    expect(text(masked[1])).toContain("ZZZ");
    expect(text(masked[3])).toContain("duplicate bash omitted");
    expect(text(masked[3])).not.toContain("ZZZ");
  });

  it("keeps a longer cache prefix than the sliding window on a 16-call trajectory", () => {
    const sliding = replay(maskToolObservations);
    const stable = replay(maskToolObservationsStable);
    console.log(`observation-mask comparison chars sent=${sliding.sent}->${stable.sent} cacheHit=${sliding.hit}->${stable.hit} cacheMiss=${sliding.miss}->${stable.miss} hitRate=${sliding.hitRate.toFixed(3)}->${stable.hitRate.toFixed(3)}`);
    expect(stable.sent).toBeLessThan(sliding.sent);
    expect(stable.miss).toBeLessThan(sliding.miss);
    expect(stable.hitRate).toBeGreaterThan(sliding.hitRate);
  });
});
