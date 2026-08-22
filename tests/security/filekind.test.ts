import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { assertEvidenceImportable, sniffFileKind, sniffKindFromBuffer } from "../../src/core/filekind.js";

const bytes = (text: string): Uint8Array => new TextEncoder().encode(text);

describe("file content sniffing", () => {
  it("classifies by leading bytes, not filename", () => {
    expect(sniffKindFromBuffer(bytes("%PDF-1.7\n1 0 obj"))).toBe("pdf");
    expect(sniffKindFromBuffer(bytes("<!doctype html><html><body>login</body></html>"))).toBe("html");
    expect(sniffKindFromBuffer(bytes('{"a": 1}'))).toBe("json");
    expect(sniffKindFromBuffer(bytes("# markdown"))).toBe("text");
    expect(sniffKindFromBuffer(new Uint8Array(0))).toBe("empty");
    expect(sniffKindFromBuffer(new Uint8Array([0, 1, 2, 3]))).toBe("binary");
  });

  it("rejects an HTML login page masquerading as a PDF full-text", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-filekind-"));
    const fake = join(root, "paper.pdf");
    await writeFile(fake, "<!DOCTYPE html><html><body>Please sign in to continue</body></html>", "utf8");
    expect(await sniffFileKind(fake)).toBe("html");
    await expect(assertEvidenceImportable(fake, "fulltext")).rejects.toThrow(/HTML|login|captcha/i);
  });

  it("accepts a real document and ignores user-level imports", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-filekind-"));
    const pdf = join(root, "paper.pdf");
    await writeFile(pdf, "%PDF-1.4\n%%EOF", "utf8");
    await expect(assertEvidenceImportable(pdf, "fulltext")).resolves.toBeUndefined();

    const html = join(root, "note.html");
    await writeFile(html, "<html>researcher note</html>", "utf8");
    // user-level imports are provenance, not trusted full-text; no sniff gate.
    await expect(assertEvidenceImportable(html, "user")).resolves.toBeUndefined();
  });

  it("recognizes a Word .docx as a document, not binary", () => {
    const zipHeader = [0x50, 0x4b, 0x03, 0x04];
    const docxBytes = new Uint8Array(16_384);
    docxBytes.set(zipHeader, 0);
    // "word/" appears in the ZIP entry names near the start of a docx.
    const marker = new TextEncoder().encode("word/document.xml");
    docxBytes.set(marker, 128);
    expect(sniffKindFromBuffer(docxBytes)).toBe("docx");

    // A plain ZIP without word/ content is still rejected as binary.
    const zipBytes = new Uint8Array([0x50, 0x4b, 0x03, 0x04, 0, 0, 0, 0, 0, 0]);
    expect(sniffKindFromBuffer(zipBytes)).toBe("binary");
  });
});
