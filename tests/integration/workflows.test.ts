import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { bootstrapProject } from "../../src/project/bootstrap.js";
import { appendClaim, appendClaimEvidenceLink, appendEvidence } from "../../src/research/ledger.js";
import { runAnalysisDelegation } from "../../src/workflows/analysis-delegation.js";
import { runLiteratureReview } from "../../src/workflows/literature-review.js";
import { literatureReviewSpec } from "../../src/workflows/literature-review.js";
import { runWritingReview } from "../../src/workflows/writing-review.js";
import { finalizeWorkflow } from "../../src/workflows/spec.js";
import { RunEventLog } from "../../src/panel/events.js";
import type { Evidence } from "../../src/core/contracts.js";

const snippet = (id: string, locator: string): Evidence => ({
  id,
  source: { kind: "file", locator },
  level: "snippet",
  quote: "Exact excerpt",
  retrievedAt: "2026-01-01T00:00:00.000Z",
  accessStatus: "verified",
  locators: [{ kind: "section", value: "Findings" }],
});

describe("M4 workflow packs", () => {
  it("literature-review aggregates sources and discloses gaps", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-litreview-"));
    await bootstrapProject({ root, goal: "Bounded question", paradigm: "qualitative-thematic" });
    await appendEvidence(root, snippet("e-1", "fixture/a.md"));
    await appendClaim(root, { id: "c-1", text: "A coded theme", kind: "interpretation", evidenceIds: ["e-1"], status: "supported" });
    await appendClaimEvidenceLink(root, { claimId: "c-1", evidenceId: "e-1", relation: "supports", rationale: "coded" });

    const result = await runLiteratureReview(root);
    expect(result.verdict).toBe("pass");
    const matrix = JSON.parse(await readFile(join(root, "outputs", "review-matrix.json"), "utf8"));
    expect(matrix.sources).toHaveLength(1);
    expect(matrix.claims).toHaveLength(1);
    expect(await readFile(join(root, "outputs", "literature-review.md"), "utf8")).toContain("Bounded question");
  });

  it("literature-review blocks with no sources", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-litreview-empty-"));
    await bootstrapProject({ root, goal: "Empty", paradigm: "qualitative-thematic" });
    const result = await runLiteratureReview(root);
    expect(result.verdict).toBe("blocked");
    expect(result.gates.some((gate) => gate.gateId === "review:sources")).toBe(true);
  });

  it("analysis-delegation plans external work without computing", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-analysis-"));
    await bootstrapProject({ root, goal: "Bounded question", paradigm: "qualitative-thematic" });
    await appendEvidence(root, {
      ...snippet("e-1", "fixture/a.md"),
      level: "fulltext",
      sha256: "a".repeat(64),
    });
    await appendClaim(root, { id: "c-1", text: "A thematic result", kind: "result", evidenceIds: ["e-1"], status: "supported" });
    await appendClaimEvidenceLink(root, { claimId: "c-1", evidenceId: "e-1", relation: "supports", rationale: "coded" });

    const result = await runAnalysisDelegation(root);
    expect(result.verdict).toBe("pass");
    const delegation = JSON.parse(await readFile(join(root, "outputs", "delegation.json"), "utf8"));
    expect(delegation.tasks).toHaveLength(1);
    expect(delegation.tasks[0].contract.script).toContain("c-1");
  });

  it("analysis-delegation blocks when there is nothing to delegate", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-analysis-empty-"));
    await bootstrapProject({ root, goal: "No results", paradigm: "qualitative-thematic" });
    await appendEvidence(root, snippet("e-1", "fixture/a.md"));
    await appendClaim(root, { id: "c-1", text: "A definition", kind: "definition", evidenceIds: ["e-1"], status: "supported" });
    await appendClaimEvidenceLink(root, { claimId: "c-1", evidenceId: "e-1", relation: "supports", rationale: "coded" });
    const result = await runAnalysisDelegation(root);
    expect(result.verdict).toBe("blocked");
    expect(result.gates.some((gate) => gate.gateId === "analysis:no-result-claims")).toBe(true);
  });

  it("writing-review flags unsupported claims and causal language", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-writing-"));
    await bootstrapProject({ root, goal: "Bounded question", paradigm: "qualitative-thematic" });
    await appendEvidence(root, snippet("e-1", "fixture/a.md"));
    await appendClaim(root, { id: "c-1", text: "The program increases engagement", kind: "interpretation", evidenceIds: ["e-1"], status: "supported" });
    await appendClaimEvidenceLink(root, { claimId: "c-1", evidenceId: "e-1", relation: "supports", rationale: "coded" });
    await appendClaim(root, { id: "c-2", text: "An unsupported assertion", kind: "definition", evidenceIds: [], status: "supported" });

    const result = await runWritingReview(root);
    const report = JSON.parse(await readFile(join(root, "outputs", "review-findings.json"), "utf8"));
    expect(report.findings.some((finding: { rule: string }) => finding.rule === "causal-language-without-result-artifact")).toBe(true);
    expect(report.findings.some((finding: { rule: string }) => finding.rule === "unsupported-claim-asserted-as-supported")).toBe(true);
    expect(result.verdict).toBe("blocked");
  });
});

describe("D4 workflow output, event order, and provenance", () => {
  it("rejects an unsafe workflow output path", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-d4-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "survey-observational" });
    await expect(finalizeWorkflow(root, literatureReviewSpec, {
      gates: [],
      outputs: [{ path: "../escape.md", contents: "x" }],
      completed: [],
    })).rejects.toThrow(/unsafe output path/);
  });

  it("blocks when a required artifact is not produced", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-d4-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "survey-observational" });
    const result = await finalizeWorkflow(root, literatureReviewSpec, {
      gates: [],
      outputs: [],
      completed: [],
    });
    expect(result.verdict).toBe("blocked");
    expect(result.gates.some((gate) => gate.gateId === "workflow:missing-artifact")).toBe(true);
  });

  it("records sha256, workflow version, input digest, and draft status", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-d4-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "survey-observational" });
    // no sources -> blocked, but outputs are still written as draft-blocked
    const result = await runLiteratureReview(root);
    expect(result.verdict).toBe("blocked");
    const manifest = JSON.parse(await readFile(result.manifestPath, "utf8"));
    expect(manifest.workflowVersion).toBe("1.0.0");
    expect(manifest.inputDigest).toMatch(/^[a-f0-9]{64}$/);
    expect(manifest.outputs.every((output: { status: string }) => output.status === "draft-blocked")).toBe(true);
    expect(manifest.outputs.every((output: { sha256: string }) => /^[a-f0-9]{64}$/.test(output.sha256))).toBe(true);
  });

  it("emits completed as the final event only after artifacts are written", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-d4-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await appendEvidence(root, snippet("e-1", "fixture/a.md"));
    await appendClaim(root, { id: "c-1", text: "A coded theme", kind: "interpretation", evidenceIds: ["e-1"], status: "supported" });
    await appendClaimEvidenceLink(root, { claimId: "c-1", evidenceId: "e-1", relation: "supports", rationale: "coded" });

    const result = await runLiteratureReview(root);
    const events = await new RunEventLog(root, result.runId).snapshot();
    expect(events[0]?.type).toBe("planned");
    expect(events.at(-1)?.type).toBe("completed");

    // blocked run ends with blocked, not completed
    const blockedRoot = await mkdtemp(join(tmpdir(), "psyclaw-d4-"));
    await bootstrapProject({ root: blockedRoot, goal: "Empty", paradigm: "survey-observational" });
    const blockedResult = await runLiteratureReview(blockedRoot);
    const blockedEvents = await new RunEventLog(blockedRoot, blockedResult.runId).snapshot();
    expect(blockedEvents.at(-1)?.type).toBe("blocked");
  });
});
