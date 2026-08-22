/**
 * Injectable registry clients. Network access is opt-in and every failure
 * resolves to `undefined` (never throws), so callers stay offline-safe and the
 * report simply marks the item unavailable/not-published.
 */

/** The latest official Pi release as reported by pi.dev. */
export interface PiRelease {
  version: string;
  packageName?: string;
  note?: string;
}

export interface RegistryClient {
  latestNpm(packageName: string): Promise<string | undefined>;
  latestPypi(packageName: string): Promise<string | undefined>;
  latestPiRelease(): Promise<PiRelease | undefined>;
}

const REQUEST_TIMEOUT_MS = 8000;
const PI_LATEST_VERSION_URL = "https://pi.dev/api/latest-version";

export function createHttpRegistry(fetchFn: typeof fetch = fetch): RegistryClient {
  return {
    async latestNpm(packageName: string): Promise<string | undefined> {
      try {
        const response = await fetchFn(
          `https://registry.npmjs.org/${encodeURIComponent(packageName)}/latest`,
          { signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) },
        );
        if (!response.ok) return undefined;
        const body = await response.json() as { version?: unknown };
        return typeof body.version === "string" && body.version.trim() ? body.version.trim() : undefined;
      } catch {
        return undefined;
      }
    },
    async latestPypi(packageName: string): Promise<string | undefined> {
      try {
        const response = await fetchFn(
          `https://pypi.org/pypi/${encodeURIComponent(packageName)}/json`,
          { signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) },
        );
        if (!response.ok) return undefined;
        const body = await response.json() as { info?: { version?: unknown } };
        const version = body.info?.version;
        return typeof version === "string" && version.trim() ? version.trim() : undefined;
      } catch {
        return undefined;
      }
    },
    async latestPiRelease(): Promise<PiRelease | undefined> {
      try {
        const response = await fetchFn(PI_LATEST_VERSION_URL, {
          headers: { accept: "application/json" },
          signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
        });
        if (!response.ok) return undefined;
        const body = await response.json() as { version?: unknown; packageName?: unknown; note?: unknown };
        const version = typeof body.version === "string" && body.version.trim() ? body.version.trim() : undefined;
        if (version === undefined) return undefined;
        const packageName = typeof body.packageName === "string" && body.packageName.trim()
          ? body.packageName.trim()
          : undefined;
        const note = typeof body.note === "string" && body.note.trim() ? body.note.trim() : undefined;
        return {
          version,
          ...(packageName === undefined ? {} : { packageName }),
          ...(note === undefined ? {} : { note }),
        };
      } catch {
        return undefined;
      }
    },
  };
}

/** Extract the package name from an `npm install -g <pkg>[@version]` command. */
export function npmPackageName(command: string): string | undefined {
  const match = command.match(/npm\s+install\s+(?:-g|--global)\s+([^\s]+)/);
  const raw = match?.[1];
  if (raw === undefined) return undefined;
  // Strip a trailing `@version` for both scoped and unscoped packages.
  const at = raw.lastIndexOf("@");
  return at > 0 ? raw.slice(0, at) : raw;
}

/** Extract the package name from a `pipx install <pkg>[==version]` command. */
export function pipxPackageName(command: string): string | undefined {
  const match = command.match(/pipx\s+install\s+([^\s]+)/);
  const raw = match?.[1];
  if (raw === undefined) return undefined;
  // Strip a pip version specifier (`==0.16.0`).
  return raw.split("==")[0] ?? undefined;
}
