import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { delimiter, join } from "node:path";
import { describe, expect, it } from "vitest";
import { bundledWindowsToolsDir, withBundledWindowsTools } from "../../src/bundled-tools.js";

describe("bundled Windows search tools", () => {
  it("prepends a complete architecture bundle to PATH", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-tools-"));
    const directory = join(root, "vendor", "windows", "x64");
    try {
      await mkdir(directory, { recursive: true });
      await Promise.all([
        writeFile(join(directory, "fd.exe"), "fixture"),
        writeFile(join(directory, "rg.exe"), "fixture"),
      ]);
      expect(bundledWindowsToolsDir(root, "win32", "x64")).toBe(directory);
      expect(withBundledWindowsTools({ PATH: "C:\\Windows" }, root, "win32", "x64").PATH)
        .toBe(`${directory}${delimiter}C:\\Windows`);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("does not advertise an incomplete or unsupported bundle", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-tools-"));
    try {
      expect(bundledWindowsToolsDir(root, "win32", "x64")).toBeUndefined();
      expect(bundledWindowsToolsDir(root, "linux", "x64")).toBeUndefined();
      expect(bundledWindowsToolsDir(root, "win32", "ia32")).toBeUndefined();
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});
