import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { checkDecisionPoints } from "../../src/analysis/decision-points.js";
import { checkPlanScript, checkRecall, recalledApproachIds } from "../../src/analysis/prior/checks.js";
import { isBriefPath, isDataPath, priorToolBlock } from "../../src/analysis/prior/gate.js";
import { parseConstants } from "../../src/analysis/prior/constants.js";
import { layerCards, renderPriorPlan } from "../../src/analysis/prior/render.js";
import { recordPriorApproval, submitPriorRecall, submitPriorScript } from "../../src/analysis/prior/submit.js";
import { nextSessionMode, parseSessionMode, sessionModePrompt } from "../../src/session/modes.js";

const RECALL = [
  "## H1",
  "- construct: the outcome is usually a mean of the scale items",
  "- internal validity: compare the randomised groups; attrition can change who remains",
  "- statistical conclusion: a linear model, or a robust one if residuals are heavy",
  "- dependence: none; H1 does not change how H2 is analysed",
].join("\n");

const SCRIPT = [
  "# H1",
  "PRIMARY_MODEL = \"ols\"  # @intent ols | robust_hc3 — both are common and can change the H1 verdict",
  "EXCLUSION = \"none\"  # @intent none | drop_attention — who remains can change the H1 verdict",
  "ALPHA = 0.05  # @declare — conventional two-sided alpha; not a question",
  "",
  "def test_h1(df):",
  "    model = PRIMARY_MODEL",
  "    rule = EXCLUSION",
  "    return model, rule",
  "",
].join("\n");

describe("prior mode", () => {
  it("is the mode after academic", () => {
    expect(nextSessionMode("academic")).toBe("prior");
    expect(nextSessionMode("prior")).toBe("chat");
    expect(parseSessionMode("prior")).toBe("prior");
    expect(sessionModePrompt("prior")).toContain("psyclaw_submit_recall");
    expect(sessionModePrompt("analysis")).not.toContain("psyclaw_submit_recall");
  });

  it("reads a next-line label and an R assignment", () => {
    const constants = parseConstants([
      "# H2",
      "SCORE <- \"sum\"",
      "# @declare — the published scoring is a sum",
    ].join("\n"));
    expect(constants).toEqual([
      expect.objectContaining({ name: "SCORE", value: "sum", label: "declare", group: "H2" }),
    ]);
  });

  it("rejects a recall that skips a slot and a script that asks about alpha", () => {
    expect(checkRecall("## H1\n- construct: mean")).toEqual(expect.arrayContaining([
      expect.stringContaining("internal validity"),
    ]));
    const asked = checkPlanScript(SCRIPT.replace("ALPHA = 0.05  # @declare — conventional two-sided alpha; not a question", "ALPHA = 0.05  # @intent 0.05 | 0.01 — which threshold"), RECALL);
    expect(asked.some((problem) => problem.includes("stage 4"))).toBe(true);
  });

  it("rejects an @intent constant that only a description uses, and a recalled approach that is not an option", () => {
    const descriptive = [
      "UNUSED = \"keep\"  # @intent keep | drop — could change a verdict",
      "def describe_sample(df):",
      "    return UNUSED",
      "",
      SCRIPT,
    ].join("\n");
    expect(checkPlanScript(descriptive, RECALL).some((problem) => problem.startsWith("UNUSED"))).toBe(true);
    const recall = `${RECALL}\n- sum_score: sum of the items`;
    expect(recalledApproachIds(recall)).toContain("sum_score");
    expect(checkPlanScript(SCRIPT, recall).some((problem) => problem.includes("sum_score"))).toBe(true);
  });

  it("layers core, technical, and dependent cards", () => {
    expect(layerCards(SCRIPT, 1).map((card) => [card.id, card.tier])).toEqual([
      ["PRIMARY_MODEL", "core"],
      ["EXCLUSION", "technical"],
    ]);
    const dependent = SCRIPT.replace(
      "EXCLUSION = \"none\"  # @intent none | drop_attention — who remains can change the H1 verdict",
      "EXCLUSION = \"none\"  # @intent none | drop_attention — (if PRIMARY_MODEL == robust_hc3) who remains can change the H1 verdict",
    );
    expect(layerCards(dependent, 8).find((card) => card.id === "EXCLUSION")?.tier).toBe("later");
  });

  it("renders decision points the existing plan check accepts", () => {
    const rendered = renderPriorPlan(SCRIPT, 8);
    expect(rendered.findings).toEqual([]);
    expect(rendered.markdown).toContain("| PRIMARY_MODEL |");
    expect(rendered.markdown).toContain("| intent |");
    expect(rendered.markdown).toContain("| ALPHA |");
    expect(rendered.markdown).toContain("| convention |");
    expect(checkDecisionPoints(rendered.markdown)).toEqual([]);
  });

  it("blocks data until recall, then still blocks outcome runs", () => {
    expect(isBriefPath("notes/BRIEF.md")).toBe(true);
    expect(isDataPath("data/raw/scores.csv")).toBe(true);
    expect(priorToolBlock("analysis", "bash", { command: "python3 -c '1'" }, false)).toBeUndefined();
    expect(priorToolBlock("prior", "read", { path: "psyclaw.md" }, false)).toBeUndefined();
    expect(priorToolBlock("prior", "read", { path: "data/scores.csv" }, false)).toContain("psyclaw_submit_recall");
    expect(priorToolBlock("prior", "bash", { command: "python3 -c '1'" }, false)).toContain("psyclaw_submit_recall");
    expect(priorToolBlock("prior", "psyclaw_data_profile", { path: "data/scores.csv" }, true)).toBeUndefined();
    expect(priorToolBlock("prior", "psyclaw_run_analysis", {}, true)).toContain("analysis");
    expect(priorToolBlock("prior", "bash", { command: "python3 analysis/scripts/analysis.py" }, true)).toContain("analysis");
  });

  it("records recall, reflects once, then writes the plan", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-prior-"));
    const recall = await submitPriorRecall(root, RECALL);
    expect(recall.accepted).toBe(true);
    const reflected = [
      "DROP = \"keep\"  # @pseudo — in this data nobody is removed",
      SCRIPT,
    ].join("\n");
    const first = await submitPriorScript(root, reflected);
    expect(first.reflect).toBe(true);
    expect(first.accepted).toBe(false);
    const second = await submitPriorScript(root, reflected);
    expect(second.accepted).toBe(true);
    expect(second.scriptPath).toBe("analysis/scripts/analysis.py");
    const plan = await readFile(join(root, "analysis/plans/plan.md"), "utf8");
    expect(plan).toContain("## Core questions");
    expect(checkDecisionPoints(plan)).toEqual([]);
    expect((await recordPriorApproval(root)).ok).toBe(true);
  });

  it("honours coreN and an R script path", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-prior-r-"));
    await submitPriorRecall(root, RECALL);
    await writeFile(join(root, ".psyclaw/prior.json"), "{ \"coreN\": 1 }\n", "utf8");
    const r = [
      "library(stats)",
      "# H1",
      "PRIMARY_MODEL <- \"ols\"  # @intent ols | robust_hc3 — both can change the H1 verdict",
      "EXCLUSION <- \"none\"  # @intent none | drop_attention — who remains can change the H1 verdict",
      "ALPHA <- 0.05  # @declare — conventional alpha",
      "test_h1 <- function(df) {",
      "  PRIMARY_MODEL",
      "  EXCLUSION",
      "}",
    ].join("\n");
    const result = await submitPriorScript(root, r);
    expect(result.accepted).toBe(true);
    expect(result.scriptPath).toBe("analysis/scripts/analysis.R");
    expect(result.message).toContain("EXCLUSION");
    expect(result.message).toContain("Technical settings, one confirmation card");
  });
});
