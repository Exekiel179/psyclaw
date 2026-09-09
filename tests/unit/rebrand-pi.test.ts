import { describe, expect, it } from "vitest";
import { restoreManagedToolDownloads, applyFooterPatchesToContent } from "../../scripts/rebrand-pi.mjs";

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

describe("Pi footer branding", () => {
  const SAMPLE_FOOTER = `
        else {
            contextPercentStr = contextPercentDisplay;
        }
        statsParts.push(contextPercentStr);
        if (areExperimentalFeaturesEnabled()) {
        const lines = [pwdLine, dimStatsLeft + dimRemainder];
        // Add extension statuses on a single line, sorted by key alphabetically
        const extensionStatuses = this.footerData.getExtensionStatuses();
        if (extensionStatuses.size > 0) {
            const sortedStatuses = Array.from(extensionStatuses.entries())
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([, text]) => sanitizeStatusText(text));
            const statusLine = sortedStatuses.join(" ");
            // Truncate to terminal width with dim ellipsis for consistency with footer style
            lines.push(truncateToWidth(statusLine, width, theme.fg("dim", "...")));
        }
        return lines;
`;

  it("inlines mode status next to auto indicator and filters it from extra status line", () => {
    const result = applyFooterPatchesToContent(SAMPLE_FOOTER);
    expect(result.applied).toBe(true);
    expect(result.appliedCount).toBe(2);
    expect(result.content).toContain('this.footerData.getExtensionStatuses().get("mode")');
    expect(result.content).toContain('filter(([key]) => key !== "mode")');
  });

  it("is idempotent when already applied", () => {
    const first = applyFooterPatchesToContent(SAMPLE_FOOTER);
    const second = applyFooterPatchesToContent(first.content);
    expect(second.applied).toBe(false);
    expect(second.appliedCount).toBe(0);
    expect(second.content).toBe(first.content);
  });
});
