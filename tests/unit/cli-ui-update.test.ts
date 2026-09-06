import { describe, expect, it } from "vitest";
import { renderProductUpdateSummary } from "../../src/style/cli-ui.js";

describe("renderProductUpdateSummary", () => {
  it("shows before → after on successful upgrade", () => {
    const text = renderProductUpdateSummary({
      ok: true,
      reasonCode: "update-applied",
      commands: ["npm install --global psyclaw@0.28.0"],
      psyclaw: { before: "0.27.23", after: "0.28.0", latest: "0.28.0" },
    });
    expect(text).toContain("升级成功");
    expect(text).toContain("0.27.23 → 0.28.0");
    expect(text).not.toContain("schemaVersion");
  });

  it("shows current version when already up to date", () => {
    const text = renderProductUpdateSummary({
      ok: true,
      reasonCode: "already-up-to-date",
      commands: [],
      psyclaw: { before: "0.28.0", after: "0.28.0", latest: "0.28.0" },
    });
    expect(text).toContain("已是最新");
    expect(text).toContain("0.28.0");
  });

  it("explains source checkout skips without dumping JSON", () => {
    const text = renderProductUpdateSummary({
      ok: true,
      reasonCode: "update-skipped",
      reason: "source checkout detected; refuse npm self-overwrite — sync with Git, then rebuild",
      commands: ["pnpm install", "pnpm build"],
      psyclaw: { before: "0.28.0" },
    });
    expect(text).toContain("源码检出");
    expect(text).toContain("0.28.0");
    expect(text).toContain("pnpm install && pnpm build");
  });
});
