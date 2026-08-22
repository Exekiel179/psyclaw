import { describe, expect, it } from "vitest";
import { agentTableLines, renderTable } from "../../src/tui/model.js";

describe("tui table model", () => {
  it("renders aligned monospace rows", () => {
    const lines = renderTable(
      ["name", "status"],
      [["Claude Code", "found"], ["x", "not found"]],
    );
    // header + divider + two data rows
    expect(lines).toHaveLength(4);
    expect(lines[0]).toContain("name");
    expect(lines[0]).toContain("status");
    // header and divider share the same column widths
    expect(lines[0]!.length).toBe(lines[1]!.length);
    expect(lines[2]).toContain("Claude Code");
  });

  it("builds agent table lines from scans", () => {
    const lines = agentTableLines([
      { id: "a", name: "Agent A", found: true, configPath: "/home/.a", skills: [{ name: "s1", path: "/p", kind: "dir" }], skillDirs: [], hasCredentials: true, credentialPaths: [], install: { method: "npm", installCommand: "npm i -g a", sourceRef: "x" } },
      { id: "b", name: "B", found: false, skills: [], skillDirs: [], hasCredentials: false, credentialPaths: [] },
    ]);
    expect(lines).toHaveLength(4);
    expect(lines[0]).toContain("name");
    expect(lines[2]).toContain("Agent A");
    expect(lines[2]).toContain("found");
    expect(lines[2]).toContain("npm");
  });
});
