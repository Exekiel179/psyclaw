import { describe, expect, it } from "vitest";
import { asEvidence, asProject, asToolReceipt, validators } from "../../src/core/schemas.js";

describe("boundary schemas", () => {
  it("accepts the project and receipt contracts", () => {
    expect(validators.researchProject.check({
      id: "p1",
      root: "C:/project",
      paradigm: "survey-observational",
      goal: "A goal",
      policyVersion: "psyclaw/core/v1",
      createdAt: "2026-01-01T00:00:00.000Z",
    })).toBe(true);
    expect(validators.toolReceipt.check({
      schemaVersion: "psyclaw/tool-receipt/v1",
      runId: "r1",
      taskId: "t1",
      tool: "read",
      effect: "read",
      approval: "not-needed",
      ok: true,
      reasonCode: "fixture.ok",
      startedAt: "now",
      finishedAt: "now",
    })).toBe(true);
  });

  it("rejects unknown fields and malformed hashes", () => {
    expect(validators.researchProject.check({
      id: "p1",
      root: "C:/project",
      paradigm: "survey-observational",
      goal: "A goal",
      policyVersion: "psyclaw/core/v1",
      createdAt: "now",
      unexpected: true,
    })).toBe(false);
    expect(validators.evidence.check({
      id: "e1",
      source: { kind: "file", locator: "x" },
      level: "fulltext",
      retrievedAt: "now",
      sha256: "bad",
      accessStatus: "verified",
      locators: [],
    })).toBe(false);
  });

  it("throws a useful error at the boundary", () => {
    expect(() => asProject({})).toThrow("researchProject schema invalid");
    expect(() => asEvidence({})).toThrow("evidence schema invalid");
    expect(() => asToolReceipt({})).toThrow("toolReceipt schema invalid");
  });
});
