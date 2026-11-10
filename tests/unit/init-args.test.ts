import { describe, expect, it } from "vitest";
import { INIT_USAGE, parseInitArgs } from "../../src/adapters/pi/init-args.js";
import { isExpectedUserErrorMessage } from "../../src/observability/expected.js";

describe("parseInitArgs", () => {
  it("treats a missing goal as optional scaffold args without throwing", () => {
    expect(parseInitArgs("")).toEqual({ ok: true });
    expect(parseInitArgs("   ")).toEqual({ ok: true });
  });

  it("parses a trailing research goal", () => {
    expect(parseInitArgs("睡眠质量与学业倦怠")).toEqual({
      ok: true,
      paradigm: "survey-observational",
      goal: "睡眠质量与学业倦怠",
    });
  });

  it("parses /init --paradigm <profile> <goal>", () => {
    expect(parseInitArgs("--paradigm qualitative-thematic A bounded goal")).toEqual({
      ok: true,
      paradigm: "qualitative-thematic",
      goal: "A bounded goal",
    });
  });

  it("returns usage for --paradigm without a research goal", () => {
    expect(parseInitArgs("--paradigm survey-observational")).toEqual({
      ok: false,
      message: INIT_USAGE,
    });
    expect(parseInitArgs("--paradigm")).toEqual({ ok: false, message: INIT_USAGE });
  });

  it("returns usage for unknown flags instead of treating them as a goal", () => {
    expect(parseInitArgs("--nope")).toEqual({ ok: false, message: INIT_USAGE });
    expect(parseInitArgs("--paradigm not-a-paradigm some goal")).toEqual({
      ok: false,
      message: `Unsupported paradigm: not-a-paradigm\n${INIT_USAGE}`,
    });
  });

  it("keeps the usage hint in the expected-user-error class used by telemetry filters", () => {
    expect(INIT_USAGE.startsWith("Usage:")).toBe(true);
    expect(isExpectedUserErrorMessage(INIT_USAGE)).toBe(true);
  });
});
