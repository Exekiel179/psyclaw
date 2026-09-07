import { describe, expect, it } from "vitest";
import { continueSessionArgs, peelContinuouslyWorkFlag } from "../../src/cli-args.js";
import {
  CONTINUOUSLY_WORK_FLAG,
  continuouslyWorkPrompt,
  continuouslyWorkWarningText,
  isContinuouslyWorkEnabled,
} from "../../src/session/continuously-work.js";
import { SESSION_MODES } from "../../src/session/modes.js";

describe("continueSessionArgs", () => {
  it("forwards both continuation aliases and trailing Pi arguments", () => {
    expect(continueSessionArgs("--continue", ["Follow up"])).toEqual(["--continue", "Follow up"]);
    expect(continueSessionArgs("-c", [])).toEqual(["-c"]);
  });

  it("does not claim other CLI commands", () => {
    expect(continueSessionArgs("chat", ["--continue"])).toBeUndefined();
    expect(continueSessionArgs(undefined, [])).toBeUndefined();
  });
});

describe("peelContinuouslyWorkFlag", () => {
  it("strips the launch flag and reports enabled", () => {
    expect(peelContinuouslyWorkFlag(["--continuously-work", "chat", "--provider", "x"])).toEqual({
      enabled: true,
      args: ["chat", "--provider", "x"],
    });
    expect(peelContinuouslyWorkFlag(["chat", CONTINUOUSLY_WORK_FLAG])).toEqual({
      enabled: true,
      args: ["chat"],
    });
  });

  it("leaves other args alone when the flag is absent", () => {
    expect(peelContinuouslyWorkFlag(["--continue", "hi"])).toEqual({
      enabled: false,
      args: ["--continue", "hi"],
    });
  });

  it("is not a Shift+Tab session mode", () => {
    expect(SESSION_MODES).not.toContain("continuously-work");
    expect(isContinuouslyWorkEnabled({ PSYCLAW_CONTINUOUSLY_WORK: "1" })).toBe(true);
    expect(isContinuouslyWorkEnabled({})).toBe(false);
    expect(continuouslyWorkWarningText()).toMatch(/token/i);
    expect(continuouslyWorkWarningText()).toMatch(/不确保产出物质量/);
    expect(continuouslyWorkPrompt()).toMatch(/psyclaw --continuously-work/);
    expect(continuouslyWorkPrompt()).not.toMatch(/Shift\+Tab.*continuously/i);
  });
});
