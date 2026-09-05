import { afterEach, describe, expect, it } from "vitest";
import {
  continueSessionArgs,
  developerCommandsEnabled,
  enableDeveloperCommands,
  extractDeveloperFlag,
} from "../../src/cli-args.js";

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

describe("extractDeveloperFlag", () => {
  afterEach(() => {
    delete process.env.PSYCLAW_DEVELOPER_COMMANDS;
  });

  it("strips --developer and -D from argv", () => {
    expect(extractDeveloperFlag(["--developer", "chat", "--provider", "x"])).toEqual({
      developer: true,
      rest: ["chat", "--provider", "x"],
    });
    expect(extractDeveloperFlag(["-D", "--continue"])).toEqual({
      developer: true,
      rest: ["--continue"],
    });
    expect(extractDeveloperFlag(["chat"])).toEqual({
      developer: false,
      rest: ["chat"],
    });
  });

  it("enables gated developer commands via env", () => {
    expect(developerCommandsEnabled()).toBe(false);
    enableDeveloperCommands();
    expect(developerCommandsEnabled()).toBe(true);
    expect(process.env.PSYCLAW_DEVELOPER_COMMANDS).toBe("1");
  });
});
