import { describe, expect, it } from "vitest";
import { continueSessionArgs, peelContinuouslyWorkFlag, unknownFlagUsage } from "../../src/cli-args.js";
import {
  CONTINUOUSLY_WORK_FLAG,
  continuouslyWorkPrompt,
  continuouslyWorkWarningText,
  isContinuouslyWorkEnabled,
} from "../../src/session/continuously-work.js";
import { formatCliUsage } from "../../src/style/cli-ui.js";

describe("continueSessionArgs", () => {
  it("forwards both continuation aliases and trailing Pi arguments", () => {
    expect(continueSessionArgs("--continue", ["Follow up"])).toEqual(["--continue", "Follow up"]);
    expect(continueSessionArgs("-c", [])).toEqual(["-c"]);
  });

  it("does not claim other CLI commands", () => {
    expect(continueSessionArgs("chat", ["--continue"])).toBeUndefined();
    expect(continueSessionArgs("--continue-work", [])).toBeUndefined();
    expect(continueSessionArgs(undefined, [])).toBeUndefined();
  });
});

describe("peelContinuouslyWorkFlag", () => {
  it("strips the canonical launch flag and reports enabled", () => {
    expect(peelContinuouslyWorkFlag(["--continuously-work", "chat", "--provider", "x"])).toEqual({
      enabled: true,
      args: ["chat", "--provider", "x"],
    });
    expect(peelContinuouslyWorkFlag(["chat", CONTINUOUSLY_WORK_FLAG])).toEqual({
      enabled: true,
      args: ["chat"],
    });
  });

  it("accepts the --continue-work alias that production treated as a command", () => {
    expect(peelContinuouslyWorkFlag(["--continue-work"])).toEqual({
      enabled: true,
      args: [],
    });
    expect(peelContinuouslyWorkFlag(["--continue-work", "--continue"])).toEqual({
      enabled: true,
      args: ["--continue"],
    });
    expect(peelContinuouslyWorkFlag(["chat", "--continuous-work"])).toEqual({
      enabled: true,
      args: ["chat"],
    });
  });

  it("leaves session resume flags alone when continuously-work is absent", () => {
    expect(peelContinuouslyWorkFlag(["--continue", "hi"])).toEqual({
      enabled: false,
      args: ["--continue", "hi"],
    });
  });

  it("is launch-only, not a Shift+Tab session mode", () => {
    expect(isContinuouslyWorkEnabled({ PSYCLAW_CONTINUOUSLY_WORK: "1" })).toBe(true);
    expect(isContinuouslyWorkEnabled({})).toBe(false);
    expect(continuouslyWorkWarningText()).toMatch(/token/i);
    expect(continuouslyWorkPrompt()).toMatch(/psyclaw --continuously-work/);
  });
});

describe("unknownFlagUsage", () => {
  it("points leftover dash tokens at continue and continuously-work without Unknown command", () => {
    const text = unknownFlagUsage("--continue-work");
    expect(text).toContain("无法识别选项 --continue-work");
    expect(text).toContain("psyclaw --continue");
    expect(text).toContain("psyclaw --continuously-work");
    expect(text).toContain("--continue-work");
    expect(text).not.toMatch(/^Unknown command:/);
  });
});

describe("CLI usage copy", () => {
  it("documents session resume and continuously-work aliases", () => {
    const usage = formatCliUsage();
    expect(usage).toContain("psyclaw --continue");
    expect(usage).toContain("psyclaw --continuously-work");
    expect(usage).toContain("--continue-work");
  });
});
