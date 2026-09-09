import { describe, expect, it } from "vitest";
import { resolveWindowsSpawn, useWindowsPackageManagerShell } from "../../src/platform/windows-spawn.js";

describe("windows-spawn", () => {
  it("leaves argv unchanged on non-Windows platforms", () => {
    expect(resolveWindowsSpawn("npx", ["-y", "@drawio/mcp"], "darwin")).toEqual({
      command: "npx",
      args: ["-y", "@drawio/mcp"],
    });
    expect(useWindowsPackageManagerShell("linux")).toBe(false);
  });

  it("wraps PATH shims through cmd.exe on Windows", () => {
    const resolved = resolveWindowsSpawn("npx", ["-y", "@drawio/mcp@1.5.0"], "win32", "C:\\\\Windows\\\\System32\\\\cmd.exe");
    expect(resolved.command).toBe("C:\\\\Windows\\\\System32\\\\cmd.exe");
    expect(resolved.args).toEqual(["/d", "/c", "npx", "-y", "@drawio/mcp@1.5.0"]);
    expect(useWindowsPackageManagerShell("win32")).toBe(true);
  });

  it("does not wrap absolute or extension-qualified executables", () => {
    expect(resolveWindowsSpawn("C:\\\\Tools\\\\npx.cmd", ["-y", "pkg"], "win32")).toEqual({
      command: "C:\\\\Tools\\\\npx.cmd",
      args: ["-y", "pkg"],
    });
    expect(resolveWindowsSpawn("node.exe", ["--version"], "win32")).toEqual({
      command: "node.exe",
      args: ["--version"],
    });
  });
});
