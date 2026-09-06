import { describe, expect, it } from "vitest";
import {
  ACADEMIC_SOFT_ROUTE_SKILLS,
  academicSoftRoutePrompt,
  formatAcademicSoftRouteInvocation,
  isAcademicSoftRouteSkill,
  rankAcademicSoftRoutes,
  resolveAcademicSoftRoute,
} from "../../src/ars/academic-router.js";
import { sessionModePrompt } from "../../src/session/modes.js";

describe("academic soft router", () => {
  it("exposes a fixed allowlist", () => {
    expect(ACADEMIC_SOFT_ROUTE_SKILLS).toContain("nature-figure");
    expect(ACADEMIC_SOFT_ROUTE_SKILLS).toContain("academic-paper-composer");
    expect(isAcademicSoftRouteSkill("nature-figure")).toBe(true);
    expect(isAcademicSoftRouteSkill("academic-grill")).toBe(false);
  });

  it("routes clear natural-language intents to allowlisted skills", () => {
    expect(resolveAcademicSoftRoute("帮我画一张论文配图")?.skill).toBe("nature-figure");
    expect(resolveAcademicSoftRoute("润色一下终稿语言")?.skill).toBe("nature-polishing");
    expect(resolveAcademicSoftRoute("按这个大纲写成全文")?.skill).toBe("academic-paper-composer");
    expect(resolveAcademicSoftRoute("优化写作策略和大纲")?.skill).toBe("academic-paper-strategist");
    expect(resolveAcademicSoftRoute("做一轮同行评审")?.skill).toBe("academic-paper-reviewer");
    expect(resolveAcademicSoftRoute("先做文献调研")?.skill).toBe("deep-research");
    expect(resolveAcademicSoftRoute("写一段文献综述")?.modeHint).toBe("lit-review");
  });

  it("orders multi-skill intents by earliest cue then keeps follow-ups", () => {
    const ranked = rankAcademicSoftRoutes("先优化详细大纲，再按大纲写成全文", 3);
    expect(ranked.map((row) => row.skill)).toEqual([
      "academic-paper-strategist",
      "academic-paper-composer",
    ]);
  });

  it("does not soft-route explicit slash commands or out-of-scope skills", () => {
    expect(resolveAcademicSoftRoute("/skill:academic-grill")).toBeNull();
    expect(resolveAcademicSoftRoute("/ars-lit-review")).toBeNull();
    expect(resolveAcademicSoftRoute("随便聊聊天气")).toBeNull();
    expect(resolveAcademicSoftRoute("请用 academic-grill 对我的方案逐题追问")).toBeNull();
  });

  it("formats an invisible /skill invocation for the host", () => {
    const text = formatAcademicSoftRouteInvocation(
      { skill: "nature-figure", reason: "figure / plotting request", priority: 100 },
      "画一张森林图",
    );
    expect(text.startsWith("/skill:nature-figure")).toBe(true);
    expect(text).toContain("画一张森林图");
    expect(text).toContain("do not ask the user to retype");
  });

  it("embeds the soft-route contract in academic mode prompt only", () => {
    const academic = sessionModePrompt("academic");
    expect(academic).toContain("Academic soft-route");
    expect(academic).toContain("nature-figure");
    expect(academicSoftRoutePrompt()).toContain("explicitly");
    expect(academicSoftRoutePrompt()).toContain("/skill:<name>");
    expect(sessionModePrompt("analysis")).not.toContain("Academic soft-route");
    expect(sessionModePrompt("chat")).not.toContain("Academic soft-route");
  });
});
