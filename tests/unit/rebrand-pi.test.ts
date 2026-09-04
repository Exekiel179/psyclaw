import { describe, expect, it } from "vitest";
import { restoreManagedToolDownloads } from "../../scripts/rebrand-pi.mjs";

const PI_TOOL_MANAGER = `export async function ensureTool(tool, onStatus) {
    const existingPath = getToolPath(tool);
    if (existingPath) {
        return existingPath;
    }
    const config = TOOLS[tool];
    onStatus?.({ type: "info", message: \`Downloading \${config.name}\` });
}`;

describe("Pi managed-tool repair", () => {
  it("leaves the official installation rule unchanged", () => {
    expect(restoreManagedToolDownloads(PI_TOOL_MANAGER)).toEqual({ content: PI_TOOL_MANAGER, applied: false });
  });

  it("removes the 0.27.20 early-return guard", () => {
    const polluted = PI_TOOL_MANAGER.replace(
      "    const config = TOOLS[tool];",
      "    // PsyClaw supplies Node-based find/grep fallbacks. Keep PATH tools when\n    // present, but never fetch optional binaries from GitHub during startup.\n    return undefined;\n    const config = TOOLS[tool];",
    );
    const repaired = restoreManagedToolDownloads(polluted);
    expect(repaired).toEqual({ content: PI_TOOL_MANAGER, applied: true });
  });
});
