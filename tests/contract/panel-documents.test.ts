import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { bootstrapProject } from "../../src/project/bootstrap.js";
import { downloadReferencePdf, enrichAssistantMessage } from "../../src/panel/server.js";
import { appendClaim, appendEvidence } from "../../src/research/ledger.js";
import { postJson, withServer } from "../helpers.js";
import { referencePdfPath } from "../../src/literature/archive.js";

async function preparePublishEvidence(root: string): Promise<void> {
  const doi = "10.1000/panel-publish-fixture";
  await writeFile(join(root, ".psyclaw", "citations.jsonl"), `${JSON.stringify({ doi })}\n`, "utf8");
  await writeFile(join(root, ".psyclaw", "references.jsonl"), `${JSON.stringify({ doi, verified: true })}\n`, "utf8");
  const pdf = referencePdfPath(doi);
  await mkdir(join(root, "literature", "pdfs"), { recursive: true });
  await writeFile(join(root, ...pdf.split("/")), "%PDF-1.4\nfixture\n%%EOF", "utf8");
}

// The panel is a read-only projection of project files; document discovery,
// manuscript serving and the reference archive are read endpoints, and all
// mutation routes are refused at the HTTP method gate (405).

describe("standardized document discovery", () => {
  it("discovers a paper/*.md manuscript even when notes/manuscript.md is absent", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-docs-paper-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await mkdir(join(root, "paper"), { recursive: true });
    await writeFile(join(root, "paper", "论文初稿.md"), "# 标题\n\n正文内容\n", "utf8");
    await withServer(root, async (base) => {
      const data = await (await fetch(`${base}/api/manuscript`)).json() as { exists: boolean; path: string | null; markdown: string };
      expect(data.exists).toBe(true);
      expect(data.path).toBe("paper/论文初稿.md");
      expect(data.markdown).toContain("正文内容");
    });
  });

  it("prefers notes/manuscript.md over paper/ when both exist", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-docs-pref-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await mkdir(join(root, "paper"), { recursive: true });
    await writeFile(join(root, "paper", "旧稿.md"), "旧稿内容", "utf8");
    await writeFile(join(root, "notes", "manuscript.md"), "面板托管手稿", "utf8");
    await withServer(root, async (base) => {
      const data = await (await fetch(`${base}/api/manuscript`)).json() as { exists: boolean; path: string | null; markdown: string };
      expect(data.path).toBe("notes/manuscript.md");
      expect(data.markdown).toContain("面板托管手稿");
    });
  });

  it("lists documents across the standard locations with import state", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-docs-list-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await mkdir(join(root, "paper"), { recursive: true });
    await mkdir(join(root, "data", "raw"), { recursive: true });
    await writeFile(join(root, "paper", "论文初稿.md"), "# 手稿", "utf8");
    await writeFile(join(root, "data", "raw", "问卷导出.xlsx"), Buffer.from([0x50, 0x4b, 0x03, 0x04, 0x00]));
    await withServer(root, async (base) => {
      const data = await (await fetch(`${base}/api/documents`)).json() as {
        documents: Array<{ path: string; kind: string; imported: boolean; isManuscript: boolean; sha256: string }>;
      };
      const manuscript = data.documents.find((doc) => doc.path === "paper/论文初稿.md");
      expect(manuscript).toBeDefined();
      expect(manuscript!.kind).toBe("manuscript");
      expect(manuscript!.isManuscript).toBe(true);
      expect(manuscript!.imported).toBe(false);
      expect(manuscript!.sha256).toMatch(/^[a-f0-9]{64}$/);
      const xlsx = data.documents.find((doc) => doc.path === "data/raw/问卷导出.xlsx");
      expect(xlsx).toBeDefined();
      expect(xlsx!.kind).toBe("data");
    });
  });
});

describe("generation-time publish (/api/publish)", () => {
  it("refuses panel publish writes (405); publishing is owned by the workflow layer", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-docs-publish-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await withServer(root, async (base) => {
      const res = await postJson(base, "/api/publish", { content: "# 发布稿\n\n发布内容", name: "论文初稿", exportDocx: false });
      expect(res.status).toBe(405);
      expect(res.headers.get("allow")).toContain("GET");
      // The rejected call must not have written anything.
      const ms = await (await fetch(`${base}/api/manuscript`)).json() as { exists: boolean; markdown: string };
      expect(ms.exists).toBe(false);
      expect(ms.markdown).toBe("");
    });
  });
});

describe("versions and reference archive endpoints", () => {
  it("serves published versions read-only after a real publish workflow", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-docs-versions-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await preparePublishEvidence(root);
    const { publishManuscript } = await import("../../src/workflows/publish.js");
    await publishManuscript(root, { name: "论文初稿", markdown: "# v1 内容", exportDocx: false });
    await publishManuscript(root, { name: "论文初稿", markdown: "# v2 内容", exportDocx: false });
    await withServer(root, async (base) => {
      // Publishing over the panel HTTP surface is refused; versions are read
      // from the publish.jsonl written by the workflow layer.
      expect((await postJson(base, "/api/publish", { content: "# v3 内容", name: "论文初稿", exportDocx: false })).status).toBe(405);

      const versions = await (await fetch(`${base}/api/versions`)).json() as { versions: Array<{ version: number; markdownPath: string; markdownLoadPath: string }>; current: { version: number } | null };
      expect(versions.versions).toHaveLength(2);
      expect(versions.current!.version).toBe(2);

      // v1 loads from the archive; v2 (current) loads from the live file
      expect(versions.versions[0]!.markdownLoadPath).toContain("archive");
      expect(versions.versions[1]!.markdownLoadPath).toBe("paper/论文初稿.md");
      const v1Text = await (await fetch(`${base}/api/artifact?path=${encodeURIComponent(versions.versions[0]!.markdownLoadPath)}`)).text();
      expect(v1Text).toContain("v1 内容");
    });
  });

  it("checks in-text citations read-only; the audit endpoint refuses panel writes", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-docs-refs-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await withServer(root, async (base) => {
      const refs = await (await fetch(`${base}/api/references`)).json() as { references: unknown[] };
      expect(refs.references).toEqual([]);

      // Citation auditing runs in the citation workflow (unit-tested); the
      // panel surface refuses the check-as-write route.
      const res = await postJson(base, "/api/references/check", { text: "（Kessler et al., 2005; Wanberg et al., 2010）" });
      expect(res.status).toBe(405);
      expect(await res.text()).toContain("method not allowed");
    });
  });
});

describe("downloadReferencePdf (OpenAlex OA, injectable fetch)", () => {
  it("downloads an OA PDF into literature/ and registers evidence", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-docs-dl-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    const fetchFn = async (url: string): Promise<Response> => {
      if (url.includes("api.openalex.org")) {
        return new Response(JSON.stringify({ open_access: { is_oa: true, oa_url: "https://example.org/paper.pdf" }, best_oa_location: { pdf_url: "https://example.org/paper.pdf" } }), { status: 200 });
      }
      return new Response("%PDF-1.4 fake content", { status: 200 });
    };
    const result = await downloadReferencePdf(root, "10.1000/oa-test", fetchFn as typeof fetch);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.path).toMatch(/^literature\/.+\.pdf$/);
      expect(result.bytes).toBeGreaterThan(0);
      const evidence = await readFile(join(root, ".psyclaw", "evidence.jsonl"), "utf8");
      expect(evidence).toContain(result.evidenceId);
    }
  });

  it("returns not-open-access honestly when OpenAlex reports no OA", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-docs-dl-no-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    const fetchFn = async (): Promise<Response> => new Response(JSON.stringify({ open_access: { is_oa: false }, best_oa_location: null }), { status: 200 });
    const result = await downloadReferencePdf(root, "10.1000/paywalled", fetchFn as typeof fetch);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("not-open-access");
  });
});

describe("assistant message enrichment", () => {
  it("leaves messages without claim ids unchanged", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-enrich-none-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    const message = "请审查统计方案。";
    expect(await enrichAssistantMessage(root, message)).toBe(message);
  });

  it("attaches real ledger context for a referenced claim and flags missing data", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-enrich-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    const claimId = "claim_abcd1234abcd1234";
    await appendClaim(root, { id: claimId, text: "自我评价是个体对自身价值的总体判断", kind: "definition", evidenceIds: [], status: "uncertain" });

    const enriched = await enrichAssistantMessage(root, `请对论断 [${claimId}] 进行深度方法学交叉复核。`);
    expect(enriched).toContain(claimId);
    expect(enriched).toContain("自我评价是个体对自身价值的总体判断");
    expect(enriched).toContain("状态=uncertain");
    expect(enriched).toContain("无法核验样本量或效应量");
  });

  it("lists attached evidence when the claim has some", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-enrich-ev-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    const claimId = "claim_eeeeeeeeeeeeeeee";
    const evidenceId = "evidence_ffffffffffffffff";
    await appendEvidence(root, {
      id: evidenceId,
      source: { kind: "doi", locator: "10.1000/x", title: "Some Paper" },
      level: "fulltext",
      quote: "quoted",
      retrievedAt: "2026-01-01T00:00:00.000Z",
      accessStatus: "partial",
      locators: [{ kind: "doi", value: "10.1000/x" }],
    });
    await appendClaim(root, { id: claimId, text: "有证据的论断", kind: "result", evidenceIds: [evidenceId], status: "supported" });
    await (await import("../../src/research/ledger.js")).appendClaimEvidenceLink(root, { claimId, evidenceId, relation: "supports", rationale: "test" });

    const enriched = await enrichAssistantMessage(root, `核验 ${claimId}`);
    expect(enriched).toContain("关联证据 1 条");
    expect(enriched).toContain(evidenceId);
    expect(enriched).toContain("10.1000/x");
  });
});

describe("citation-usage endpoints (/api/citations)", () => {
  it("refuses citation recording over HTTP; citation use is recorded by the workflow", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-docs-cite-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await withServer(root, async (base) => {
      const res = await postJson(base, "/api/citations", {
        doi: "not-a-doi",
        reason: "支持：社会支持缓冲压力假说",
        context: "社会支持缓冲压力（某作者, 2005）",
      });
      expect(res.status).toBe(405);
      expect(await res.text()).toContain("method not allowed");

      // Nothing was appended by the rejected write.
      const list = await (await fetch(`${base}/api/citations`)).json() as { citations: unknown[] };
      expect(list.citations).toEqual([]);
    });
  });

  it("rejects every citation write attempt, with or without a reason", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-docs-cite-bad-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await withServer(root, async (base) => {
      const res = await postJson(base, "/api/citations", { doi: "10.1000/x", reason: "", context: "c" });
      // The method gate fires before payload validation, so even malformed
      // payloads cannot reach a writer.
      expect(res.status).toBe(405);
    });
  });
});

describe("document import", () => {
  it("refuses /api/documents/import over HTTP and keeps discovery read-only", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-docs-import-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await mkdir(join(root, "paper"), { recursive: true });
    await writeFile(join(root, "paper", "论文初稿.md"), "# 手稿\n\n可编辑内容\n", "utf8");
    await withServer(root, async (base) => {
      const res = await postJson(base, "/api/documents/import", { path: "paper/论文初稿.md" });
      expect(res.status).toBe(405);
      expect(await res.text()).toContain("method not allowed");

      // The rejected call registered nothing in the evidence/import ledger.
      const evidence = await readFile(join(root, ".psyclaw", "evidence.jsonl"), "utf8").catch(() => "");
      expect(evidence).not.toContain("论文初稿.md");
      const imports = await readFile(join(root, ".psyclaw", "imports.jsonl"), "utf8").catch(() => "");
      expect(imports).not.toContain("psyclaw/import/v1");

      // Document discovery stays read-only and reflects the real file.
      const listing = await (await fetch(`${base}/api/documents`)).json() as { documents: Array<{ path: string; imported: boolean; isManuscript: boolean }> };
      const manuscript = listing.documents.find((doc) => doc.path === "paper/论文初稿.md");
      expect(manuscript?.isManuscript).toBe(true);
      expect(manuscript!.imported).toBe(false);
    });
  });

  it("rejects every import path at the method gate before path validation", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-docs-bad-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await mkdir(join(root, "analysis", "scripts"), { recursive: true });
    await writeFile(join(root, "analysis", "scripts", "analyze.py"), "print(1)", "utf8");
    await withServer(root, async (base) => {
      // Neither a traversal attempt nor an unsupported format can reach an
      // importer: the read-only panel rejects the mutation first.
      const escape = await postJson(base, "/api/documents/import", { path: "../escape.md" });
      expect(escape.status).toBe(405);
      const unsupported = await postJson(base, "/api/documents/import", { path: "analysis/scripts/analyze.py" });
      expect(unsupported.status).toBe(405);
    });
  });

  it("keeps a foreign-format project file discoverable and refuses import writes", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-docs-docx-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await mkdir(join(root, "paper"), { recursive: true });
    await writeFile(join(root, "paper", "草案.docx"), Buffer.from([0x50, 0x4b, 0x03, 0x04, 0x00]), "utf8");
    await withServer(root, async (base) => {
      const res = await postJson(base, "/api/documents/import", { path: "paper/草案.docx" });
      expect(res.status).toBe(405);
      const docs = await (await fetch(`${base}/api/documents`)).json() as { documents: Array<{ path: string }> };
      expect(docs.documents.some((doc) => doc.path === "paper/草案.docx")).toBe(true);
    });
  });
});
