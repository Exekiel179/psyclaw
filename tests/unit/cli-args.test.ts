import { describe, expect, it } from "vitest";
import { continueSessionArgs } from "../../src/cli-args.js";

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
