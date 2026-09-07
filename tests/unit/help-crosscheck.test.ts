import { describe, expect, it } from "vitest";
import { formatSessionHelp, sessionHelpDocument } from "../../src/session/help.js";
import { formatCliUsage } from "../../src/style/cli-ui.js";

describe("session help", () => {
  it("describes AI crosscheck plus mandatory human approval", () => {
    const doc = sessionHelpDocument();
    expect(doc.steps.some((step) => /AI.*\/crosscheck|\/crosscheck/.test(step))).toBe(true);
    expect(doc.steps.some((step) => /强制人审|人审/.test(step))).toBe(true);
    expect(doc.commands.find((row) => row.cmd === "/crosscheck")?.blurb).toMatch(/AI|人审/);
    expect(doc.notes.some((note) => /人审/.test(note))).toBe(true);
    expect(formatSessionHelp()).toMatch(/人审|核实/);
  });
});

describe("cli usage", () => {
  it("lists crosscheck and continuously-work", () => {
    const text = formatCliUsage();
    expect(text).toContain("/crosscheck");
    expect(text).toMatch(/AI 核查|人审/);
    expect(text).toContain("--continuously-work");
    expect(text).toContain("/ars");
  });
});
