import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

/** The two official Pi packages psyclaw pins and bumps in lockstep. */
export const PI_AI = "@earendil-works/pi-ai";
export const PI_CODING_AGENT = "@earendil-works/pi-coding-agent";

interface RawPackageJson {
  name?: unknown;
  version?: unknown;
  packageManager?: unknown;
  dependencies?: Record<string, unknown>;
}

export interface PsyClawManifest {
  root: string;
  version: string;
  piVersion?: string;
  piAiVersion?: string;
  packageManager?: string;
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

/**
 * Walk up from `startDir` until a `package.json` named `psyclaw` is found. The
 * single source of truth for "where is the psyclaw package and what does it
 * say" — used by both the async manifest resolver and the sync version reader.
 */
function findPsyClawPackage(startDir: string): { dir: string; parsed: RawPackageJson } | undefined {
  let dir = startDir;
  for (let depth = 0; depth < 6; depth += 1) {
    try {
      const parsed = JSON.parse(readFileSync(join(dir, "package.json"), "utf8")) as RawPackageJson;
      if (parsed.name === "psyclaw") return { dir, parsed };
    } catch {
      // keep walking up
    }
    dir = join(dir, "..");
  }
  return undefined;
}

/** Synchronous psyclaw version read (banner, branding) — same walk as the resolver. */
export function readPsyClawVersionSync(startDir?: string): string | undefined {
  const found = findPsyClawPackage(startDir ?? dirname(fileURLToPath(import.meta.url)));
  return found === undefined ? undefined : asString(found.parsed.version);
}

/**
 * Walk up from `startDir` (defaults to this module's location) until a
 * `package.json` named `psyclaw` is found, then return its own version and the
 * pinned Pi dependency versions. Returns `undefined` when no psyclaw package is
 * reachable — the caller fails closed instead of guessing.
 */
export async function resolvePsyClawManifest(startDir?: string): Promise<PsyClawManifest | undefined> {
  const found = findPsyClawPackage(startDir ?? dirname(fileURLToPath(import.meta.url)));
  if (found === undefined) return undefined;
  const { dir, parsed } = found;
  const dependencies = parsed.dependencies ?? {};
  const piVersion = asString(dependencies[PI_CODING_AGENT]);
  const piAiVersion = asString(dependencies[PI_AI]);
  const packageManager = asString(parsed.packageManager);
  return {
    root: dir,
    version: asString(parsed.version) ?? "unknown",
    ...(piVersion === undefined ? {} : { piVersion }),
    ...(piAiVersion === undefined ? {} : { piAiVersion }),
    ...(packageManager === undefined ? {} : { packageManager }),
  };
}
