import { createHash } from "node:crypto";
import type { MetadataCandidate, MetadataCrossCheck } from "./contracts.js";

export function normalizeDoi(value: string | undefined): string | undefined {
  if (!value) return undefined;
  const doi = value.trim().replace(/^doi:\s*/i, "").replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, "").replace(/[)\].,;]+$/, "").toLowerCase();
  return /^10\.\d{4,9}\/\S+$/.test(doi) ? doi : undefined;
}

export function normalizeTitle(value: string | undefined): string {
  return (value ?? "").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();
}

export function crossCheckMetadata(expected: MetadataCandidate, observed: MetadataCandidate): MetadataCrossCheck {
  const expectedDoi = normalizeDoi(expected.doi);
  const observedDoi = normalizeDoi(observed.doi);
  const doiMatch = expectedDoi !== undefined && observedDoi !== undefined && expectedDoi === observedDoi;
  const expectedTitle = normalizeTitle(expected.title);
  const observedTitle = normalizeTitle(observed.title);
  const titleMatch = expectedTitle.length > 0 && observedTitle.length > 0 && (expectedTitle === observedTitle || expectedTitle.includes(observedTitle) || observedTitle.includes(expectedTitle));
  const reasons: string[] = [];
  if (!doiMatch) reasons.push("DOI missing or does not match");
  if (!titleMatch) reasons.push("title missing or does not match");
  return { schemaVersion: "psyclaw/metadata-cross-check/v1", match: doiMatch && titleMatch, confidence: doiMatch && titleMatch ? "high" : doiMatch || titleMatch ? "medium" : "low", ...(observedDoi ? { normalizedDoi: observedDoi } : {}), titleMatch, doiMatch, reasons };
}

export function sha256Bytes(bytes: Uint8Array): string { return createHash("sha256").update(bytes).digest("hex"); }

export function detectFulltext(bytes: Uint8Array): "pdf" | "html" | "unknown" {
  if (bytes.slice(0, 5).every((v, i) => v === [0x25, 0x50, 0x44, 0x46, 0x2d][i])) return "pdf";
  const head = new TextDecoder().decode(bytes.slice(0, 512)).trimStart().toLowerCase();
  return /<(!doctype\s+html|html|head|body)\b/.test(head) ? "html" : "unknown";
}
