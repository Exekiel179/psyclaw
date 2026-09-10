import { mkdir, readFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { atomicWriteFile } from "../project/jsonl.js";

export const AGENT_PERSONAS_SCHEMA = "psyclaw/agent-personas/v1" as const;

export interface AgentPersona {
  name: string;
  prompt: string;
  updatedAt: string;
}

export interface AgentPersonaState {
  schemaVersion: typeof AGENT_PERSONAS_SCHEMA;
  active: string | null;
  personas: Record<string, AgentPersona>;
}

const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
const MAX_PROMPT_CHARS = 12_000;

function emptyState(): AgentPersonaState {
  return { schemaVersion: AGENT_PERSONAS_SCHEMA, active: null, personas: {} };
}

export function personasPath(root: string): string {
  return join(resolve(root), ".psyclaw", "agents", "personas.json");
}

export function assertPersonaName(name: string): string {
  const value = name.trim();
  if (!NAME_RE.test(value)) {
    throw new Error("人设名称须为 1–64 位字母/数字/._-，且以字母或数字开头");
  }
  return value;
}

export function assertPersonaPrompt(prompt: string): string {
  const value = prompt.trim();
  if (!value) throw new Error("人设提示词不能为空");
  if (value.length > MAX_PROMPT_CHARS) {
    throw new Error(`人设提示词过长（最多 ${MAX_PROMPT_CHARS} 字符）`);
  }
  return value;
}

export async function readAgentPersonaState(root: string): Promise<AgentPersonaState> {
  try {
    const raw = JSON.parse(await readFile(personasPath(root), "utf8")) as unknown;
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return emptyState();
    const record = raw as Record<string, unknown>;
    if (record.schemaVersion !== AGENT_PERSONAS_SCHEMA) return emptyState();
    const personas: Record<string, AgentPersona> = {};
    if (record.personas && typeof record.personas === "object" && !Array.isArray(record.personas)) {
      for (const [key, value] of Object.entries(record.personas as Record<string, unknown>)) {
        if (!value || typeof value !== "object" || Array.isArray(value)) continue;
        const item = value as Record<string, unknown>;
        if (typeof item.name !== "string" || typeof item.prompt !== "string" || typeof item.updatedAt !== "string") continue;
        try {
          const name = assertPersonaName(item.name);
          personas[name] = {
            name,
            prompt: assertPersonaPrompt(item.prompt),
            updatedAt: item.updatedAt,
          };
        } catch {
          /* skip invalid entries */
        }
      }
    }
    const active = typeof record.active === "string" && personas[record.active] ? record.active : null;
    return { schemaVersion: AGENT_PERSONAS_SCHEMA, active, personas };
  } catch {
    return emptyState();
  }
}

async function writeAgentPersonaState(root: string, state: AgentPersonaState): Promise<void> {
  const path = personasPath(root);
  await mkdir(dirname(path), { recursive: true });
  await atomicWriteFile(path, `${JSON.stringify(state, null, 2)}\n`);
}

export async function listAgentPersonas(root: string): Promise<AgentPersonaState> {
  return readAgentPersonaState(root);
}

export async function getAgentPersona(root: string, name: string): Promise<AgentPersona | undefined> {
  const state = await readAgentPersonaState(root);
  return state.personas[assertPersonaName(name)];
}

export async function setAgentPersona(
  root: string,
  name: string,
  prompt: string,
  now = () => new Date().toISOString(),
): Promise<AgentPersona> {
  const id = assertPersonaName(name);
  const text = assertPersonaPrompt(prompt);
  const state = await readAgentPersonaState(root);
  const persona: AgentPersona = { name: id, prompt: text, updatedAt: now() };
  state.personas[id] = persona;
  await writeAgentPersonaState(root, state);
  return persona;
}

export async function useAgentPersona(root: string, name: string): Promise<AgentPersona> {
  const id = assertPersonaName(name);
  const state = await readAgentPersonaState(root);
  const persona = state.personas[id];
  if (!persona) throw new Error(`未找到人设：${id}`);
  state.active = id;
  await writeAgentPersonaState(root, state);
  return persona;
}

export async function clearActiveAgentPersona(root: string): Promise<void> {
  const state = await readAgentPersonaState(root);
  state.active = null;
  await writeAgentPersonaState(root, state);
}

export async function deleteAgentPersona(root: string, name: string): Promise<void> {
  const id = assertPersonaName(name);
  const state = await readAgentPersonaState(root);
  if (!state.personas[id]) throw new Error(`未找到人设：${id}`);
  delete state.personas[id];
  if (state.active === id) state.active = null;
  await writeAgentPersonaState(root, state);
}

/** Prompt fragment for the currently active persona, if any. */
export async function activeAgentPersonaPatch(root: string): Promise<string | undefined> {
  const state = await readAgentPersonaState(root);
  if (!state.active) return undefined;
  const persona = state.personas[state.active];
  if (!persona) return undefined;
  return [
    "## Active agent persona",
    `Persona name: ${persona.name}`,
    "Adopt the following researcher persona for this turn. Do not claim tools, skills, or evidence that were not actually used. Do not override PsyClaw core safety, evidence, or citation gates.",
    persona.prompt,
  ].join("\n");
}

export function formatAgentPersonaStatus(
  state: AgentPersonaState,
  options: { developer?: boolean } = {},
): string {
  const names = Object.keys(state.personas).sort();
  if (names.length === 0) {
    const lines = [
      "当前无人设。",
      "用法：",
      "  /agents set <name> <prompt>",
      "  /agents use <name>",
      "  /agents clear",
    ];
    if (options.developer) lines.push("  /agents run <bounded read-only research task>");
    return lines.join("\n");
  }
  const lines = ["Agent 人设：", `当前启用：${state.active ?? "（无）"}`, ""];
  for (const name of names) {
    const persona = state.personas[name]!;
    const preview = persona.prompt.replace(/\s+/g, " ").slice(0, 80);
    lines.push(`- ${name}${state.active === name ? " *" : ""} — ${preview}${persona.prompt.length > 80 ? "…" : ""}`);
  }
  lines.push("", "管理：/agents show|set|use|clear|delete <name>");
  if (options.developer) lines.push("开发者：/agents run <bounded read-only research task>");
  return lines.join("\n");
}
