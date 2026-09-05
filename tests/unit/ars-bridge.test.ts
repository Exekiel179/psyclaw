import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { sha256Text } from "../../src/core/hash.js";
import { ARS_REVIEW_SEATS, type ArsReviewSeat, type ArsSeatResult } from "../../src/ars/contracts.js";
import { runArsMultiAgentBridge, type ArsBridgeAdapters } from "../../src/ars/bridge.js";
import { ARS_REVIEW_ROLES, arsReviewDispatchBatches } from "../../src/ars/panel-plan.js";
import { buildArsPhase1Prompt, buildArsPhase2Prompt } from "../../src/ars/pi-panel-executor.js";
import { fakeReReviewClient, type ArsReReviewAdapters } from "../../src/ars/re-review.js";
import { bootstrapProject } from "../../src/project/bootstrap.js";

const MANUSCRIPT_MARKER = "UNIQUE_MANUSCRIPT_BODY_TOKEN_xyz";
const RESPONSE_LETTER = "RESPONSE_LETTER_MUST_NOT_APPEAR_IN_2A";

function seatResult(seat: ArsReviewSeat, runRoot: string): ArsSeatResult {
  const phase1 = `phase1-${seat}-blind`;
  const phase2 = `phase2-${seat}-visible`;
  return {
    schemaVersion: "psyclaw/ars-seat-result/v1",
    seat,
    role: ARS_REVIEW_ROLES[seat],
    contextId: `${runRoot.split(/[\\/]/).at(-1)}-${seat.toLowerCase()}`,
    provider: null,
    modelFamily: null,
    peerOutputsVisible: false,
    phase1,
    phase1Sha256: sha256Text(phase1),
    phase2,
    phase2Sha256: sha256Text(phase2),
    outcome: "succeeded",
  };
}

async function projectWithManuscript(): Promise<{ root: string; manuscriptPath: string; cards: string }> {
  const root = await mkdtemp(join(tmpdir(), "psyclaw-ars-bridge-"));
  await bootstrapProject({ root, goal: "ARS bridge fixture", paradigm: "survey-observational" });
  await mkdir(join(root, "paper"), { recursive: true });
  const manuscriptPath = "paper/manuscript.md";
  await writeFile(join(root, manuscriptPath), `# Title\n\n${MANUSCRIPT_MARKER}\n`, "utf8");
  return { root, manuscriptPath, cards: "confirmed-cards:v1" };
}

function offlineFullAdapters(overrides?: {
  failSeat?: ArsReviewSeat;
  onSeat?: (seat: ArsReviewSeat, manuscriptPath: string, cards: string) => void;
}): Partial<ArsBridgeAdapters> {
  return {
    executeSeat: async (seat, _contractPath, manuscriptPath, _metadataPath, reviewerCards, options) => {
      overrides?.onSeat?.(seat, manuscriptPath, reviewerCards);
      if (overrides?.failSeat === seat) throw new Error(`injected failure for ${seat}`);
      return seatResult(seat, options.runRoot);
    },
    executeSynthesis: async (seats) => {
      expect(seats).toHaveLength(5);
      expect(seats.every((seat) => seat.peerOutputsVisible === false)).toBe(true);
      return "synthetic-panel-decision";
    },
    buildProvenance: async (_seats, _contractSha256, panelId, runRoot) => {
      const path = join(runRoot, "panel-provenance.json");
      await writeFile(path, JSON.stringify({ panel_id: panelId, ok: true }), "utf8");
      return path;
    },
    finalizeCarrier: async ({ runRoot }) => {
      const path = join(runRoot, "panel-provenance-carrier.json");
      await writeFile(path, JSON.stringify({ carrier: true }), "utf8");
      return path;
    },
  };
}

function reReviewJson(phase: "1" | "2a" | "2b", decisionState = "accepted"): string {
  if (phase === "1") return JSON.stringify({ schema: "precommitment", gate: "phase1", contract_ack: true });
  if (phase === "2a") return JSON.stringify({ schema: "verdict", gate: "phase2a", evidence_committed: true });
  return JSON.stringify({ schema: "traceability", gate: "phase2b", decision_state: decisionState });
}

async function writeReReviewInputs(root: string, withResponseLetter: boolean): Promise<Record<string, string>> {
  await mkdir(join(root, "paper"), { recursive: true });
  const paths = {
    originalManuscriptPath: "paper/original.md",
    manuscriptPath: "paper/revised.md",
    roadmapPath: "paper/roadmap.md",
    authorAdjudicationPath: "paper/adjudication.json",
    revisionEvidenceBundlePath: "paper/evidence-bundle.json",
    ...(withResponseLetter ? { responseLetterPath: "paper/response-letter.md" } : {}),
  };
  await writeFile(join(root, paths.originalManuscriptPath), "original manuscript body", "utf8");
  await writeFile(join(root, paths.manuscriptPath), "revised manuscript body", "utf8");
  await writeFile(join(root, paths.roadmapPath), "revision roadmap", "utf8");
  await writeFile(join(root, paths.authorAdjudicationPath), JSON.stringify({ decisions: [] }), "utf8");
  await writeFile(join(root, paths.revisionEvidenceBundlePath), JSON.stringify({ items: [] }), "utf8");
  if (withResponseLetter && paths.responseLetterPath) {
    await writeFile(join(root, paths.responseLetterPath), RESPONSE_LETTER, "utf8");
  }
  return paths;
}

describe("ARS Stage 3 / 3′ bridge fixtures", () => {
  it("keeps Phase 1 paper-blind and Phase 2 paper-visible without peer outputs", () => {
    const phase1 = buildArsPhase1Prompt({
      agentPrompt: "agent",
      role: "methodology",
      seat: "R1",
      contract: "{}",
      metadata: '{"title":"t"}',
      reviewerCards: "cards",
    });
    expect(phase1).toContain("paper-content-blind");
    expect(phase1).not.toContain(MANUSCRIPT_MARKER);
    expect(phase1).not.toContain("<paper_content>");

    const phase2 = buildArsPhase2Prompt({
      role: "methodology",
      seat: "R1",
      contract: "{}",
      phase1: "p1",
      manuscript: MANUSCRIPT_MARKER,
      reviewerCards: "cards",
    });
    expect(phase2).toContain(MANUSCRIPT_MARKER);
    expect(phase2).not.toContain("peer");
  });

  it("runs reviewer_full with fixed five seats, 4+1 batches, checkpoint and provenance", async () => {
    const { root, manuscriptPath, cards } = await projectWithManuscript();
    const seatCalls: ArsReviewSeat[] = [];

    const result = await runArsMultiAgentBridge({
      mode: "reviewer_full",
      manuscriptPath,
      reviewerCards: cards,
      title: "Fixture",
      passportDigest: "passport-1",
    }, {
      root,
      adapters: offlineFullAdapters({
        onSeat: (seat) => { seatCalls.push(seat); },
      }),
    });

    expect(result.status).toBe("completed");
    expect(result.mode).toBe("reviewer_full");
    expect(result.seatResults?.map((seat) => seat.seat)).toEqual([...ARS_REVIEW_SEATS]);
    expect(result.independenceClaim).toBe("process-separated-not-independent-errors");
    expect([...seatCalls].sort()).toEqual([...ARS_REVIEW_SEATS].sort());
    expect(arsReviewDispatchBatches().map((batch) => batch.length)).toEqual([4, 1]);

    const runRoot = join(root, result.outputRoot);
    const checkpoint = JSON.parse(await readFile(join(runRoot, "checkpoint.json"), "utf8")) as {
      completedSeats: string[];
      expectedSeats: string[];
      inputDigest: string;
    };
    expect(checkpoint.expectedSeats).toEqual([...ARS_REVIEW_SEATS]);
    expect(checkpoint.completedSeats).toHaveLength(5);
    expect(checkpoint.inputDigest).toBe(result.inputDigest);
    await expect(readFile(join(runRoot, "panel-provenance.json"), "utf8")).resolves.toContain(result.runId);
    await expect(readFile(join(runRoot, "result.json"), "utf8")).resolves.toContain("\"status\": \"completed\"");
  });

  it("blocks with PANEL-SHRUNK when any seat fails and does not invent missing seats", async () => {
    const { root, manuscriptPath, cards } = await projectWithManuscript();
    const result = await runArsMultiAgentBridge({
      mode: "reviewer_full",
      manuscriptPath,
      reviewerCards: cards,
    }, {
      root,
      adapters: offlineFullAdapters({ failSeat: "R2" }),
    });
    expect(result.status).toBe("blocked");
    expect(result.diagnostics.some((item) => item.includes("[PANEL-SHRUNK]"))).toBe(true);
    expect(result.seatResults?.some((seat) => seat.seat === "R2")).toBe(false);
    expect(result.synthesis).toBeUndefined();
  });

  it("refuses resume when manuscript digest drifts", async () => {
    const { root, manuscriptPath, cards } = await projectWithManuscript();
    const first = await runArsMultiAgentBridge({
      mode: "reviewer_full",
      manuscriptPath,
      reviewerCards: cards,
      passportDigest: "passport-stable",
    }, { root, adapters: offlineFullAdapters() });
    expect(first.status).toBe("completed");

    await writeFile(join(root, manuscriptPath), "# Title\n\nchanged body\n", "utf8");
    await expect(runArsMultiAgentBridge({
      mode: "reviewer_full",
      manuscriptPath,
      reviewerCards: cards,
      passportDigest: "passport-stable",
      resumeRunId: first.runId,
    }, { root, adapters: offlineFullAdapters() })).rejects.toThrow(/resume blocked/i);
  });

  it("replays a completed resume when digests still match", async () => {
    const { root, manuscriptPath, cards } = await projectWithManuscript();
    const first = await runArsMultiAgentBridge({
      mode: "reviewer_full",
      manuscriptPath,
      reviewerCards: cards,
      passportDigest: "passport-replay",
    }, { root, adapters: offlineFullAdapters() });
    let seatExecutions = 0;
    const second = await runArsMultiAgentBridge({
      mode: "reviewer_full",
      manuscriptPath,
      reviewerCards: cards,
      passportDigest: "passport-replay",
      resumeRunId: first.runId,
    }, {
      root,
      adapters: offlineFullAdapters({
        onSeat: () => { seatExecutions += 1; },
      }),
    });
    expect(second.status).toBe("completed");
    expect(second.runId).toBe(first.runId);
    expect(second.inputDigest).toBe(first.inputDigest);
    expect(seatExecutions).toBe(0);
  });

  it("rejects sensitive or non-research ARS inputs", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-ars-sensitive-"));
    await bootstrapProject({ root, goal: "ARS", paradigm: "survey-observational" });
    await writeFile(join(root, ".env"), "API_KEY=secret-value-here", "utf8");
    await expect(runArsMultiAgentBridge({
      mode: "reviewer_full",
      manuscriptPath: ".env",
      reviewerCards: "cards",
    }, { root, adapters: offlineFullAdapters() })).rejects.toThrow(/not approved/i);
  });

  it("runs reviewer_re_review as three ordered gates without five-seat full schema", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-ars-rereview-"));
    await bootstrapProject({ root, goal: "ARS re-review", paradigm: "survey-observational" });
    const paths = await writeReReviewInputs(root, true);
    const prompts: string[] = [];
    let seatCalls = 0;

    const adapters: Partial<ArsReReviewAdapters> = {
      createClient: () => fakeReReviewClient((prompt) => {
        prompts.push(prompt);
        if (prompt.includes("Phase 1")) return reReviewJson("1");
        if (prompt.includes("Phase 2A")) return reReviewJson("2a");
        if (prompt.includes("Phase 2B")) return reReviewJson("2b");
        throw new Error(`unexpected gate prompt: ${prompt.slice(0, 80)}`);
      }),
      validateSchema: async () => undefined,
      runChecker: async () => ({ stdout: "ok" }),
    };

    const result = await runArsMultiAgentBridge({
      mode: "reviewer_re_review",
      ...paths,
    }, {
      root,
      adapters: {
        executeSeat: async () => {
          seatCalls += 1;
          throw new Error("reviewer_full seat executor must not run for re-review");
        },
      },
      reReviewAdapters: adapters,
    });

    expect(result.status).toBe("completed");
    expect(result.mode).toBe("reviewer_re_review");
    expect(seatCalls).toBe(0);
    expect(prompts).toHaveLength(3);
    expect(prompts[0]).toContain("Phase 1");
    expect(prompts[0]).not.toContain("original manuscript body");
    expect(prompts[0]).not.toContain(RESPONSE_LETTER);
    expect(prompts[1]).toContain("Phase 2A");
    expect(prompts[1]).toContain("original manuscript body");
    expect(prompts[1]).not.toContain(RESPONSE_LETTER);
    expect(prompts[1]).toMatch(/Response to Reviewers.*withheld|withheld/i);
    expect(prompts[2]).toContain("Phase 2B");
    expect(prompts[2]).toContain(RESPONSE_LETTER);
  });

  it("blocks reviewer_re_review on user_review_required and refuses resume", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-ars-rereview-block-"));
    await bootstrapProject({ root, goal: "ARS re-review block", paradigm: "survey-observational" });
    const paths = await writeReReviewInputs(root, false);

    const blocked = await runArsMultiAgentBridge({
      mode: "reviewer_re_review",
      ...paths,
    }, {
      root,
      reReviewAdapters: {
        createClient: () => fakeReReviewClient((prompt) => {
          if (prompt.includes("Phase 1")) return reReviewJson("1");
          if (prompt.includes("Phase 2A")) return reReviewJson("2a");
          return reReviewJson("2b", "user_review_required");
        }),
        validateSchema: async () => undefined,
        runChecker: async () => ({ stdout: "needs human" }),
      },
    });
    expect(blocked.status).toBe("blocked");
    expect(blocked.diagnostics.some((item) => item.includes("awaiting human resolution"))).toBe(true);

    await expect(runArsMultiAgentBridge({
      mode: "reviewer_re_review",
      ...paths,
      resumeRunId: "ars_rereview_fake",
    }, {
      root,
      reReviewAdapters: {
        createClient: () => fakeReReviewClient(() => reReviewJson("1")),
        validateSchema: async () => undefined,
        runChecker: async () => ({ stdout: "ok" }),
      },
    })).rejects.toThrow(/resume is not available/i);
  });
});
