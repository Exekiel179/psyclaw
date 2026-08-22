import { describe, expect, it } from "vitest";
import { cleanMetaTarget, runWorkflowTool } from "../../src/adapters/pi/extension.js";
import { createStageRunner, formatNoteLine, formatStageLine } from "../../src/run.js";
import { metaforScript, parseEffectCsv, searchOpenAlex } from "../../src/workflows/meta-analysis.js";

describe("parseEffectCsv", () => {
  it("parses study_id/effect_size/standard_error rows", () => {
    const rows = parseEffectCsv(
      "study_id,effect_size,standard_error,n\n" +
        "smith2020,0.42,0.11,120\n" +
        "jones2019,-0.18,0.23,85\n",
    );
    expect(rows).toHaveLength(2);
    expect(rows[0]).toEqual({ studyId: "smith2020", effectSize: 0.42, standardError: 0.11, n: 120 });
    expect(rows[1]).toEqual({ studyId: "jones2019", effectSize: -0.18, standardError: 0.23, n: 85 });
  });

  it("accepts aliased column names", () => {
    const rows = parseEffectCsv("study,effect,se\ns1,0.1,0.05\n");
    expect(rows).toHaveLength(1);
    expect(rows[0]!.studyId).toBe("s1");
  });

  it("drops rows with missing or non-positive standard errors", () => {
    const rows = parseEffectCsv(
      "study_id,effect_size,standard_error\n" +
        "ok,0.5,0.1\n" +
        "bad-se,0.5,0\n" +
        "bad-effect,abc,0.1\n" +
        "empty,,\n",
    );
    expect(rows).toHaveLength(1);
    expect(rows[0]!.studyId).toBe("ok");
  });

  it("returns [] for empty input or a missing header", () => {
    expect(parseEffectCsv("")).toEqual([]);
    expect(parseEffectCsv("a,b,c\n1,2,3\n")).toEqual([]);
  });
});

describe("searchOpenAlex", () => {
  it("maps API results and slices to nStudies", async () => {
    const fetchFn = async (): Promise<Response> =>
      new Response(JSON.stringify({
        results: [
          { id: "W1", title: "First", publication_year: 2021, authorships: [{ author: { display_name: "A" } }], doi: "https://doi.org/10.1/x", cited_by_count: 5 },
          { id: "W2", title: "Second", authorships: [] },
          { id: "W3", title: "Third" },
        ],
      }), { status: 200 });
    const studies = await searchOpenAlex("engagement", 2, fetchFn);
    expect(studies).toHaveLength(2);
    expect(studies[0]!.title).toBe("First");
    expect(studies[0]!.year).toBe(2021);
    expect(studies[0]!.authors).toEqual(["A"]);
    expect(studies[0]!.citations).toBe(5);
    expect(studies[1]!.authors).toEqual([]);
    expect(studies[1]!.year).toBeUndefined();
  });

  it("throws when the API responds with an error status", async () => {
    const fetchFn = async (): Promise<Response> => new Response("boom", { status: 503 });
    await expect(searchOpenAlex("x", 10, fetchFn)).rejects.toThrow(/OpenAlex/);
  });
});

describe("metaforScript", () => {
  it("delegates REML, I² and Egger to R and never fabricates numbers", () => {
    const script = metaforScript("data/clean/effects.csv");
    expect(script).toContain("library(metafor)");
    expect(script).toContain('method = "REML"');
    expect(script).toContain("fit$I2");
    expect(script).toContain("regtest");
    expect(script).toContain("egger_p");
    expect(script).not.toMatch(/I2\s*=\s*\d/); // no hardcoded statistics in core
  });
});

describe("cleanMetaTarget", () => {
  it("strips meta-analysis intent words and stopwords, keeping the topic", () => {
    expect(cleanMetaTarget("请对 online learning engagement 做元分析")).toBe("online learning engagement");
    expect(cleanMetaTarget("Meta-analysis of blended learning")).toBe("blended learning");
    expect(cleanMetaTarget("online learning engagement")).toBe("online learning engagement");
  });
});

describe("runWorkflowTool dispatch", () => {
  it("blocks on an unknown workflow id", async () => {
    const result = await runWorkflowTool("ignored-root", "bogus-workflow");
    expect(result.details.status).toBe("blocked");
    expect(result.content[0]!.text).toContain("Unknown workflow: bogus-workflow");
  });

  it("blocks meta-analysis without a target before touching the project", async () => {
    const result = await runWorkflowTool("ignored-root", "meta-analysis");
    expect(result.details.status).toBe("blocked");
    expect(result.content[0]!.text).toContain("meta-analysis requires a target");
  });
});

describe("createStageRunner", () => {
  it("prints [tag] label and a completion note in stage order", async () => {
    const lines: string[] = [];
    const runner = createStageRunner({ write: (line) => lines.push(line), color: false });
    const seen: string[] = [];
    const value = await runner.stage("intake", "search", async () => { seen.push("a"); return 3; }, (n) => `got ${n}`);
    await runner.stage("brief", "write", async () => { seen.push("b"); }, (r) => `done ${r}`);
    expect(value).toBe(3);
    expect(seen).toEqual(["a", "b"]);
    expect(lines[0]).toBe("[intake] search…");
    expect(lines[1]).toBe("  got 3");
    expect(lines[2]).toBe("[brief] write…");
    expect(lines[3]).toBe("  done undefined");
  });

  it("formats colorized lines for TTY output", () => {
    expect(formatStageLine("audit", "run", true)).toBe("\x1b[36m[audit]\x1b[0m run");
    expect(formatStageLine("audit", "run", false)).toBe("[audit] run");
    expect(formatNoteLine("note", false)).toBe("  note");
  });
});
