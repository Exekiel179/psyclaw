import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  assertHumanVerifyGate,
  defaultVerifyChecklist,
  evaluateHumanVerifyGate,
  markVerifyItem,
  resolveVerifyMark,
} from "../../src/verify/checklist.js";

describe("resolveVerifyMark", () => {
  it("coerces AI verified to ai-checked", () => {
    expect(resolveVerifyMark("verified", "ai")).toEqual({ status: "ai-checked", approvedBy: "ai" });
    expect(resolveVerifyMark("verified", "human")).toEqual({ status: "verified", approvedBy: "human" });
    expect(resolveVerifyMark("human", "ai")).toEqual({ status: "verified", approvedBy: "human" });
  });
});

describe("human verify gate", () => {
  it("blocks analysis complete until every pre/post item is human-verified", () => {
    const checklist = defaultVerifyChecklist("2026-01-01T00:00:00.000Z");
    const blocked = evaluateHumanVerifyGate(checklist, "analysis-complete");
    expect(blocked.ok).toBe(false);
    if (!blocked.ok) expect(blocked.pending.length).toBeGreaterThan(0);

    for (const item of checklist.items) {
      if (item.phase === "pre-analysis" || item.phase === "post-analysis") {
        item.status = "verified";
        item.approvedBy = "human";
      }
    }
    expect(evaluateHumanVerifyGate(checklist, "analysis-complete").ok).toBe(true);
  });

  it("does not accept ai-checked or skipped as human approval", () => {
    const checklist = defaultVerifyChecklist("2026-01-01T00:00:00.000Z");
    for (const item of checklist.items) {
      item.status = "ai-checked";
      item.approvedBy = "ai";
    }
    expect(evaluateHumanVerifyGate(checklist, "analysis-complete").ok).toBe(false);
    for (const item of checklist.items) {
      item.status = "skipped";
      item.approvedBy = "human";
    }
    expect(evaluateHumanVerifyGate(checklist, "academic-finalize").ok).toBe(false);
  });

  it("persists AI marks as ai-checked and human marks as verified", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-verify-"));
    try {
      await markVerifyItem(root, "n", "verified", "ai note", "stats", { source: "ai" });
      const afterAi = await assertHumanVerifyGate(root, "analysis-complete");
      expect(afterAi.ok).toBe(false);
      const n = afterAi.checklist.items.find((item) => item.id === "n");
      expect(n?.status).toBe("ai-checked");

      await markVerifyItem(root, "n", "verified", "human ok", "stats", { source: "human" });
      const again = afterAi.checklist.items; // reload via assert
      const reloaded = await assertHumanVerifyGate(root, "analysis-complete");
      expect(reloaded.checklist.items.find((item) => item.id === "n")?.status).toBe("verified");
      expect(again).toBeTruthy();
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});
