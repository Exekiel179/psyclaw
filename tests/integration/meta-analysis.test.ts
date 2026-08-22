import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { bootstrapProject } from "../../src/project/bootstrap.js";
import { runMetaAnalysis } from "../../src/workflows/meta-analysis.js";

/** Deterministic OpenAlex-shaped response; real network never touched. */
function fakeOpenAlex(): typeof fetch {
  return async (): Promise<Response> =>
    new Response(JSON.stringify({
      results: [
        { id: "W1", title: "Online learning engagement study A", publication_year: 2021, authorships: [{ author: { display_name: "Alpha" } }], doi: "https://doi.org/10.1/a", cited_by_count: 7 },
        { id: "W2", title: "Online learning engagement study B", publication_year: 2022, authorships: [{ author: { display_name: "Beta" } }], doi: "https://doi.org/10.1/b", cited_by_count: 3 },
        { id: "W3", title: "Online learning engagement study C", publication_year: 2023, authorships: [], doi: "https://doi.org/10.1/c" },
      ],
    }), { status: 200 });
}

async function withDataset(root: string): Promise<void> {
  await mkdir(join(root, "data", "clean"), { recursive: true });
  await writeFile(
    join(root, "data", "clean", "effects.csv"),
    "study_id,effect_size,standard_error,n\nW1,0.42,0.11,120\nW2,0.31,0.14,96\nW3,0.55,0.19,64\n",
    "utf8",
  );
}

describe("meta-analysis workflow", () => {
  it("passes with a dataset and staged runner, writing report and ledger entries", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-meta-"));
    await bootstrapProject({ root, goal: "Online learning engagement", paradigm: "meta-analysis" });
    await withDataset(root);

    const lines: string[] = [];
    const result = await runMetaAnalysis(root, {
      target: "online learning engagement",
      nStudies: 3,
      fetchFn: fakeOpenAlex(),
      runner: { stage: async (tag, label, fn, onDone) => {
        lines.push(`[${tag}] ${label}`);
        const value = await fn();
        if (onDone) lines.push(`  ${onDone(value)}`);
        return value;
      }, note: () => undefined },
    });

    expect(result.verdict).toBe("pass");
    expect(lines).toContain("[intake] 检索 OpenAlex 数据库并提取 \"online learning engagement\" 的实证研究");
    expect(lines.some((line) => line.startsWith("[audit]"))).toBe(true);
    expect(lines.some((line) => line.startsWith("[brief]"))).toBe(true);

    const report = JSON.parse(await readFile(join(root, "analysis", "outputs", "meta-analysis.json"), "utf8"));
    expect(report.studiesFound).toBe(3);
    expect(report.effectRows).toBe(3);
    expect(report.audit.delegatedTo).toBe("R metafor");

    const script = await readFile(join(root, "analysis", "scripts", "metafor.R"), "utf8");
    expect(script).toContain("rma(yi = d$effect_size");

    // Every found study was recorded into the evidence ledger.
    const ledger = await readFile(join(root, ".psyclaw", "evidence.jsonl"), "utf8");
    expect(ledger).toContain("Online learning engagement study A");
    expect(ledger).toContain("Online learning engagement study C");
  });

  it("blocks honestly without a dataset instead of fabricating effect sizes", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-meta-empty-"));
    await bootstrapProject({ root, goal: "Online learning engagement", paradigm: "meta-analysis" });

    const result = await runMetaAnalysis(root, {
      target: "online learning engagement",
      nStudies: 3,
      fetchFn: fakeOpenAlex(),
    });

    expect(result.verdict).toBe("blocked");
    expect(result.gates.some((gate) => gate.gateId === "meta:effect-data-missing")).toBe(true);
    const report = JSON.parse(await readFile(join(root, "analysis", "outputs", "meta-analysis.json"), "utf8"));
    expect(report.effectRows).toBe(0);
    expect(report.audit.note).toContain("数据集缺失");
  });

  it("blocks when fewer than two studies are found", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-meta-few-"));
    await bootstrapProject({ root, goal: "Online learning engagement", paradigm: "meta-analysis" });

    const fetchFn = async (): Promise<Response> =>
      new Response(JSON.stringify({ results: [{ id: "W1", title: "Only one" }] }), { status: 200 });
    const result = await runMetaAnalysis(root, {
      target: "online learning engagement",
      nStudies: 5,
      fetchFn,
    });
    expect(result.verdict).toBe("blocked");
    expect(result.gates.some((gate) => gate.gateId === "meta:insufficient-studies")).toBe(true);
  });
});
