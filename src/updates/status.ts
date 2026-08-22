export type UpdateStatus =
  | "up-to-date"
  | "outdated"
  | "unpinned"
  | "unavailable"
  | "not-published"
  | "unknown";

const UNPINNED_REFS = new Set(["", "unpinned", "latest", "head", "main", "master", "*", "unknown"]);

/** A ref that cannot be compared to a registry version. */
export function isUnpinnedRef(ref: string | undefined): boolean {
  return ref === undefined || UNPINNED_REFS.has(ref.trim().toLowerCase());
}

/** Compare two versions; returns null when either side is not parseable semver. */
export function compareSemver(left: string, right: string): number | null {
  const a = parseSemver(left);
  const b = parseSemver(right);
  if (a === null || b === null) return null;
  for (let index = 0; index < 3; index += 1) {
    const x = a[index] ?? 0;
    const y = b[index] ?? 0;
    if (x !== y) return x < y ? -1 : 1;
  }
  return 0;
}

function parseSemver(value: string): [number, number, number] | null {
  const match = value.trim().replace(/^v/i, "").match(/^(\d+)\.(\d+)\.(\d+)/);
  if (!match) return null;
  return [Number(match[1]), Number(match[2]), Number(match[3])];
}

/** Classify a pinned version against the latest available version. */
export function versionStatus(current: string | undefined, latest: string | undefined): UpdateStatus {
  if (latest === undefined) return "unavailable";
  if (current === undefined) return "unknown";
  const comparison = compareSemver(current, latest);
  if (comparison === null) return "unknown";
  return comparison < 0 ? "outdated" : "up-to-date";
}
