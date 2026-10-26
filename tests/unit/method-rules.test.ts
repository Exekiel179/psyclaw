import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  METHOD_INJECT_CHAR_BUDGET,
  RESIDENT_METHOD_RULES,
  loadCoreMethodSkills,
  methodTopicsIn,
  renderMethodBlocks,
  type InjectionBlock,
} from "../../src/analysis/method-rules.js";
import {
  composeMethodInjection,
  preferenceKey,
  readSkillPreferences,
  resetInjectedTopicsForTests,
  selectOrDefault,
  userSkillsOutsideScriptOnly,
  writeSkillPreferences,
} from "../../src/analysis/skill-resolution.js";
import { formatAnalysisPlanTakeover, resolveStatsIntent } from "../../src/analysis/stats-router.js";
import { defaultAnalysisPlan } from "../../src/project/workspace.js";
import { sessionModePrompt, unattendedAnalysisPrompt } from "../../src/session/modes.js";
import { setDataAccess } from "../../src/safety/data-access.js";
import { enabledLocalSkillPaths } from "../../src/skills/user-skills.js";

const roots: string[] = [];

afterEach(async () => {
  resetInjectedTopicsForTests();
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
});

async function tempRoot(): Promise<string> {
  const root = await mkdtemp(join(tmpdir(), "psyclaw-method-"));
  roots.push(root);
  return root;
}

describe("method topic detection", () => {
  it("returns the topics named by the request", () => {
    expect(methodTopicsIn("做一下调节，并报告简单斜率")).toEqual(["interactions"]);
    expect(methodTopicsIn("配对样本的差分，先看总体变化")).toEqual(["change-scores"]);
    expect(methodTopicsIn("中介效应")).toContain("mediation");
    expect(methodTopicsIn("多层模型和随机截距")).toEqual(["multilevel"]);
    expect(methodTopicsIn("跑一个 SEM")).toEqual(["sem"]);
    expect(methodTopicsIn("请写 results/report.md")).toEqual(["report"]);
  });

  it("does not invent a topic for a generic analysis request", () => {
    expect(methodTopicsIn("帮我分析这个 csv")).toEqual([]);
  });

  it("skips soft routing when the message names a loaded user skill", () => {
    expect(resolveStatsIntent("用 my-moderation 做调节分析", { userSkillNames: ["my-moderation"] })).toBeNull();
    expect(resolveStatsIntent("/skill:my-moderation 做调节")).toBeNull();
    expect(resolveStatsIntent("做一下调节分析")?.topics).toEqual(["interactions"]);
  });
});

describe("method injection", () => {
  it("injects the core body once, inside the takeover text", async () => {
    const cwd = await tempRoot();
    const first = await composeMethodInjection({
      cwd,
      topics: ["interactions"],
      seen: new Set(),
      hasUI: false,
      userSkills: [],
    });
    expect(first.text).toContain("topic=interactions");
    expect(first.text).toContain("simple slope");
    expect(first.text).toContain("Gelman");
    const takeover = formatAnalysisPlanTakeover("做一下调节分析", first.text);
    expect(takeover.startsWith("/skill:analysis-plan")).toBe(true);
    expect(takeover).toContain("[psyclaw:method-skill");

    const again = await composeMethodInjection({
      cwd,
      topics: ["interactions"],
      seen: new Set(["interactions"]),
      hasUI: false,
      userSkills: [],
    });
    expect(again.text).toBe("");
  });

  it("replaces an over-budget body with a catalog line", () => {
    const block: InjectionBlock = {
      topic: "sem",
      skill: "method-sem",
      path: "/skills/method-sem",
      source: "core",
      body: "x".repeat(METHOD_INJECT_CHAR_BUDGET + 10),
    };
    const rendered = renderMethodBlocks([block], 100);
    expect(rendered.included).toEqual([]);
    expect(rendered.catalog).toEqual(["sem"]);
    expect(rendered.text).toContain("[psyclaw:method-catalog]");
    expect(rendered.text).toContain("/skills/method-sem");
    expect(rendered.text).not.toContain("x".repeat(50));
  });

  it("defaults a topic conflict to the user skill, and a saved choice sticks", async () => {
    const cwd = await tempRoot();
    const userSkills = [{
      name: "my-moderation",
      path: join(cwd, ".psyclaw", "skills", "my-moderation"),
      description: "Project moderation rules",
      topics: ["interactions"],
      body: "USER BODY slopes",
    }];
    const first = await composeMethodInjection({
      cwd,
      topics: ["interactions"],
      seen: new Set(),
      hasUI: false,
      userSkills,
    });
    expect(first.text).toContain("项目中有用户 skill my-moderation");
    expect(first.text).toContain("USER BODY slopes");
    expect(first.text).not.toContain("Gelman");
    expect((await readSkillPreferences(cwd)).choices[preferenceKey("interactions", "my-moderation")]).toBe("user");

    resetInjectedTopicsForTests();
    await writeSkillPreferences(cwd, {
      schemaVersion: "psyclaw/skill-preferences/v1",
      choices: { [preferenceKey("interactions", "my-moderation")]: "core" },
    });
    const saved = await composeMethodInjection({
      cwd,
      topics: ["interactions"],
      seen: new Set(),
      hasUI: true,
      select: async () => { throw new Error("saved choice must not ask again"); },
      userSkills,
    });
    expect(saved.text).toContain("Gelman");
    expect(saved.text).not.toContain("USER BODY slopes");
  });

  it("uses the user skill when the choice card times out, and reset makes the next conflict ask again", async () => {
    const cwd = await tempRoot();
    const userSkills = [{
      name: "my-moderation",
      path: join(cwd, "skills", "my-moderation"),
      description: "moderation",
      topics: ["interactions"],
      body: "USER AFTER TIMEOUT",
    }];
    const timedOut = await composeMethodInjection({
      cwd,
      topics: ["interactions"],
      seen: new Set(),
      hasUI: true,
      choiceTimeoutMs: 20,
      select: () => new Promise(() => undefined),
      userSkills,
    });
    expect(timedOut.text).toContain("USER AFTER TIMEOUT");

    await writeSkillPreferences(cwd, { schemaVersion: "psyclaw/skill-preferences/v1", choices: {} });
    let asked = 0;
    resetInjectedTopicsForTests();
    const askedAgain = await composeMethodInjection({
      cwd,
      topics: ["interactions"],
      seen: new Set(),
      hasUI: true,
      choiceTimeoutMs: 1_000,
      select: async () => {
        asked += 1;
        return "两者都注入，冲突时以用户 skill 为准";
      },
      userSkills,
    });
    expect(asked).toBe(1);
    expect(askedAgain.text).toContain("USER AFTER TIMEOUT");
    expect(askedAgain.text).toContain("Gelman");
    expect((await readSkillPreferences(cwd)).choices[preferenceKey("interactions", "my-moderation")]).toBe("both");
  });

  it("returns undefined when select never settles", async () => {
    await expect(selectOrDefault(() => new Promise(() => undefined), 20)).resolves.toBeUndefined();
  });
});

describe("resident method rules", () => {
  it("keeps the standing rules short and in the plan and the analysis prompt", () => {
    expect(RESIDENT_METHOD_RULES.length).toBeLessThan(900);
    expect(defaultAnalysisPlan()).toContain(RESIDENT_METHOD_RULES);
    expect(defaultAnalysisPlan()).not.toContain("Repeated stimuli");
    expect(sessionModePrompt("analysis")).toContain(RESIDENT_METHOD_RULES);
    expect(sessionModePrompt("chat")).not.toContain("Standing method rules");
  });

  it("lets an unattended run read listed skills", () => {
    const prompt = unattendedAnalysisPrompt();
    expect(prompt).not.toContain(".psyclaw/");
    expect(prompt).toContain("Skills listed in the system prompt may be read");
    expect(prompt).toContain("HANDOFF");
  });

  it("ships a core skill body for each method topic", async () => {
    const skills = await loadCoreMethodSkills();
    const byTopic = new Map(skills.map((skill) => [skill.topic, skill.body]));
    expect(byTopic.get("change-scores")).toContain("Lord");
    expect(byTopic.get("interactions")).toContain("Johnson-Neyman");
    expect(byTopic.get("mediation")).toContain("bootstrap");
    expect(byTopic.get("multilevel")).toContain("random intercept");
    expect(byTopic.get("sem")).toContain("identified");
    expect(byTopic.get("report")).toContain("JARS-Quant");
    expect(byTopic.get("report")).not.toContain("| Design |");
  });
});

describe("same-name core skills", () => {
  it("records a skipped user skill instead of loading it", async () => {
    const root = await tempRoot();
    const skill = join(root, ".psyclaw", "skills", "analysis-plan");
    await mkdir(skill, { recursive: true });
    await writeFile(join(skill, "SKILL.md"), "---\nname: analysis-plan\ndescription: Duplicate core\n---\n", "utf8");
    const loaded = await enabledLocalSkillPaths(root, { excludedNames: ["analysis-plan"] });
    expect(loaded.paths).not.toContain(skill);
    expect(loaded.skipped).toContainEqual({ name: "analysis-plan", path: skill, reason: "core-name" });
    expect(await readFile(join(skill, "SKILL.md"), "utf8")).toContain("Duplicate core");
  });

  it("does not read a user skill stored under a script-only path", async () => {
    const root = await tempRoot();
    const skill = join(root, ".psyclaw", "skills", "secret-moderation");
    await mkdir(skill, { recursive: true });
    await writeFile(join(skill, "SKILL.md"), "---\nname: secret-moderation\ndescription: moderation\ntopics:\n  - interactions\n---\nSECRET BODY\n", "utf8");
    await setDataAccess(root, ".psyclaw/skills", "script-only");
    const found = await userSkillsOutsideScriptOnly(root);
    expect(found.some((item) => item.body.includes("SECRET BODY"))).toBe(false);
  });
});
