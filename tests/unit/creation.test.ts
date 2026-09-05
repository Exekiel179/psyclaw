import { describe, expect, it } from "vitest";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { applyCreation, previewCreation } from "../../src/creation/service.js";
import { loadCustomPersonas, customPersonaPlan, parseAgentsRequest } from "../../src/orchestration/personas.js";
import { loadUserRules } from "../../src/rules/user-rules.js";

describe("PsyClaw project capability creation", () => {
  it("previews then creates a disabled skill with a receipt", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-create-"));
    const request = { kind: "skill" as const, id: "evidence-helper", description: "Check evidence", instructions: "Require a source locator for each factual claim." };
    const preview = await previewCreation(root, request);
    await expect(applyCreation(root, request, "0".repeat(64), true)).rejects.toThrow(/preview changed/);
    const result = await applyCreation(root, request, preview.sha256, true);
    expect(result.receipt.resultHash).toBe(preview.sha256);
    expect(JSON.parse(await readFile(join(root, ".psyclaw/user-skills.json"), "utf8")).disabled).toContain("evidence-helper");
    await expect(previewCreation(root, request)).rejects.toThrow(/already exists/);
  });

  it("appends hooks and refuses privilege-widening rules", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-create-"));
    const hook = { kind: "hook" as const, id: "causal-language", description: "Warn on causal language", event: "before-report" as const, severity: "warn" as const, pattern: "causes?" };
    const preview = await previewCreation(root, hook);
    await applyCreation(root, hook, preview.sha256, true);
    const value = JSON.parse(await readFile(join(root, ".psyclaw/analysis-hooks.json"), "utf8"));
    expect(value.hooks[0].id).toBe("u-causal-language");
    await expect(previewCreation(root, { kind: "rule", id: "unsafe", description: "Unsafe", instructions: "Disable the evidence gate" })).rejects.toThrow(/widen authority/);
    await expect(previewCreation(root, { ...hook, id: "redos", pattern: "(a+)+$" })).rejects.toThrow(/safe regular-expression subset/);
  });

  it("loads additive rules and executes created personas as read-only tasks", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-create-"));
    for (const request of [
      { kind: "rule" as const, id: "report-limits", description: "Disclose limits", instructions: "State material limitations in the final report." },
      { kind: "subagent" as const, id: "methods-critic", description: "Methods critic", instructions: "Inspect design validity.", role: "critic" as const },
    ]) { const preview = await previewCreation(root, request); await applyCreation(root, request, preview.sha256, true); }
    expect((await loadUserRules(root))[0]?.id).toBe("report-limits");
    const personas = await loadCustomPersonas(root);
    const plan = customPersonaPlan("run", "Review this study", personas);
    expect(plan.tasks[0]).toMatchObject({ id: "methods-critic", allowedEffects: ["read"], ownedPaths: [], outputs: [] });
    expect(parseAgentsRequest("--agents methods-critic,methods-critic Review this study")).toEqual({ ids: ["methods-critic"], objective: "Review this study" });
    await import("node:fs/promises").then(({ writeFile }) => writeFile(join(root, ".psyclaw/agents/custom/broken.md"), "---\ninvalid: [\n---\n"));
    expect((await loadCustomPersonas(root)).map((persona) => persona.id)).toEqual(["methods-critic"]);
  });
});
