import { open } from "node:fs/promises";

export type FileKind = "pdf" | "docx" | "html" | "json" | "text" | "binary" | "empty" | "unknown";

const SAMPLE_BYTES = 16_384;

function asciiPrefix(buffer: Uint8Array, prefix: string): boolean {
  for (let index = 0; index < prefix.length; index += 1) {
    if (buffer[index] !== prefix.charCodeAt(index)) return false;
  }
  return true;
}

function isZip(buffer: Uint8Array): boolean {
  // PK\x03\x04 local file header
  return buffer.length >= 4 && buffer[0] === 0x50 && buffer[1] === 0x4b && buffer[2] === 0x03 && buffer[3] === 0x04;
}

function latin1(buffer: Uint8Array): string {
  let output = "";
  for (const byte of buffer) output += String.fromCharCode(byte);
  return output;
}

/**
 * Classify content by its leading bytes, never by its filename extension.
 * This is the deterministic basis for the `fake-pdf-html` hard fail: an HTML
 * login or captcha page must not be accepted as trusted full-text just
 * because its name ends in `.pdf`.
 */
export function sniffKindFromBuffer(buffer: Uint8Array): FileKind {
  if (buffer.length === 0) return "empty";
  if (buffer.length >= 5 && asciiPrefix(buffer, "%PDF-")) return "pdf";
  if (isZip(buffer)) {
    // A Word .docx is a ZIP whose entries live under word/ (word/document.xml).
    // Other ZIPs (xlsx/pptx/plain archives) are not treated as Word evidence.
    return latin1(buffer).toLowerCase().includes("word/") ? "docx" : "binary";
  }
  const sample = latin1(buffer.subarray(0, Math.min(buffer.length, SAMPLE_BYTES)))
    .trimStart()
    .toLowerCase();
  if (sample.startsWith("<") || sample.startsWith("<!doctype") || sample.includes("<html")) {
    return "html";
  }
  if (sample.startsWith("{") || sample.startsWith("[")) return "json";
  for (const byte of buffer.subarray(0, Math.min(buffer.length, SAMPLE_BYTES))) {
    if (byte === 0) return "binary";
  }
  return "text";
}

export async function sniffFileKind(path: string): Promise<FileKind> {
  const handle = await open(path, "r");
  try {
    const buffer = new Uint8Array(SAMPLE_BYTES);
    const { bytesRead } = await handle.read(buffer, 0, buffer.length, 0);
    return sniffKindFromBuffer(buffer.subarray(0, bytesRead));
  } finally {
    await handle.close();
  }
}

/**
 * Gate a local evidence import. `fulltext` imports must be a recognizable
 * document; an HTML page or an empty/binary blob is rejected rather than
 * silently recorded as trusted full-text.
 */
export async function assertEvidenceImportable(path: string, level: string): Promise<void> {
  if (level !== "fulltext") return;
  const kind = await sniffFileKind(path);
  if (kind === "html") {
    throw new Error("Refusing to import HTML as full-text evidence (possible login/captcha page)");
  }
  if (kind === "binary" || kind === "unknown") {
    throw new Error("Refusing to import unrecognized binary content as full-text evidence");
  }
  if (kind === "empty") {
    throw new Error("Refusing to import an empty file as full-text evidence");
  }
  // `docx` is accepted: it is a real document, converted to text/Markdown via
  // `docxToText` / `docxToMarkdown` before any claim-evidence reading.
}
