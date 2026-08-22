export type StyleArtifactKind = "manuscript" | "figure" | "table";

export interface JournalStyleProfile {
  schemaVersion: "psyclaw/journal-style/v1";
  journal: string;
  source: string;
  ref: string;
  version: string;
  license?: string;
  rules: Record<string, string | number | boolean>;
}

export interface StyleArtifactContract {
  schemaVersion: "psyclaw/style-artifact/v1";
  kind: StyleArtifactKind;
  id: string;
  version: string;
  format: string;
  profile: string;
  sourceHash?: string;
  scriptPath?: string;
  inputHash?: string;
}

export const defaultJournalStyle: JournalStyleProfile = {
  schemaVersion: "psyclaw/journal-style/v1",
  journal: "default-scientific",
  source: "psyclaw-built-in",
  ref: "default-v1",
  version: "1.0.0",
  rules: { citations: "author-year-or-numbered", figureFormat: "png-or-pdf", tableFormat: "tsv-or-csv", discloseUncertainty: true },
};

export function validateStyleArtifact(value: StyleArtifactContract): StyleArtifactContract {
  if (value.schemaVersion !== "psyclaw/style-artifact/v1" || !value.id || !value.version || !value.format || !value.profile) throw new Error("invalid psyclaw/style-artifact/v1");
  if ((value.kind === "figure" || value.kind === "table") && (!value.scriptPath || !value.inputHash)) throw new Error("data-derived figures and tables require scriptPath and inputHash");
  return value;
}

export function resolveJournalStyle(profile?: JournalStyleProfile): JournalStyleProfile {
  if (!profile) return defaultJournalStyle;
  if (profile.schemaVersion !== "psyclaw/journal-style/v1" || !profile.source || !profile.ref || !profile.version || !profile.license) throw new Error("journal profile requires source, ref, version, and license");
  return profile;
}
