import { describe, expect, it } from "vitest";
import { checkEvidenceSufficiency } from "../../src/core/evidence-policy.js";
import { asEvidence } from "../../src/core/schemas.js";
import type { Claim, ClaimEvidenceLink, Evidence } from "../../src/core/contracts.js";

const claim = (kind: Claim["kind"], evidenceIds: string[] = ["e-1"]): Claim => ({
  id: "c-1",
  text: "A bounded claim",
  kind,
  evidenceIds,
  status: "supported",
});

const evidence = (overrides: Partial<Evidence> = {}): Evidence => ({
  id: "e-1",
  source: { kind: "file", locator: "notes/source.md" },
  level: "abstract",
  retrievedAt: "2026-01-01T00:00:00.000Z",
  accessStatus: "verified",
  locators: [{ kind: "section", value: "Abstract" }],
  ...overrides,
});

const link = (overrides: Partial<ClaimEvidenceLink> = {}): ClaimEvidenceLink => ({
  claimId: "c-1",
  evidenceId: "e-1",
  relation: "supports",
  rationale: "The source states the claim.",
  ...overrides,
});

describe("evidence integrity hard fails", () => {
  it("blocks an unsupported claim with no evidence", () => {
    const [result] = checkEvidenceSufficiency({
      claims: [claim("definition", [])],
      evidence: [],
      links: [],
    });
    expect(result?.ok).toBe(false);
    expect(result?.reason).toMatch(/支持证据|等级/);
  });

  it("blocks citation metadata-only as a definition", () => {
    const [result] = checkEvidenceSufficiency({
      claims: [claim("definition")],
      evidence: [evidence({ level: "metadata", locators: [{ kind: "doi", value: "10.0000/x" }] })],
      links: [link()],
    });
    expect(result?.ok).toBe(false);
    expect(result?.reason).toContain("等级");
  });

  it("blocks conflicting studies rather than silently picking a direction", () => {
    const snippet = {
      level: "snippet" as const,
      quote: "Exact text",
      locators: [{ kind: "section", value: "Results" }],
    };
    const [result] = checkEvidenceSufficiency({
      claims: [{ ...claim("interpretation"), evidenceIds: ["e-1", "e-2"] }],
      evidence: [
        evidence({ ...snippet, id: "e-1" }),
        evidence({ ...snippet, id: "e-2", source: { kind: "file", locator: "notes/other.md" } }),
      ],
      links: [link(), { claimId: "c-1", evidenceId: "e-2", relation: "contradicts", rationale: "opposite" }],
    });
    expect(result?.ok).toBe(false);
    expect(result?.reason).toContain("矛盾");
  });

  it("rejects evidence with a missing or malformed source field at the schema boundary", () => {
    expect(() => asEvidence({
      id: "e-1",
      source: { kind: "doi", locator: "" },
      level: "metadata",
      retrievedAt: "2026-01-01T00:00:00.000Z",
      accessStatus: "verified",
      locators: [],
    })).toThrow(/schema invalid/);
  });

  it("treats a fake PDF/HTML full-text as unverifiable rather than trusted", () => {
    // A fulltext record must carry a SHA and a page/section/row locator;
    // without them it cannot qualify even though accessStatus claims verified.
    const [result] = checkEvidenceSufficiency({
      claims: [claim("result")],
      evidence: [evidence({
        level: "fulltext",
        source: { kind: "file", locator: "downloads/paper.pdf" },
        locators: [{ kind: "file", value: "downloads/paper.pdf" }],
      })],
      links: [link()],
    });
    expect(result?.ok).toBe(false);
  });
});

describe("social-science paradigm profiles", () => {
  it("lets a single located snippet support a qualitative interpretation", () => {
    const [result] = checkEvidenceSufficiency({
      paradigm: "qualitative-thematic",
      claims: [claim("interpretation")],
      evidence: [evidence({ level: "snippet", quote: "Coded excerpt", locators: [{ kind: "section", value: "Theme A" }] })],
      links: [link()],
    });
    expect(result?.ok).toBe(true);
  });

  it("still requires two independent sources for a survey interpretation", () => {
    const [result] = checkEvidenceSufficiency({
      paradigm: "survey-observational",
      claims: [claim("interpretation")],
      evidence: [evidence({ level: "snippet", quote: "Coded excerpt", locators: [{ kind: "section", value: "Theme A" }] })],
      links: [link()],
    });
    expect(result?.ok).toBe(false);
    expect(result?.reason).toContain("两个独立");
  });

  it("does not demand a numeric artifact run for a qualitative result", () => {
    const [qualitative] = checkEvidenceSufficiency({
      paradigm: "qualitative-thematic",
      claims: [claim("result")],
      evidence: [evidence({
        level: "fulltext",
        sha256: "a".repeat(64),
        locators: [{ kind: "section", value: "Findings" }],
      })],
      links: [link()],
    });
    expect(qualitative?.ok).toBe(true);

    const [survey] = checkEvidenceSufficiency({
      paradigm: "survey-observational",
      claims: [claim("result")],
      evidence: [evidence({
        level: "fulltext",
        sha256: "a".repeat(64),
        locators: [{ kind: "section", value: "Findings" }],
      })],
      links: [link()],
    });
    expect(survey?.ok).toBe(false);
    expect(survey?.reason).toContain("真实运行产物");
  });
});
