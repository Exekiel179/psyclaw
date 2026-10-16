import { afterEach, describe, expect, it, vi } from "vitest";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { sha256Text } from "../../src/core/hash.js";
import { ARS_REVIEW_SEATS, type ArsReviewSeat, type ArsSeatResult } from "../../src/ars/contracts.js";
import { ARS_REVIEW_ROLES } from "../../src/ars/panel-plan.js";
import { executeArsReviewSeat, executeArsSynthesis } from "../../src/ars/pi-panel-executor.js";
import { fakeReReviewClient, runArsReReview } from "../../src/ars/re-review.js";
import { bootstrapProject } from "../../src/project/bootstrap.js";
import {
  setObservabilityHandleForTests,
  shutdownObservability,
} from "../../src/observability/index.js";
import type { LlmGenerationInput } from "../../src/observability/llm.js";
import { observePiRpcPromptAndWait } from "../../src/observability/pi-rpc.js";
import type { PiRpcMessage } from "../../src/adapters/pi/rpc.js";

const rpc = vi.hoisted(() => ({ prompts: [] as string[] }));

vi.mock("../../src/platform/python.js", () => ({
  execPython: async () => ({ stdout: "ok", stderr: "" }),
}));

vi.mock("../../src/adapters/pi/rpc.js", () => {
  class PiRpcClient {
    async start() {}
    async stop() {}
    async promptAndWait(prompt: string): Promise<PiRpcMessage[]> {
      rpc.prompts.push(prompt);
      const text = prompt.includes("editorial synthesis")
        ? "synthesis-artifact"
        : prompt.includes("paper-visible Phase 2")
          ? "phase2-artifact"
          : "phase1-artifact";
      return [{
        type: "message_end",
        message: {
          role: "assistant",
          content: [{ type: "text", text }],
          provider: "deepseek",
          model: "deepseek-v4-flash",
          usage: { input: 6, output: 2 },
        },
      }];
    }
  }
  return { PiRpcClient };
});

const SECRET_PROMPT = "SECRET_ARS_PROMPT_SHOULD_NOT_LEAK";

function captureHandle() {
  const spans: Array<{ name: string; attributes: Record<string, string> }> = [];
  const generations: LlmGenerationInput[] = [];
  setObservabilityHandleForTests({
    captureEvent() {},
    captureError() {},
    captureLlmGeneration(input) { generations.push({ ...input }); },
    async runSpan(name, attributes, fn) {
      spans.push({ name, attributes: { ...attributes } });
      return fn();
    },
    async flush() {},
  });
  return { spans, generations };
}

function textEvents(text: string, usage?: { input: number; output: number }): PiRpcMessage[] {
  return [{
    type: "message_end",
    message: {
      role: "assistant",
      content: [{ type: "text", text }],
      provider: "deepseek",
      model: "deepseek-v4-flash",
      ...(usage === undefined ? {} : { usage }),
    },
  }];
}

function reReviewJson(phase: "1" | "2a" | "2b"): string {
  if (phase === "1") return JSON.stringify({ schema: "precommitment", gate: "phase1", contract_ack: true });
  if (phase === "2a") return JSON.stringify({ schema: "verdict", gate: "phase2a", evidence_committed: true });
  return JSON.stringify({ schema: "traceability", gate: "phase2b", decision_state: "accepted" });
}

async function writeReReviewInputs(root: string): Promise<Record<string, string>> {
  await mkdir(join(root, "paper"), { recursive: true });
  const paths = {
    originalManuscriptPath: "paper/original.md",
    manuscriptPath: "paper/revised.md",
    roadmapPath: "paper/roadmap.md",
    authorAdjudicationPath: "paper/adjudication.json",
    revisionEvidenceBundlePath: "paper/evidence-bundle.json",
  };
  await writeFile(join(root, paths.originalManuscriptPath), "original manuscript body", "utf8");
  await writeFile(join(root, paths.manuscriptPath), "revised manuscript body", "utf8");
  await writeFile(join(root, paths.roadmapPath), "revision roadmap", "utf8");
  await writeFile(join(root, paths.authorAdjudicationPath), JSON.stringify({ decisions: [] }), "utf8");
  await writeFile(join(root, paths.revisionEvidenceBundlePath), JSON.stringify({ items: [] }), "utf8");
  return paths;
}

function seatResult(seat: ArsReviewSeat, runRoot: string): ArsSeatResult {
  const phase1 = `phase1-${seat}`;
  const phase2 = `phase2-${seat}`;
  return {
    schemaVersion: "psyclaw/ars-seat-result/v1",
    seat,
    role: ARS_REVIEW_ROLES[seat],
    contextId: `${runRoot.split(/[\\/]/).at(-1)}-${seat.toLowerCase()}`,
    provider: "deepseek",
    modelFamily: null,
    peerOutputsVisible: false,
    phase1,
    phase1Sha256: sha256Text(phase1),
    phase2,
    phase2Sha256: sha256Text(phase2),
    outcome: "succeeded",
  };
}

describe("ARS RPC LLM telemetry", () => {
  afterEach(async () => {
    rpc.prompts.length = 0;
    await shutdownObservability();
  });

  it("wraps promptAndWait with cli.llm_call and $ai_generation without prompts", async () => {
    const { spans, generations } = captureHandle();
    const events = await observePiRpcPromptAndWait(
      { promptAndWait: async () => textEvents("ok", { input: 8, output: 3 }) },
      SECRET_PROMPT,
      { phase: "ars_review_seat_phase1", spanName: "ars-review-seat-phase1", provider: "deepseek", model: "deepseek-v4-flash" },
    );
    expect(events).toHaveLength(1);
    expect(spans).toEqual([{
      name: "cli.llm_call",
      attributes: { phase: "ars_review_seat_phase1", provider: "deepseek", model: "deepseek-v4-flash" },
    }]);
    expect(generations).toHaveLength(1);
    expect(generations[0]).toMatchObject({
      provider: "deepseek",
      model: "deepseek-v4-flash",
      usage: { input: 8, output: 3 },
      surface: "cli",
      spanName: "ars-review-seat-phase1",
    });
    expect(JSON.stringify({ spans, generations })).not.toContain(SECRET_PROMPT);
  });

  it("emits a failed generation when promptAndWait throws", async () => {
    const { spans, generations } = captureHandle();
    await expect(observePiRpcPromptAndWait(
      { promptAndWait: async () => { throw new TypeError("rpc down"); } },
      SECRET_PROMPT,
      { phase: "ars_synthesis", spanName: "ars-synthesis", provider: "openai" },
    )).rejects.toThrow(/rpc down/);
    expect(spans).toEqual([{
      name: "cli.llm_call",
      attributes: { phase: "ars_synthesis", provider: "openai" },
    }]);
    expect(generations).toEqual([expect.objectContaining({
      provider: "openai",
      model: "unknown",
      error: true,
      errorName: "TypeError",
      surface: "cli",
      spanName: "ars-synthesis",
    })]);
    expect(JSON.stringify({ spans, generations })).not.toContain(SECRET_PROMPT);
  });

  it("records seat phase1/phase2 spans and generations for executeArsReviewSeat", async () => {
    const { spans, generations } = captureHandle();
    const root = await mkdtemp(join(tmpdir(), "psyclaw-ars-seat-obs-"));
    await mkdir(join(root, "run"), { recursive: true });
    const contractPath = join(root, "contract.json");
    const manuscriptPath = join(root, "manuscript.md");
    const metadataPath = join(root, "metadata.json");
    await writeFile(contractPath, "{}", "utf8");
    await writeFile(manuscriptPath, "manuscript body", "utf8");
    await writeFile(metadataPath, "{\"title\":\"t\"}", "utf8");

    const result = await executeArsReviewSeat("R1", contractPath, manuscriptPath, metadataPath, "cards", {
      root,
      runRoot: join(root, "run"),
      provider: "deepseek",
      model: "deepseek-v4-flash",
    });
    expect(result.outcome).toBe("succeeded");
    expect(result.phase1).toBe("phase1-artifact");
    expect(result.phase2).toBe("phase2-artifact");
    expect(spans.map((span) => span.attributes.phase)).toEqual([
      "ars_review_seat_phase1",
      "ars_review_seat_phase2",
    ]);
    expect(spans.every((span) => span.name === "cli.llm_call")).toBe(true);
    expect(generations.map((item) => item.spanName)).toEqual([
      "ars-review-seat-phase1",
      "ars-review-seat-phase2",
    ]);
    expect(generations.every((item) => item.surface === "cli" && item.usage?.input === 6)).toBe(true);
  });

  it("records synthesis span and generation for executeArsSynthesis", async () => {
    const { spans, generations } = captureHandle();
    const root = await mkdtemp(join(tmpdir(), "psyclaw-ars-synth-obs-"));
    const runRoot = join(root, "run");
    await mkdir(runRoot, { recursive: true });
    const contractPath = join(root, "contract.json");
    const manuscriptPath = join(root, "manuscript.md");
    await writeFile(contractPath, "{}", "utf8");
    await writeFile(manuscriptPath, "manuscript body", "utf8");
    for (const seat of ARS_REVIEW_SEATS) {
      await writeFile(join(runRoot, `${seat}.phase2.md`), `phase2-${seat}`, "utf8");
    }

    const synthesis = await executeArsSynthesis(
      ARS_REVIEW_SEATS.map((seat) => seatResult(seat, runRoot)),
      contractPath,
      manuscriptPath,
      { root, runRoot, provider: "deepseek", model: "deepseek-v4-flash" },
    );
    expect(synthesis).toBe("synthesis-artifact");
    expect(spans).toEqual([{
      name: "cli.llm_call",
      attributes: { phase: "ars_synthesis", provider: "deepseek", model: "deepseek-v4-flash" },
    }]);
    expect(generations).toEqual([expect.objectContaining({
      surface: "cli",
      spanName: "ars-synthesis",
      provider: "deepseek",
      model: "deepseek-v4-flash",
    })]);
  });

  it("records re-review phase1/2A/2B spans and generations", async () => {
    const { spans, generations } = captureHandle();
    const root = await mkdtemp(join(tmpdir(), "psyclaw-ars-rereview-obs-"));
    await bootstrapProject({ root, goal: "ARS re-review telemetry", paradigm: "survey-observational" });
    const paths = await writeReReviewInputs(root);

    const result = await runArsReReview({
      mode: "reviewer_re_review",
      ...paths,
    }, {
      root,
      provider: "deepseek",
      model: "deepseek-v4-flash",
      adapters: {
        createClient: () => fakeReReviewClient((prompt) => {
          if (prompt.includes("Phase 1")) return reReviewJson("1");
          if (prompt.includes("Phase 2A")) return reReviewJson("2a");
          if (prompt.includes("Phase 2B")) return reReviewJson("2b");
          throw new Error(`unexpected gate prompt: ${prompt.slice(0, 80)}`);
        }),
        validateSchema: async () => undefined,
        runChecker: async () => ({ stdout: "ok" }),
      },
    });

    expect(result.status).toBe("completed");
    expect(spans.map((span) => span.attributes.phase)).toEqual([
      "ars_rereview_phase1",
      "ars_rereview_phase2a",
      "ars_rereview_phase2b",
    ]);
    expect(spans.every((span) => span.name === "cli.llm_call")).toBe(true);
    expect(generations.map((item) => item.spanName)).toEqual([
      "ars-rereview-phase1",
      "ars-rereview-phase2a",
      "ars-rereview-phase2b",
    ]);
    expect(generations.every((item) => item.surface === "cli" && item.provider === "deepseek")).toBe(true);
  });

  it("records a failed re-review generation when a gate RPC throws", async () => {
    const { generations } = captureHandle();
    const root = await mkdtemp(join(tmpdir(), "psyclaw-ars-rereview-fail-"));
    await bootstrapProject({ root, goal: "ARS re-review fail", paradigm: "survey-observational" });
    const paths = await writeReReviewInputs(root);

    const result = await runArsReReview({
      mode: "reviewer_re_review",
      ...paths,
    }, {
      root,
      provider: "deepseek",
      adapters: {
        createClient: () => fakeReReviewClient(() => {
          throw new Error("gate rpc failed");
        }),
        validateSchema: async () => undefined,
        runChecker: async () => ({ stdout: "ok" }),
      },
    });

    expect(result.status).toBe("blocked");
    expect(generations).toEqual([expect.objectContaining({
      error: true,
      errorName: "Error",
      surface: "cli",
      spanName: "ars-rereview-phase1",
      provider: "deepseek",
    })]);
  });
});
