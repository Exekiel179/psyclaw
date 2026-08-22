import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { bootstrapProject } from "../../src/project/bootstrap.js";
import { appendClaim, appendClaimEvidenceLink, appendEvidence } from "../../src/research/ledger.js";
import { runOfflineBrief } from "../../src/research/brief.js";

describe("offline research brief", () => {
  it("fails closed when evidence is insufficient", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-brief-blocked-"));
    await bootstrapProject({ root, goal: "Bounded question", paradigm: "survey-observational" });
    await appendEvidence(root, {
      id: "e1",
      source: { kind: "file", locator: "source.md" },
      level: "metadata",
      retrievedAt: "2026-01-01T00:00:00.000Z",
      accessStatus: "verified",
      locators: [{ kind: "file", value: "source.md" }],
    });
    await appendClaim(root, {
      id: "c1",
      text: "A result requiring full text",
      kind: "result",
      evidenceIds: ["e1"],
      status: "supported",
    });
    await appendClaimEvidenceLink(root, {
      claimId: "c1",
      evidenceId: "e1",
      relation: "supports",
      rationale: "fixture",
    });
    const result = await runOfflineBrief(root);
    expect(result.verdict).toBe("blocked");
    expect(result.briefPath).toBeUndefined();
    expect(await readFile(result.manifestPath, "utf8")).toContain("psyclaw/brief-manifest/v1");
    expect(await readFile(result.verdictPath, "utf8")).toContain("psyclaw/verdict/v1");
    expect(await readFile(join(root, "notes", "HANDOFF.md"), "utf8")).toContain("resolve blocked");
  });

  it("writes a brief only after a supported non-result claim passes", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-brief-pass-"));
    await bootstrapProject({ root, goal: "Bounded question", paradigm: "qualitative-thematic" });
    await appendEvidence(root, {
      id: "e1",
      source: { kind: "file", locator: "source.md" },
      level: "abstract",
      retrievedAt: "2026-01-01T00:00:00.000Z",
      accessStatus: "verified",
      locators: [{ kind: "section", value: "Abstract" }],
    });
    await appendClaim(root, {
      id: "c1",
      text: "A definition from the source",
      kind: "definition",
      evidenceIds: ["e1"],
      status: "supported",
    });
    await appendClaimEvidenceLink(root, {
      claimId: "c1",
      evidenceId: "e1",
      relation: "supports",
      rationale: "fixture",
    });
    const result = await runOfflineBrief(root);
    expect(result.verdict).toBe("pass");
    expect(result.briefPath).toBeDefined();
    expect(await readFile(result.briefPath!, "utf8")).toContain("A definition from the source");
    expect(await readFile(result.verdictPath, "utf8")).toContain('"verdict": "pass"');
  });
});
