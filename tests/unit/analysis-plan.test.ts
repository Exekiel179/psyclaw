import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  advanceAnalysisPlan,
  createAnalysisPlan,
  formatAnalysisPlanStatus,
  readActiveAnalysisPlan,
  syncHandoffFromAnalysisPlan,
  writeAnalysisPlan,
} from "../../src/analysis/plan.js";
import {
  analysisSoftRoutePrompt,
  formatAnalysisPlanTakeover,
  resolveStatsIntent,
} from "../../src/analysis/stats-router.js";
import { sessionModePrompt } from "../../src/session/modes.js";
import { ensureProjectDirectories } from "../../src/project/paths.js";

const roots: string[] = [];

afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
});

async function tempRoot(): Promise<string> {
  const root = await mkdtemp(join(tmpdir(), "psyclaw-plan-"));
  roots.push(root);
  await ensureProjectDirectories(root);
  return root;
}

describe("stats intent router", () => {
  it("matches clear analysis intents", () => {
    expect(resolveStatsIntent("帮我分析一下这个 csv")?.kind).toBe("stats-analysis");
    expect(resolveStatsIntent("做独立样本 t 检验")?.kind).toBe("stats-analysis");
    expect(resolveStatsIntent("先写个统计方案")?.kind).toBe("stats-analysis");
  });

  it("skips slash commands and academic-dominant asks", () => {
    expect(resolveStatsIntent("/plan status")).toBeNull();
    expect(resolveStatsIntent("/skill:analysis-plan")).toBeNull();
    expect(resolveStatsIntent("帮我写论文终稿")).toBeNull();
    expect(resolveStatsIntent("随便聊聊天气")).toBeNull();
  });

  it("formats takeover text for the host", () => {
    const text = formatAnalysisPlanTakeover("跑一下回归分析");
    expect(text.startsWith("/skill:analysis-plan")).toBe(true);
    expect(text).toContain("跑一下回归分析");
    expect(text).toContain("reproducible scripts");
    expect(text).toContain("/plan");
    expect(text).toContain("我已审阅并批准本方案");
  });

  it("embeds soft-route contract in analysis mode prompt only", () => {
    expect(sessionModePrompt("analysis")).toContain("Analysis soft-route");
    expect(sessionModePrompt("analysis")).toContain("/plan");
    expect(sessionModePrompt("analysis")).toContain("我已审阅并批准本方案");
    expect(analysisSoftRoutePrompt()).toContain("analysis-plan");
    expect(sessionModePrompt("academic")).not.toContain("Analysis soft-route");
    expect(sessionModePrompt("academic")).toContain("/grill");
    expect(sessionModePrompt("academic")).toContain("/brainstorm");
    expect(sessionModePrompt("chat")).not.toContain("Analysis soft-route");
  });
});

describe("analysis plan store", () => {
  it("persists active plan through confirm → review → run/defer", async () => {
    const root = await tempRoot();
    let plan = await writeAnalysisPlan(root, createAnalysisPlan({
      goal: "比较两组焦虑得分",
      confirmatory: true,
      now: "2026-09-07T00:00:00.000Z",
    }));
    expect(plan.status).toBe("clarifying");

    plan = advanceAnalysisPlan(plan, {
      type: "draft",
      primaryOutcome: "anxiety_score",
      primaryAnalysis: "independent-samples t-test",
      proposedMethods: ["independent-samples t-test", "Welch t-test"],
      missingDataPlan: "listwise deletion if <5%",
      multiplicityPlan: "not applicable (single primary)",
      exclusionCriteria: "incomplete primary outcome",
      exploratoryAnalyses: [],
    });
    expect(plan.status).toBe("awaiting-confirm");

    plan = advanceAnalysisPlan(plan, { type: "confirm", method: "Welch t-test", backend: "local-script" });
    plan = advanceAnalysisPlan(plan, { type: "review" });
    plan = await writeAnalysisPlan(root, plan);
    expect(plan.status).toBe("ready");
    expect(plan.confirmedMethod).toBe("Welch t-test");

    const blocked = advanceAnalysisPlan(plan, { type: "run-now" });
    expect(blocked.status).toBe("ready");
    expect(blocked.notes).toMatch(/我已审阅并批准本方案/);

    plan = advanceAnalysisPlan(plan, { type: "ritual-approve", text: "我已审阅并批准本方案" });
    plan = advanceAnalysisPlan(plan, { type: "run-now" });
    expect(plan.status).toBe("running");
    expect(plan.ritualApproval?.text).toBe("我已审阅并批准本方案");

    plan = advanceAnalysisPlan({ ...plan, status: "ready", runPreference: "unset" }, { type: "defer" });
    plan = await writeAnalysisPlan(root, plan);
    expect(plan.status).toBe("deferred");

    const active = await readActiveAnalysisPlan(root);
    expect(active?.id).toBe(plan.id);
    expect(formatAnalysisPlanStatus(plan)).toContain(plan.id);

    const md = await readFile(join(root, "analysis", "plans", `${plan.id}.md`), "utf8");
    expect(md).toContain("Welch t-test");

    const handoff = await syncHandoffFromAnalysisPlan(root, plan);
    expect(handoff).toBe("analysis/HANDOFF.md");
    const handoffText = await readFile(join(root, "analysis", "HANDOFF.md"), "utf8");
    expect(handoffText).toContain(plan.id);
  });
});
