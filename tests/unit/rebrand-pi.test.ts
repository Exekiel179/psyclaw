import { describe, expect, it } from "vitest";
import { disableManagedToolDownloads } from "../../scripts/rebrand-pi.mjs";

const PI_TOOL_MANAGER = `export async function ensureTool(tool, onStatus) {
    const existingPath = getToolPath(tool);
    if (existingPath) {
        return existingPath;
    }
    const config = TOOLS[tool];
    onStatus?.({ type: "info", message: \`Downloading \${config.name}\` });
}`;

describe("Pi managed-tool patch", () => {
  it("keeps PATH tools and returns before optional downloads", () => {
    const result = disableManagedToolDownloads(PI_TOOL_MANAGER);

    expect(result.applied).toBe(true);
    expect(result.content).toContain("return existingPath;");
    expect(result.content.indexOf("return undefined;")).toBeLessThan(result.content.indexOf("const config"));
  });

  it("is idempotent", () => {
    const once = disableManagedToolDownloads(PI_TOOL_MANAGER);
    const twice = disableManagedToolDownloads(once.content);

    expect(twice).toEqual({ content: once.content, applied: false });
  });
});
