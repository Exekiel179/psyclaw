import { describe, expect, it } from "vitest";
import { pathToFileURL } from "node:url";
import { join } from "node:path";
import { toImportSpecifier } from "../../src/chat.js";

describe("Windows ESM --import specifier", () => {
  it("converts a Windows drive path to a file URL", () => {
    if (process.platform !== "win32") return;

    const windowsPath = String.raw`C:\Users\demo\AppData\Roaming\npm\node_modules\psyclaw\dist\src\network-routing.js`;
    expect(toImportSpecifier(windowsPath)).toBe(
      "file:///C:/Users/demo/AppData/Roaming/npm/node_modules/psyclaw/dist/src/network-routing.js",
    );
  });

  it("preserves file URL conversion for POSIX paths", () => {
    const posixPath = join("/tmp", "psyclaw", "dist", "src", "network-routing.js");
    const href = toImportSpecifier(posixPath);
    expect(href).toBe(pathToFileURL(posixPath).href);
    expect(href.startsWith("file:")).toBe(true);
  });
});
