import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { bootstrapProject } from "../../src/project/bootstrap.js";
import { listCitationUses, recordCitationUse } from "../../src/core/citations.js";
import type { DoiVerification } from "../../src/core/doi.js";

const verifiedVerification = (doi: string): DoiVerification => ({
  schemaVersion: "psyclaw/doi-verify/v1",
  doi,
  status: "verified",
  crossref: { title: "Social Support and Job Anxiety", authors: ["Ronald C Kessler"], year: 2005, container: "A Journal" },
  verifiedAt: "2026-01-01T00:00:00.000Z",
});

describe("recordCitationUse (evidence + reason at generation time)", () => {
  it("verifies the DOI, archives the reference, and records the citation reason", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-cite-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });

    const result = await recordCitationUse(root, {
      doi: "10.1000/kessler2005",
      reason: "支持：社会支持缓冲压力假说",
      context: "社会支持能够削弱压力事件对心理健康的消极影响（Kessler et al., 2005）",
      section: "1 引言",
    }, async (doi) => verifiedVerification(doi));

    expect(result.appended).toBe(true);
    expect(result.record.citationId).toMatch(/^cite_[a-f0-9]{16}$/);
    expect(result.record.doi).toBe("10.1000/kessler2005");
    expect(result.record.surname).toBe("Kessler");
    expect(result.record.year).toBe(2005);
    expect(result.record.reason).toContain("缓冲压力假说");
    expect(result.record.section).toBe("1 引言");
    expect(result.record.verified).toBe(true);
    expect(result.reference?.title).toBe("Social Support and Job Anxiety");

    // reference was archived
    const refs = await readFile(join(root, ".psyclaw", "references.jsonl"), "utf8");
    expect(refs).toContain("10.1000/kessler2005");
    // citation use persisted
    const uses = await listCitationUses(root);
    expect(uses).toHaveLength(1);
    expect(uses[0]!.reason).toContain("缓冲压力假说");

    // idempotent: same doi+reason+context → no duplicate
    const again = await recordCitationUse(root, {
      doi: "10.1000/kessler2005",
      reason: "支持：社会支持缓冲压力假说",
      context: "社会支持能够削弱压力事件对心理健康的消极影响（Kessler et al., 2005）",
    }, async (doi) => verifiedVerification(doi));
    expect(again.appended).toBe(false);
    expect((await listCitationUses(root))).toHaveLength(1);
  });

  it("records the use honestly (verified=false) when the DOI cannot be verified", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-cite-un-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    const result = await recordCitationUse(root, {
      doi: "not-a-doi",
      reason: "待核验的引用",
      context: "某处引用",
    }, async () => ({ schemaVersion: "psyclaw/doi-verify/v1", doi: "not-a-doi", status: "error", error: "不是合法 DOI", verifiedAt: "" }));

    expect(result.record.verified).toBe(false);
    expect(result.reference).toBeNull();
    expect((await listCitationUses(root))[0]!.reason).toBe("待核验的引用");
  });

  it("requires doi, reason, and context", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-cite-bad-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await expect(recordCitationUse(root, { doi: "10.1000/x", reason: "", context: "c" })).rejects.toThrow(/doi, reason, and context/);
  });
});
