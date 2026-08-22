import type { RunEvent } from "../orchestration/contracts.js";
import { redactSecrets } from "../core/redact.js";
import { lstat } from "node:fs/promises";
import { appendJsonl, readJsonl } from "../project/jsonl.js";
import { assertSafeProjectPath, projectPaths } from "../project/paths.js";

/**
 * Append-only projection of a run's facts. The panel may replay this log, but
 * it never becomes an alternative state store.
 */
export class RunEventLog {
  private readonly path: string;

  public constructor(private readonly root: string, private readonly runId: string) {
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(runId)) {
      throw new Error("Run id contains unsupported path characters");
    }
    this.path = `${projectPaths(root).runs}/${runId}.jsonl`;
  }

  public async append(event: Omit<RunEvent, "schemaVersion" | "runId">): Promise<RunEvent> {
    const full: RunEvent = {
      schemaVersion: "psyclaw/run-event/v1",
      runId: this.runId,
      ...event,
      // Free-form text in the log is scrubbed so a model or untrusted tool
      // cannot exfiltrate a credential through a projection surface.
      ...(event.message !== undefined ? { message: redactSecrets(event.message) } : {}),
    };
    if (!full.at.trim()) throw new Error("Run event timestamp cannot be empty");
    const path = await assertSafeRunEventPath(this.root, this.runId);
    await assertRegularRunFile(path, true);
    await appendJsonl(path, full);
    return full;
  }

  public async snapshot(): Promise<RunEvent[]> {
    const path = await assertSafeRunEventPath(this.root, this.runId);
    await assertRegularRunFile(path, true);
    const rows = await readJsonl<unknown>(path);
    return rows.map((row, index) => {
      if (!isRunEvent(row) || row.runId !== this.runId) {
        throw new Error(`Invalid run event at ${path}:${index + 1}`);
      }
      return row;
    });
  }
}

/**
 * Resolve a run log through the project path policy before any read or write.
 * This rejects a symlinked `.psyclaw`/`runs` ancestor as well as a symlinked
 * event file. The check is an application boundary; hostile concurrent
 * processes still require an OS-level sandbox or no-follow file handles.
 */
export async function assertSafeRunEventPath(root: string, runId: string): Promise<string> {
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(runId)) {
    throw new Error("Run id contains unsupported path characters");
  }
  const path = await assertSafeProjectPath(root, `.psyclaw/runs/${runId}.jsonl`);
  return path;
}

async function assertRegularRunFile(path: string, allowMissing: boolean): Promise<void> {
  try {
    const stat = await lstat(path);
    if (stat.isSymbolicLink() || !stat.isFile()) throw new Error("Run event path must be a regular file");
  } catch (error) {
    if (allowMissing && (error as NodeJS.ErrnoException).code === "ENOENT") return;
    throw error;
  }
}

function isRunEvent(value: unknown): value is RunEvent {
  if (typeof value !== "object" || value === null) return false;
  const event = value as Partial<RunEvent>;
  const validTypes: RunEvent["type"][] = [
    "planned",
    "started",
    "receipt",
    "gate",
    "checkpoint",
    "completed",
    "blocked",
  ];
  return (
    event.schemaVersion === "psyclaw/run-event/v1" &&
    typeof event.runId === "string" &&
    typeof event.at === "string" &&
    typeof event.type === "string" &&
    validTypes.includes(event.type as RunEvent["type"])
  );
}
