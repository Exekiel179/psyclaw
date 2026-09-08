import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { BUNDLED_PERSONAS } from "../orchestration/bundled-personas.js";
import { loadCustomPersonas, type CustomPersona } from "../orchestration/personas.js";

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export interface RecommendedAgentItem {
  id: string;
  name: string;
  kind: "agent";
  pack?: string;
  role?: string;
  stage?: string;
  description?: string;
  sourceRef?: string;
  bundled?: boolean;
  [key: string]: unknown;
}

export interface RecommendedAgentsCatalog {
  schemaVersion: "psyclaw/recommended-agents/v1";
  documentVersion: string;
  sourceRef?: string;
  repositoryHint?: string;
  items: RecommendedAgentItem[];
  installPrep: unknown[];
}

function catalogCandidates(): string[] {
  const moduleDir = dirname(fileURLToPath(import.meta.url));
  return [
    join(moduleDir, "..", "..", "agents", "recommended", "catalog.json"),
    join(moduleDir, "..", "..", "..", "agents", "recommended", "catalog.json"),
    join(process.cwd(), "agents", "recommended", "catalog.json"),
  ];
}

/** Load the recommended-agent catalog; fall back to in-code bundled personas. */
export async function readRecommendedAgentsCatalog(): Promise<RecommendedAgentsCatalog> {
  for (const path of catalogCandidates()) {
    try {
      const value = JSON.parse(await readFile(path, "utf8")) as unknown;
      if (!isRecord(value) || value.schemaVersion !== "psyclaw/recommended-agents/v1" || !Array.isArray(value.items)) {
        continue;
      }
      if (value.items.some((item) => !isRecord(item) || item.kind !== "agent" || typeof item.id !== "string" || typeof item.name !== "string")) {
        continue;
      }
      return {
        schemaVersion: "psyclaw/recommended-agents/v1",
        documentVersion: typeof value.documentVersion === "string" ? value.documentVersion : "0",
        ...(typeof value.sourceRef === "string" ? { sourceRef: value.sourceRef } : {}),
        ...(typeof value.repositoryHint === "string" ? { repositoryHint: value.repositoryHint } : {}),
        items: value.items as RecommendedAgentItem[],
        installPrep: Array.isArray(value.installPrep) ? value.installPrep : [],
      };
    } catch {
      // try next layout
    }
  }
  return {
    schemaVersion: "psyclaw/recommended-agents/v1",
    documentVersion: "bundled-fallback",
    sourceRef: "bundled",
    repositoryHint: "对齐 Claude Code subagent；外仓可后续加入 installPrep。",
    items: BUNDLED_PERSONAS.map((persona) => ({
      id: persona.id,
      name: persona.label,
      kind: "agent" as const,
      pack: persona.pack,
      role: persona.role,
      stage: persona.stage,
      description: persona.description,
      sourceRef: "bundled",
      bundled: true,
    })),
    installPrep: [],
  };
}

export interface AgentManagerRow {
  id: string;
  name: string;
  description: string;
  source: "bundled" | "custom";
  role: string;
  stage: string;
  sourceRef: string;
  status: "core" | "enabled";
}

/** Rows for `/agents` manager and Panel: bundled core personas + project custom personas. */
export async function agentManagerRows(root: string): Promise<AgentManagerRow[]> {
  const catalog = await readRecommendedAgentsCatalog();
  const bundledRows: AgentManagerRow[] = catalog.items
    .filter((item) => item.bundled === true || item.sourceRef === "bundled")
    .map((item) => ({
      id: item.id,
      name: item.name,
      description: typeof item.description === "string" ? item.description : "",
      source: "bundled" as const,
      role: typeof item.role === "string" ? item.role : "researcher",
      stage: typeof item.stage === "string" ? item.stage : "内置 Subagent",
      sourceRef: typeof item.sourceRef === "string" ? item.sourceRef : "bundled",
      status: "core" as const,
    }));
  const custom = await loadCustomPersonas(root);
  const customRows: AgentManagerRow[] = custom.map((persona) => ({
    id: persona.id,
    name: persona.label,
    description: `项目自定义 Subagent · ${persona.role}`,
    source: "custom" as const,
    role: persona.role,
    stage: "自定义 Subagent",
    sourceRef: persona.path,
    status: "enabled" as const,
  }));
  const seen = new Set(bundledRows.map((row) => row.id));
  return [...bundledRows, ...customRows.filter((row) => !seen.has(row.id))];
}

/** Resolve selectable personas for `/agents` (bundled + custom). */
export async function loadSelectablePersonas(root: string): Promise<CustomPersona[]> {
  const custom = await loadCustomPersonas(root);
  const byId = new Map(custom.map((persona) => [persona.id, persona]));
  for (const persona of BUNDLED_PERSONAS) {
    if (byId.has(persona.id)) continue;
    byId.set(persona.id, {
      id: persona.id,
      label: persona.label,
      role: persona.role,
      prompt: [
        `# ${persona.label}`,
        "",
        persona.instructions,
        "",
        "所有判断必须标明依据和不确定性；不得虚构引用、数据、统计结果或稿件中不存在的内容。",
      ].join("\n"),
      path: `bundled:${persona.pack}/${persona.id}`,
      allowedEffects: ["read"],
    });
  }
  return [...byId.values()].sort((a, b) => a.id.localeCompare(b.id));
}

export async function recommendedAgentsForPanel(root: string): Promise<{
  schemaVersion: "psyclaw/recommended-agents/v1";
  items: Array<Record<string, unknown>>;
  repositoryHint?: string;
}> {
  const rows = await agentManagerRows(root);
  const catalog = await readRecommendedAgentsCatalog();
  return {
    schemaVersion: "psyclaw/recommended-agents/v1",
    ...(catalog.repositoryHint === undefined ? {} : { repositoryHint: catalog.repositoryHint }),
    items: rows.map((row) => ({
      id: row.id,
      name: row.name,
      kind: "agent",
      role: row.role,
      stage: row.stage,
      description: row.description,
      sourceRef: row.sourceRef,
      bundled: row.source === "bundled",
      installed: true,
      enabled: true,
      locked: row.source === "bundled",
      slashCommand: `/agents <bounded read-only research task>`,
    })),
  };
}
