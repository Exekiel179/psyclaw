import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  agentManagerRows,
  loadSelectablePersonas,
  readRecommendedAgentsCatalog,
  recommendedAgentsForPanel,
} from "../../src/agents/recommended-personas.js";
import { BUNDLED_PERSONAS } from "../../src/orchestration/bundled-personas.js";

describe("recommended agent personas", () => {
  it("loads the bundled catalog with eight personas", async () => {
    const catalog = await readRecommendedAgentsCatalog();
    expect(catalog.schemaVersion).toBe("psyclaw/recommended-agents/v1");
    expect(catalog.items).toHaveLength(BUNDLED_PERSONAS.length);
    expect(catalog.items.every((item) => item.kind === "agent" && item.bundled === true)).toBe(true);
  });

  it("lists bundled personas for /agents manager and Panel", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-agents-reco-"));
    await mkdir(join(root, ".psyclaw", "agents", "custom"), { recursive: true });
    const rows = await agentManagerRows(root);
    expect(rows.filter((row) => row.source === "bundled")).toHaveLength(8);
    const panel = await recommendedAgentsForPanel(root);
    expect(panel.items.some((item) => item.id === "landscape-mapper" && item.locked === true)).toBe(true);
  });

  it("lets /agents --agent resolve bundled and custom personas", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-agents-select-"));
    const customDir = join(root, ".psyclaw", "agents", "custom");
    await mkdir(customDir, { recursive: true });
    await writeFile(join(customDir, "my-critic.md"), [
      "---",
      "schemaVersion: psyclaw/agent-persona/v1",
      "id: my-critic",
      "label: 我的批判者",
      "role: critic",
      "allowedEffects:",
      "  - read",
      "---",
      "",
      "# 我的批判者",
      "",
      "只读审查。",
      "",
    ].join("\n"), "utf8");
    const personas = await loadSelectablePersonas(root);
    expect(personas.some((persona) => persona.id === "methods-scout")).toBe(true);
    expect(personas.some((persona) => persona.id === "my-critic" && persona.role === "critic")).toBe(true);
  });
});
