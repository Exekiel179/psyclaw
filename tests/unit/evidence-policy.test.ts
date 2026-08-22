import { describe, expect, it } from "vitest";
import { checkEvidenceSufficiency } from "../../src/core/evidence-policy.js";
import type { Claim, ClaimEvidenceLink, Evidence } from "../../src/core/contracts.js";

const claim = (kind: Claim["kind"] = "definition"): Claim => ({
  id: "claim-1",
  text: "A bounded claim",
  kind,
  evidenceIds: ["e-1"],
  status: "supported",
});

const evidence = (overrides: Partial<Evidence> = {}): Evidence => ({
  id: "e-1",
  source: { kind: "file", locator: "notes/source.md", title: "Source" },
  level: "abstract",
  retrievedAt: "2026-01-01T00:00:00.000Z",
  accessStatus: "verified",
  locators: [{ kind: "section", value: "Abstract" }],
  ...overrides,
});

const link = (overrides: Partial<ClaimEvidenceLink> = {}): ClaimEvidenceLink => ({
  claimId: "claim-1",
  evidenceId: "e-1",
  relation: "supports",
  rationale: "The source states the claim.",
  ...overrides,
});

describe("checkEvidenceSufficiency", () => {
  it("accepts an abstract-level definition with a locator", () => {
    const [result] = checkEvidenceSufficiency({
      claims: [claim()],
      evidence: [evidence()],
      links: [link()],
    });
    expect(result?.ok).toBe(true);
  });

  it("blocks a snippet without an exact quote", () => {
    const [result] = checkEvidenceSufficiency({
      claims: [claim("method")],
      evidence: [evidence({ level: "snippet" })],
      links: [link()],
    });
    expect(result?.ok).toBe(false);
    expect(result?.reason).toContain("等级");
  });

  it("blocks full text without a hash", () => {
    const [result] = checkEvidenceSufficiency({
      claims: [claim("result")],
      evidence: [evidence({ level: "fulltext" })],
      links: [link()],
      artifactRunClaimIds: new Set(["claim-1"]),
    });
    expect(result?.ok).toBe(false);
    expect(result?.reason).toContain("等级");
  });

  it("blocks full text with a malformed hash", () => {
    const [result] = checkEvidenceSufficiency({
      claims: [claim("result")],
      evidence: [evidence({ level: "fulltext", sha256: "not-a-sha256" })],
      links: [link()],
      artifactRunClaimIds: new Set(["claim-1"]),
    });
    expect(result?.ok).toBe(false);
  });

  it("blocks result claims without an artifact run", () => {
    const [result] = checkEvidenceSufficiency({
      claims: [claim("result")],
      evidence: [evidence({ level: "fulltext", sha256: "abc" })],
      links: [link()],
    });
    expect(result?.ok).toBe(false);
    expect(result?.reason).toContain("真实运行产物");
  });

  it("blocks unresolved contradiction and missing evidence IDs", () => {
    const results = checkEvidenceSufficiency({
      claims: [claim()],
      evidence: [evidence()],
      links: [link({ relation: "contradicts" }), link({ evidenceId: "missing" })],
    });
    expect(results[0]?.ok).toBe(false);
    expect(results[0]?.reason).toContain("矛盾");
    expect(results[0]?.reason).toContain("不存在");
  });

  it("requires two sources for interpretation claims by default", () => {
    const [result] = checkEvidenceSufficiency({
      claims: [claim("interpretation")],
      evidence: [evidence({ level: "snippet", quote: "Exact text" })],
      links: [link()],
    });
    expect(result?.ok).toBe(false);
    expect(result?.reason).toContain("两个独立");
  });

  it("does not treat user-provided evidence as verified support", () => {
    const [result] = checkEvidenceSufficiency({
      claims: [claim()],
      evidence: [evidence({
        level: "user",
        source: { kind: "user", locator: "researcher-note" },
        accessStatus: "verified",
      })],
      links: [link()],
    });
    expect(result?.ok).toBe(false);
    expect(result?.reason).toContain("用户提供");
  });

  it("requires precise locators for snippets and full text", () => {
    const [snippet] = checkEvidenceSufficiency({
      claims: [claim("method")],
      evidence: [evidence({ level: "snippet", quote: "Exact text", locators: [{ kind: "file", value: "source.md" }] })],
      links: [link()],
    });
    expect(snippet?.ok).toBe(false);

    const [fulltext] = checkEvidenceSufficiency({
      claims: [claim("result")],
      evidence: [evidence({ level: "fulltext", sha256: "a".repeat(64), locators: [{ kind: "file", value: "source.pdf" }] })],
      links: [link()],
      artifactRunClaimIds: new Set(["claim-1"]),
    });
    expect(fulltext?.ok).toBe(false);
  });

  it("deduplicates independent sources by SHA and normalized DOI", () => {
    const first = evidence({
      id: "e-1",
      level: "snippet",
      quote: "Same source",
      sha256: "b".repeat(64),
      source: { kind: "doi", locator: "https://doi.org/10.1234/example." },
      locators: [{ kind: "page", value: "1" }],
    });
    const second = evidence({
      id: "e-2",
      level: "snippet",
      quote: "Same source",
      sha256: "b".repeat(64),
      source: { kind: "url", locator: "doi:10.1234/example" },
      locators: [{ kind: "page", value: "2" }],
    });
    const [result] = checkEvidenceSufficiency({
      claims: [{ ...claim("interpretation"), evidenceIds: ["e-1", "e-2"] }],
      evidence: [first, second],
      links: [link({ evidenceId: "e-1" }), link({ evidenceId: "e-2" })],
    });
    expect(result?.ok).toBe(false);
    expect(result?.reason).toContain("两个独立");
  });

  it("blocks claim/link ledger drift, orphan links, and status upgrades", () => {
    const results = checkEvidenceSufficiency({
      claims: [{ ...claim(), evidenceIds: ["e-1", "undeclared"], status: "uncertain" }],
      evidence: [evidence()],
      links: [link(), link({ claimId: "missing-claim", evidenceId: "e-1" })],
    });
    expect(results.some((result) => result.reason.includes("未建立关系"))).toBe(true);
    expect(results.some((result) => result.gateId === "ledger:orphan-links")).toBe(true);
    expect(results.some((result) => result.reason.includes("状态为 uncertain"))).toBe(true);
  });
});
