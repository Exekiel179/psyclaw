import { basename, extname } from "node:path";
import { sha256File } from "../core/hash.js";
import type { ArtifactIdentity, ArtifactKind, ReproducibilityCheck, StyleCheckFinding, StyleCheckResult } from "./contracts.js";
import { STYLE_CONTRACT_VERSION } from "./contracts.js";

const SHA = /^[a-f0-9]{64}$/i;
const SLUG = /^[a-z0-9][a-z0-9-]*$/;

export function artifactFilename(identity: ArtifactIdentity): string {
  if (!SLUG.test(identity.slug)) throw new Error("artifact slug must use lowercase letters, numbers, and hyphens");
  if (!/^v[1-9][0-9]*$/.test(identity.version)) throw new Error("artifact version must be like v1");
  const extension = identity.extension.replace(/^\./, "").toLowerCase();
  if (!/^[a-z0-9]+$/.test(extension)) throw new Error("artifact extension is invalid");
  return `${identity.kind}-${identity.slug}-${identity.version}.${extension}`;
}

export function parseArtifactFilename(path: string): ArtifactIdentity | undefined {
  const match = /^(figure|table|manuscript)-([a-z0-9][a-z0-9-]*)-(v[1-9][0-9]*)\.([a-z0-9]+)$/i.exec(basename(path));
  return match ? { kind: match[1]!.toLowerCase() as ArtifactKind, slug: match[2]!.toLowerCase(), version: match[3]!.toLowerCase(), extension: match[4]!.toLowerCase() } : undefined;
}

export async function verifyReproducibility(check: ReproducibilityCheck): Promise<StyleCheckResult> {
  const findings: StyleCheckFinding[] = [];
  if (!check.scriptPath?.trim() || !check.scriptSha256 || !SHA.test(check.scriptSha256)) findings.push({ rule: "script-hash-required", severity: "block", message: "script path and SHA-256 are required" });
  if (check.scriptPath && check.scriptSha256 && SHA.test(check.scriptSha256)) {
    try { if ((await sha256File(check.scriptPath)).toLowerCase() !== check.scriptSha256.toLowerCase()) findings.push({ rule: "script-hash-mismatch", severity: "block", message: "script hash does not match the file" }); }
    catch { findings.push({ rule: "script-unavailable", severity: "block", message: "reproducibility script is unavailable" }); }
  }
  for (const [path, hash] of Object.entries(check.inputHashes ?? {})) {
    if (!SHA.test(hash)) { findings.push({ rule: "input-hash-invalid", severity: "block", message: `invalid input hash: ${path}` }); continue; }
    try {
      if ((await sha256File(path)).toLowerCase() !== hash.toLowerCase()) findings.push({ rule: "input-hash-mismatch", severity: "block", message: `input hash does not match: ${path}` });
    } catch { findings.push({ rule: "input-unavailable", severity: "block", message: `input is unavailable: ${path}` }); }
  }
  return { schemaVersion: STYLE_CONTRACT_VERSION, ok: !findings.some((f) => f.severity === "block"), findings };
}

export function checkDefaultStyle(identity: ArtifactIdentity, profileId = "generic"): StyleCheckResult {
  const findings: StyleCheckFinding[] = [];
  try { artifactFilename(identity); } catch (error) { findings.push({ rule: "artifact-name-invalid", severity: "block", message: String(error instanceof Error ? error.message : error) }); }
  if (!profileId.trim()) findings.push({ rule: "profile-required", severity: "block", message: "style profile id is required" });
  return { schemaVersion: STYLE_CONTRACT_VERSION, ok: !findings.some((f) => f.severity === "block"), findings };
}

export function artifactExtension(path: string): string { return extname(path).replace(/^\./, "").toLowerCase(); }
