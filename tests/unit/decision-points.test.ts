import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { checkDecisionPoints, decisionPointsNotice, tableRowsUnder } from "../../src/analysis/decision-points.js";
import { runAnalysisEntrypoint } from "../../src/analysis/runtime-tools.js";
import { defaultAnalysisPlan } from "../../src/project/workspace.js";

const FILLED = [
  "# Analysis plan",
  "",
  "## Decision points",
  "",
  "| ID | Decision | Options | Settled by | Primary | Alternative (sensitivity) |",
  "| --- | --- | --- | --- | --- | --- |",
  "| DP1 | Groups | separate / pooled | intent | separate per group | pooled model with group term |",
  "| DP2 | Effect size | g / d | convention | g | |",
  "",
  "## Verdict rules",
  "",
  "| Hypothesis | Test | Alpha and multiplicity family | Counts as supported if |",
  "| --- | --- | --- | --- |",
  "| H1 | random-effects mean | .05, none | g > 0 and p < .05 |",
  "",
].join("\n");

describe("decision points", () => {
  it("reads the rows of the table under a heading and stops at the next heading", () => {
    const rows = tableRowsUnder(FILLED, "## Decision points");
    expect(rows).toHaveLength(2);
    expect(rows[0]?.["settled by"]).toBe("intent");
    expect(rows[1]?.["alternative (sensitivity)"]).toBe("");
  });

  it("accepts a complete plan", () => {
    expect(checkDecisionPoints(FILLED)).toEqual([]);
  });

  it("flags the empty template, an unknown source, and an intent row without a sensitivity analysis", () => {
    const empty = checkDecisionPoints(defaultAnalysisPlan());
    expect(empty.some((finding) => finding.startsWith("No decision points recorded"))).toBe(true);
    expect(empty.some((finding) => finding.startsWith("No verdict rules locked"))).toBe(true);
    const bad = checkDecisionPoints(FILLED
      .replace("| convention |", "| framework rule |")
      .replace("| pooled model with group term |", "| |"));
    expect(bad).toContain('Decision DP2: "Settled by" must be one of brief, data, convention, intent.');
    expect(bad.some((finding) => finding.startsWith("Decision DP1 depends on researcher intent: run the main alternative"))).toBe(true);
  });

  it("adds a non-blocking plan check to a fresh run only while the plan is incomplete", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-decision-points-"));
    await mkdir(join(root, "analysis/scripts"), { recursive: true });
    await mkdir(join(root, "analysis/plans"), { recursive: true });
    await writeFile(join(root, "analysis/scripts/run_all.R"), "cat(1)\n", "utf8");
    expect(await decisionPointsNotice(root)).toBeUndefined();
    await writeFile(join(root, "analysis/plans/plan.md"), defaultAnalysisPlan(), "utf8");
    const run = async () => ({ exitCode: 0, stdout: "ok\n", stderr: "" });
    const first = await runAnalysisEntrypoint(root, { run });
    expect(first).toContain("Plan check (analysis/plans/plan.md), not a blocker");
    await writeFile(join(root, "analysis/plans/plan.md"), FILLED, "utf8");
    const second = await runAnalysisEntrypoint(root, { run, force: true });
    expect(second).not.toContain("Plan check");
  });
});
