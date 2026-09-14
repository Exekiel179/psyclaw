import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const BIOSIGNAL_PACK_SCHEMA = "psyclaw/biosignal-pack/v1" as const;

export interface BiosignalDomain {
  id: string;
  name: string;
  description: string;
  mcp: string[];
  skills: string[];
}

export interface BiosignalPackCatalog {
  schemaVersion: typeof BIOSIGNAL_PACK_SCHEMA;
  documentVersion: string;
  description?: string;
  domains: BiosignalDomain[];
}

export interface BiosignalInstallPlan {
  domainIds: string[];
  domainNames: string[];
  mcpIds: string[];
  skillIds: string[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string" && item.trim().length > 0);
}

export function parseBiosignalPackCatalog(raw: unknown): BiosignalPackCatalog {
  if (!isRecord(raw)) throw new Error("biosignal pack catalog must be an object");
  if (raw.schemaVersion !== BIOSIGNAL_PACK_SCHEMA) {
    throw new Error(`unsupported biosignal pack schema: ${String(raw.schemaVersion)}`);
  }
  if (typeof raw.documentVersion !== "string" || !raw.documentVersion.trim()) {
    throw new Error("biosignal pack documentVersion is required");
  }
  if (!Array.isArray(raw.domains) || raw.domains.length === 0) {
    throw new Error("biosignal pack domains must be a non-empty array");
  }
  const domains: BiosignalDomain[] = raw.domains.map((entry, index) => {
    if (!isRecord(entry)) throw new Error(`biosignal domain #${index + 1} must be an object`);
    const id = typeof entry.id === "string" ? entry.id.trim() : "";
    const name = typeof entry.name === "string" ? entry.name.trim() : "";
    const description = typeof entry.description === "string" ? entry.description.trim() : "";
    if (!id || !name) throw new Error(`biosignal domain #${index + 1} needs id and name`);
    return {
      id,
      name,
      description,
      mcp: asStringArray(entry.mcp),
      skills: asStringArray(entry.skills),
    };
  });
  return {
    schemaVersion: BIOSIGNAL_PACK_SCHEMA,
    documentVersion: raw.documentVersion.trim(),
    ...(typeof raw.description === "string" ? { description: raw.description } : {}),
    domains,
  };
}

function isMissingFile(error: unknown): boolean {
  return isRecord(error) && error.code === "ENOENT";
}

export async function readBiosignalPackCatalog(): Promise<BiosignalPackCatalog> {
  const moduleDir = dirname(fileURLToPath(import.meta.url));
  const candidates = [
    join(moduleDir, "..", "..", "skills", "recommended", "biosignal-pack.json"),
    join(moduleDir, "..", "..", "..", "skills", "recommended", "biosignal-pack.json"),
    join(process.cwd(), "skills", "recommended", "biosignal-pack.json"),
  ];
  let lastError: unknown;
  for (const path of candidates) {
    try {
      return parseBiosignalPackCatalog(JSON.parse(await readFile(path, "utf8")));
    } catch (error) {
      if (isMissingFile(error)) continue;
      lastError = error;
      // Prefer surfacing schema/parse errors from the first existing file.
      throw error;
    }
  }
  throw lastError instanceof Error ? lastError : new Error("biosignal-pack.json not found");
}

export function resolveBiosignalInstallPlan(
  catalog: BiosignalPackCatalog,
  selectedDomainIds: readonly string[],
): BiosignalInstallPlan {
  const selected = new Set(selectedDomainIds.map((id) => id.trim()).filter(Boolean));
  if (selected.size === 0) {
    throw new Error("请至少选择一个研究域");
  }
  const domains = catalog.domains.filter((domain) => selected.has(domain.id));
  if (domains.length !== selected.size) {
    const known = new Set(catalog.domains.map((domain) => domain.id));
    const unknown = [...selected].filter((id) => !known.has(id));
    throw new Error(`未知研究域：${unknown.join(", ")}`);
  }
  const mcpIds = [...new Set(domains.flatMap((domain) => domain.mcp))];
  const skillIds = [...new Set(domains.flatMap((domain) => domain.skills))];
  return {
    domainIds: domains.map((domain) => domain.id),
    domainNames: domains.map((domain) => domain.name),
    mcpIds,
    skillIds,
  };
}
