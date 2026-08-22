import type { JournalProfile } from "./contracts.js";

const ID = /^[a-z0-9][a-z0-9._-]{0,63}$/;
const SHA = /^[a-f0-9]{64}$/i;

function validate(profile: JournalProfile): JournalProfile {
  if (!ID.test(profile.id)) throw new Error("journal profile id must be a stable identifier");
  for (const field of ["name", "source", "ref", "version", "license"] as const) {
    if (!profile[field]?.trim()) throw new Error(`journal profile ${field} is required`);
  }
  if (profile.status === "verified" && profile.source.trim() === "") throw new Error("verified profile requires a source");
  return Object.freeze({ ...profile, status: profile.status ?? "unverified", rules: profile.rules ?? {} });
}

/** Descriptor-first registry. Registration never implies that a journal rule is trusted. */
export class JournalProfileRegistry {
  private readonly profiles = new Map<string, JournalProfile>();
  private defaultId: string;

  constructor(profiles: readonly JournalProfile[] = [], defaultId?: string) {
    for (const profile of profiles) this.register(profile);
    this.defaultId = defaultId ?? profiles[0]?.id ?? "generic";
    if (!this.profiles.has(this.defaultId)) {
      this.register({ id: "generic", name: "Generic manuscript", source: "psyclaw", ref: "builtin", version: "v1", license: "MIT", status: "verified" });
      this.defaultId = "generic";
    }
  }

  register(profile: JournalProfile): JournalProfile {
    const normalized = validate(profile);
    if (this.profiles.has(normalized.id)) throw new Error(`journal profile already registered: ${normalized.id}`);
    this.profiles.set(normalized.id, normalized);
    return normalized;
  }

  get(id: string): JournalProfile | undefined { return this.profiles.get(id); }
  list(): readonly JournalProfile[] { return [...this.profiles.values()]; }
  default(): JournalProfile { return this.profiles.get(this.defaultId)!; }
  setDefault(id: string): void {
    if (!this.profiles.has(id)) throw new Error(`journal profile not found: ${id}`);
    this.defaultId = id;
  }
}

export const DEFAULT_JOURNAL_PROFILE: JournalProfile = Object.freeze({
  id: "generic", name: "Generic manuscript", source: "psyclaw", ref: "builtin", version: "v1", license: "MIT", status: "verified", rules: {},
});

export function createDefaultJournalProfileRegistry(): JournalProfileRegistry {
  return new JournalProfileRegistry([DEFAULT_JOURNAL_PROFILE], "generic");
}

export { SHA };
