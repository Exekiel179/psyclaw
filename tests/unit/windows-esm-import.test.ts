import { describe, expect, it } from "vitest";
import { pathToFileURL } from "node:url";
import { join } from "node:path";
import { toImportSpecifier } from "../../src/chat.js";

describe("Windows ESM --import specifier", () => {
  it("never yields a bare drive-letter protocol", () => {
    const fakeWin = process.platform === "win32"
      ? "C:\\\\Users\\\\demo\\\\AppData\\\\Roaming\\\\npm\\\\node_modules\\\\psyclaw\\\\dist\\\\src\\\\network-routing.js"
      : join("/tmp", "psyclaw", "dist", "src", "network-routing.js");
    const href = toImportSpecifier(fakeWin);
    expect(href).toBe(pathToFileURL(fakeWin).href);
    expect(href.startsWith("file:")).toBe(true);
    expect(/^c:/i.test(href)).toBe(false);
  });
});
