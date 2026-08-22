import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { sha256File } from "../core/hash.js";
import { projectPaths } from "../project/paths.js";

export type SkillDriftStatus = "up-to-date" | "changed" | "missing" | "no-import";

export interface SkillDrift {
  agentId: string;
  status: SkillDriftStatus;
  /** Source files whose content changed since import. */
  changed: string[];
  /** Source files that no longer exist. */
  missing: string[];
}

interface ManifestShape {
  skills?: { files?: { sourcePath?: unknown; sha256?: unknown }[] }[];
}

/**
 * Detect whether imported skill files drifted from their sources. Only the
 * source path is re-hashed; the imported copy itself is never modified and the
 * result is read-only.
 */
export async function checkSkillDrift(root: string, agentId: string): Promise<SkillDrift> {
  const manifestPath = join(projectPaths(root).root, ".psyclaw", "imports", agentId, "import-manifest.json");
  let manifest: ManifestShape;
  try {
    manifest = JSON.parse(await readFile(manifestPath, "utf8")) as ManifestShape;
  } catch {
    return { agentId, status: "no-import", changed: [], missing: [] };
  }

  const changed: string[] = [];
  const missing: string[] = [];
  for (const skill of manifest.skills ?? []) {
    for (const file of skill.files ?? []) {
      const source = file.sourcePath;
      const expected = file.sha256;
      if (typeof source !== "string" || typeof expected !== "string") continue;
      const actual = await sha256File(source).catch(() => undefined);
      if (actual === undefined) {
        missing.push(source);
      } else if (actual.toLowerCase() !== expected.toLowerCase()) {
        changed.push(source);
      }
    }
  }
  const status: SkillDriftStatus = missing.length > 0 ? "missing" : changed.length > 0 ? "changed" : "up-to-date";
  return { agentId, status, changed, missing };
}
