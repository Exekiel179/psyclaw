import { lstat, readFile, readdir } from "node:fs/promises";
import { join } from "node:path";
import type { Effect } from "../core/contracts.js";
import { parseCreatedFrontmatter } from "../creation/service.js";
import { assertSafeProjectPath } from "../project/paths.js";
import type { AgentRole, Plan, TaskNode } from "./contracts.js";
import { normalizeEffects } from "./effects.js";

export interface CustomPersona {
  id: string;
  label: string;
  role: AgentRole;
  prompt: string;
  path: string;
  allowedEffects: Effect[];
}

const ROLES = new Set<AgentRole>(["planner", "researcher", "analyst", "critic", "writer", "verifier"]);

export async function loadCustomPersonas(root: string): Promise<CustomPersona[]> {
  const directory = await assertSafeProjectPath(root, ".psyclaw/agents/custom");
  const entries = await readdir(directory, { withFileTypes: true }).catch(() => []);
  const personas: CustomPersona[] = [];
  for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
    if (!entry.isFile() || entry.isSymbolicLink() || !entry.name.endsWith(".md")) continue;
    const path = join(directory, entry.name);
    try {
      const stat = await lstat(path);
      if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 24_000) continue;
      const text = await readFile(path, "utf8");
      const metadata = parseCreatedFrontmatter(text);
      const id = metadata.id;
      const label = metadata.label;
      const role = metadata.role;
      if (metadata.schemaVersion !== "psyclaw/agent-persona/v1" || typeof id !== "string" || typeof label !== "string" || typeof role !== "string" || !ROLES.has(role as AgentRole)) continue;
      const allowedEffects = normalizeEffects(Array.isArray(metadata.allowedEffects) ? metadata.allowedEffects : ["read"]);
      const prompt = text.replace(/^---\s*\n[\s\S]*?\n---\s*/, "").trim();
      personas.push({ id, label, role: role as AgentRole, prompt, path, allowedEffects });
    } catch { /* malformed or raced optional persona: skip this file only */ }
  }
  return personas;
}

export function customPersonaPlan(runId: string, objective: string, personas: readonly CustomPersona[]): Plan {
  if (personas.length < 1 || personas.length > 4) throw new Error("select between one and four custom subagents");
  const tasks: TaskNode[] = personas.map((persona) => ({
    id: persona.id,
    role: persona.role,
    objective: `${persona.prompt}\n\nBounded task: ${objective}`,
    deps: [],
    ownedPaths: [],
    parallelSafe: true,
    inputs: [],
    outputs: [],
    allowedEffects: [...persona.allowedEffects],
    completionContract: { requiredArtifacts: [], requiredReceiptEffects: [], mustPassGates: [] },
  }));
  return {
    schemaVersion: "psyclaw/plan/v1",
    runId,
    tasks,
    budget: { maxTurns: tasks.length, maxWorkers: tasks.length },
    horizon: { strategy: "hierarchical-plan-act-reflect", maxIterations: tasks.length, reflectionEvery: 1 },
  };
}

export function parseAgentsRequest(input: string): { ids: string[]; objective: string } {
  // Codex-style: entire trailing text is the task. Agent selection is via /agents UI.
  return { ids: [], objective: input.trim() };
}
