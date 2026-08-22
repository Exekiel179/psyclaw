import { describe, expect, it } from "vitest";
import { buildClaimLiteratureMap } from "../../src/panel/literature-map.js";
import { checkPreRegistration } from "../../src/analysis/pre-registration.js";
import { PARADIGM_REPORT_FIELDS, policiesForParadigm } from "../../src/core/evidence-policy.js";

describe("claim literature map", () => {
  it("groups sources per claim and sorts contradictions first", () => {
    const map = buildClaimLiteratureMap(
      [
        { id: "c-1", text: "A claim", kind: "result", status: "supported", evidenceIds: ["e-1", "e-2"] },
      ],
      [
        { id: "e-1", source: { kind: "file", locator: "p1.pdf", title: "Paper One" }, level: "fulltext", retrievedAt: "", accessStatus: "verified", locators: [] },
        { id: "e-2", source: { kind: "file", locator: "p2.pdf" }, level: "abstract", retrievedAt: "", accessStatus: "verified", locators: [] },
      ],
      [
        { claimId: "c-1", evidenceId: "e-1", relation: "supports", rationale: "r" },
        { claimId: "c-1", evidenceId: "e-2", relation: "contradicts", rationale: "r" },
      ],
      "2026-01-01T00:00:00.000Z",
    );
    expect(map.schemaVersion).toBe("psyclaw/literature-map/v1");
    expect(map.claims).toHaveLength(1);
    expect(map.claims[0]!.sources).toHaveLength(2);
    expect(map.claims[0]!.sources[0]!.relation).toBe("contradicts"); // sorted first
    expect(map.claims[0]!.sources[1]!.title).toBe("Paper One");
  });
});

describe("pre-registration gate", () => {
  it("blocks confirmatory analysis without a plan and passes with a complete one", () => {
    const blocked = checkPreRegistration(undefined, "survey-observational");
    expect(blocked.some((gate) => gate.gateId === "analysis:pre-registration" && gate.severity === "block")).toBe(true);

    const ok = checkPreRegistration({
      schemaVersion: "psyclaw/pre-registration/v1",
      confirmatory: true,
      primaryOutcome: "employment anxiety",
      primaryAnalysis: "mediation",
      exploratoryAnalyses: [],
      missingDataPlan: "complete cases",
      multiplicityPlan: "none",
      exclusionCriteria: "attention check",
    }, "survey-observational");
    expect(ok.every((gate) => gate.severity !== "block")).toBe(true);
  });

  it("does not require numeric pre-registration for qualitative paradigms", () => {
    expect(checkPreRegistration(undefined, "qualitative-thematic")).toEqual([]);
    expect(checkPreRegistration(undefined, "ethnographic")).toEqual([]);
  });
});

describe("paradigm profile deepening", () => {
  it("meta-analysis requires full text for method and result", () => {
    const policies = policiesForParadigm("meta-analysis");
    expect(policies.find((p) => p.claimKind === "method")!.minimumLevel).toBe("fulltext");
    expect(policies.find((p) => p.claimKind === "result")!.minimumLevel).toBe("fulltext");
  });

  it("keeps the independent-source gate for survey interpretation", () => {
    const policies = policiesForParadigm("survey-observational");
    expect(policies.find((p) => p.claimKind === "interpretation")!.requiresIndependentSource).toBe(true);
  });

  it("relaxes independent sources for qualitative and documentary results", () => {
    for (const paradigm of ["qualitative-thematic", "ethnographic", "historical-documentary", "policy-legal"] as const) {
      const policies = policiesForParadigm(paradigm);
      expect(policies.find((p) => p.claimKind === "result")!.requiresIndependentSource).toBe(false);
    }
  });

  it("declares required report fields for every paradigm", () => {
    const paradigms = Object.keys(PARADIGM_REPORT_FIELDS);
    expect(paradigms.length).toBeGreaterThanOrEqual(9);
    expect(PARADIGM_REPORT_FIELDS["meta-analysis"]).toContain("PRISMA 流程");
    expect(PARADIGM_REPORT_FIELDS["qualitative-thematic"]).toContain("研究者立场与反身性");
  });
});
