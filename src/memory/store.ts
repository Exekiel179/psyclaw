import { appendJsonl, readJsonl } from "../project/jsonl.js";
import { projectPaths } from "../project/paths.js";
import type { MemoryRecord } from "../core/contracts.js";

export interface MemorySearchOptions {
  scope?: MemoryRecord["scope"];
  topK?: number;
}

export interface MemoryStore {
  draft(record: MemoryRecord): Promise<void>;
  approve(id: string): Promise<void>;
  archive(id: string, reason: string): Promise<void>;
  search(query: string, options?: MemorySearchOptions): Promise<MemoryRecord[]>;
  audit(): AsyncIterable<MemoryRecord>;
}

function memoryPath(root: string, scope: MemoryRecord["scope"]): string {
  return `${projectPaths(root).memory}/${scope}.jsonl`;
}

function latestById(records: readonly MemoryRecord[]): Map<string, MemoryRecord> {
  const latest = new Map<string, MemoryRecord>();
  for (const record of records) latest.set(record.id, record);
  return latest;
}

export class JsonlMemoryStore implements MemoryStore {
  public constructor(private readonly root: string) {}

  async draft(record: MemoryRecord): Promise<void> {
    if (record.status !== "pending") throw new Error("New memory records must start as pending");
    if (!record.content || record.sourceRefs.length === 0) {
      throw new Error("Memory drafts require content and at least one source reference");
    }
    if (record.confidence < 0 || record.confidence > 1) throw new Error("Memory confidence must be between 0 and 1");
    await appendJsonl(memoryPath(this.root, record.scope), record);
  }

  async approve(id: string): Promise<void> {
    const current = await this.findLatest(id);
    if (!current) throw new Error(`Memory not found: ${id}`);
    if (current.status !== "pending") throw new Error(`Only pending memories can be approved: ${id}`);
    await appendJsonl(memoryPath(this.root, current.scope), {
      ...current,
      status: "active" as const,
      updatedAt: new Date().toISOString(),
    });
  }

  async archive(id: string, reason: string): Promise<void> {
    const current = await this.findLatest(id);
    if (!current) throw new Error(`Memory not found: ${id}`);
    if (!reason.trim()) throw new Error("Archive reason is required");
    await appendJsonl(memoryPath(this.root, current.scope), {
      ...current,
      status: "archived" as const,
      content: { previous: current.content, archiveReason: reason },
      updatedAt: new Date().toISOString(),
    });
  }

  async search(query: string, options: MemorySearchOptions = {}): Promise<MemoryRecord[]> {
    const scopes = options.scope ? [options.scope] : (["session", "project", "user"] as const);
    const records = (await Promise.all(scopes.map((scope) => readJsonl<MemoryRecord>(memoryPath(this.root, scope))))).flat();
    const needle = query.trim().toLowerCase();
    return [...latestById(records).values()]
      .filter((record) => record.status === "active")
      .filter((record) => !needle || JSON.stringify(record.content).toLowerCase().includes(needle))
      .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
      .slice(0, options.topK ?? 20);
  }

  async *audit(): AsyncIterable<MemoryRecord> {
    for (const scope of ["session", "project", "user"] as const) {
      for (const record of await readJsonl<MemoryRecord>(memoryPath(this.root, scope))) yield record;
    }
  }

  private async findLatest(id: string): Promise<MemoryRecord | undefined> {
    const records = (await Promise.all(
      (["session", "project", "user"] as const).map((scope) => readJsonl<MemoryRecord>(memoryPath(this.root, scope))),
    )).flat();
    return latestById(records).get(id);
  }
}
