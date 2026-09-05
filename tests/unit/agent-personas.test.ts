import { describe, expect, it } from "vitest";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  activeAgentPersonaPatch,
  clearActiveAgentPersona,
  deleteAgentPersona,
  formatAgentPersonaStatus,
  getAgentPersona,
  listAgentPersonas,
  setAgentPersona,
  useAgentPersona,
} from "../../src/agents/personas.js";

describe("agent personas", () => {
  it("stores, activates, and clears persona prompts under .psyclaw/agents", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-personas-"));
    await setAgentPersona(root, "reviewer", "你是严格的方法学审稿人。");
    await setAgentPersona(root, "writer", "你是谨慎的学术写作者。");

    const listed = await listAgentPersonas(root);
    expect(Object.keys(listed.personas).sort()).toEqual(["reviewer", "writer"]);
    expect(listed.active).toBeNull();

    await useAgentPersona(root, "reviewer");
    expect((await listAgentPersonas(root)).active).toBe("reviewer");
    expect(await getAgentPersona(root, "reviewer")).toMatchObject({
      name: "reviewer",
      prompt: "你是严格的方法学审稿人。",
    });

    const patch = await activeAgentPersonaPatch(root);
    expect(patch).toContain("reviewer");
    expect(patch).toContain("你是严格的方法学审稿人。");
    expect(patch).toContain("Do not override PsyClaw core safety");

    const status = formatAgentPersonaStatus(await listAgentPersonas(root), { developer: true });
    expect(status).toContain("reviewer *");
    expect(status).toContain("/agents run");

    await clearActiveAgentPersona(root);
    expect(await activeAgentPersonaPatch(root)).toBeUndefined();

    await deleteAgentPersona(root, "writer");
    expect(await getAgentPersona(root, "writer")).toBeUndefined();

    const raw = JSON.parse(await readFile(join(root, ".psyclaw", "agents", "personas.json"), "utf8"));
    expect(raw.schemaVersion).toBe("psyclaw/agent-personas/v1");
    expect(raw.active).toBeNull();
    expect(Object.keys(raw.personas)).toEqual(["reviewer"]);
  });

  it("rejects invalid persona names and empty prompts", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-personas-invalid-"));
    await expect(setAgentPersona(root, "../x", "ok")).rejects.toThrow(/名称/);
    await expect(setAgentPersona(root, "ok", "   ")).rejects.toThrow(/提示词|不能为空/);
  });
});
