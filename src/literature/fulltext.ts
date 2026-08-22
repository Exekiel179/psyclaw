import { lstat } from "node:fs/promises";
import { readFile } from "node:fs/promises";
import { sha256File } from "../core/hash.js";
import { sniffKindFromBuffer } from "../core/filekind.js";
import type { InstitutionalAccessRequest, VerifiedFulltext } from "./contracts.js";

export function createInstitutionalAccessRequest(identifier: string, now = new Date().toISOString()): InstitutionalAccessRequest {
  const value = identifier.trim();
  if (!value) throw new Error("identifier is required");
  const identifierKind = /^10\.\d{4,9}\//i.test(value) ? "doi" : /^https?:\/\//i.test(value) ? "url" : "title";
  return { schemaVersion: "psyclaw/institutional-access/v1", requestId: `fulltext-${Date.now()}`, identifier: value, identifierKind, authorization: "user-authenticated", browserSession: "existing-visible-session", approval: "pending", createdAt: now };
}

export async function verifyInstitutionalFulltext(path: string, sourceLocator: string, options: { access?: VerifiedFulltext["access"]; expectedSha256?: string; now?: string } = {}): Promise<VerifiedFulltext> {
  const stat = await lstat(path);
  if (!stat.isFile() || stat.isSymbolicLink()) throw new Error("full-text must be a regular file");
  const bytes = await readFile(path);
  if (sniffKindFromBuffer(bytes.subarray(0, 512)) !== "pdf") throw new Error("full-text is not a recognizable PDF (possible HTML login page)");
  const sha256 = await sha256File(path);
  if (options.expectedSha256 && options.expectedSha256.toLowerCase() !== sha256) throw new Error("full-text SHA-256 mismatch");
  return { schemaVersion: "psyclaw/verified-fulltext/v1", path, sha256, bytes: stat.size, contentType: "application/pdf", sourceLocator, access: options.access ?? "institutional-authorized", verifiedAt: options.now ?? new Date().toISOString(), titleMatch: "not-checked", doiMatch: "not-checked" };
}
