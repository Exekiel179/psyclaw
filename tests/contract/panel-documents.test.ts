import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { bootstrapProject } from "../../src/project/bootstrap.js";
import { downloadReferencePdf, enrichAssistantMessage } from "../../src/panel/server.js";
import { appendClaim, appendEvidence } from "../../src/research/ledger.js";
import { postJson, withServer } from "../helpers.js";

// Detect pandoc at module load so `it.runIf` below is decided before tests run.
const pandocOk = await new Promise<boolean>((resolve) => {
  const child = spawn("pandoc", ["--version"], { stdio: "ignore", shell: process.platform === "win32" });
  child.on("error", () => resolve(false));
  child.on("close", (code) => resolve(code === 0));
});

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
  it("writes the manuscript to paper/ and the panel recognizes it immediately", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-docs-publish-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await withServer(root, async (base) => {
      const res = await postJson(base, "/api/publish", { content: "# 发布稿\n\n发布内容", name: "论文初稿", exportDocx: false });
      expect(res.status).toBe(200);
      const data = await res.json() as { ok: boolean; markdownPath: string; docxPath: string | null };
      expect(data.ok).toBe(true);
      expect(data.markdownPath).toBe("paper/论文初稿.md");
      expect(data.docxPath).toBeNull();

      const onDisk = await readFile(join(root, "paper", "论文初稿.md"), "utf8");
      expect(onDisk).toContain("发布内容");

      // manuscript discovery now resolves to the published file
      const ms = await (await fetch(`${base}/api/manuscript`)).json() as { exists: boolean; path: string | null };
      expect(ms.exists).toBe(true);
      expect(ms.path).toBe("paper/论文初稿.md");

      // document registry marks it as the manuscript
      const docs = await (await fetch(`${base}/api/documents`)).json() as { documents: Array<{ path: string; isManuscript: boolean; imported: boolean }> };
      expect(docs.documents.find((doc) => doc.path === "paper/论文初稿.md")!.isManuscript).toBe(true);
    });
  });
});

describe("versions and reference archive endpoints", () => {
  it("lists manuscript versions and serves archived version files", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-docs-versions-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await withServer(root, async (base) => {
      await postJson(base, "/api/publish", { content: "# v1 内容", name: "论文初稿", exportDocx: false });
      await postJson(base, "/api/publish", { content: "# v2 内容", name: "论文初稿", exportDocx: false });

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

  it("checks in-text citations against an empty archive and flags them as gaps", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-docs-refs-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await withServer(root, async (base) => {
      const refs = await (await fetch(`${base}/api/references`)).json() as { references: unknown[] };
      expect(refs.references).toEqual([]);

      const res = await postJson(base, "/api/references/check", { text: "（Kessler et al., 2005; Wanberg et al., 2010）" });
      expect(res.status).toBe(200);
      const data = await res.json() as { citations: Array<{ surname: string; missing: boolean }>; matched: number; unmatched: number };
      expect(data.matched).toBe(0);
      expect(data.unmatched).toBe(2);
      expect(data.citations.map((c) => c.surname).sort()).toEqual(["Kessler", "Wanberg"]);
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
  it("records a citation use (even unverified) and lists it", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-docs-cite-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await withServer(root, async (base) => {
      // invalid-format DOI → verification errors without network; use still recorded honestly
      const res = await postJson(base, "/api/citations", {
        doi: "not-a-doi",
        reason: "支持：社会支持缓冲压力假说",
        context: "社会支持缓冲压力（某作者, 2005）",
      });
      expect(res.status).toBe(200);
      const data = await res.json() as { ok: boolean; record: { citationId: string; verified: boolean; reason: string }; appended: boolean };
      expect(data.ok).toBe(true);
      expect(data.record.citationId).toMatch(/^cite_[a-f0-9]{16}$/);
      expect(data.record.verified).toBe(false);
      expect(data.record.reason).toContain("缓冲压力假说");

      const list = await (await fetch(`${base}/api/citations`)).json() as { citations: Array<{ citationId: string; reason: string }> };
      expect(list.citations).toHaveLength(1);
      expect(list.citations[0]!.citationId).toBe(data.record.citationId);
    });
  });

  it("rejects a citation use without a reason", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-docs-cite-bad-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await withServer(root, async (base) => {
      const res = await postJson(base, "/api/citations", { doi: "10.1000/x", reason: "", context: "c" });
      expect(res.status).toBe(400);
    });
  });
});

describe("document import", () => {
  it("imports an .md manuscript: registers evidence, records import, idempotent by sha256", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-docs-import-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await mkdir(join(root, "paper"), { recursive: true });
    await writeFile(join(root, "paper", "论文初稿.md"), "# 手稿\n\n可编辑内容\n", "utf8");
    await withServer(root, async (base) => {
      const res = await postJson(base, "/api/documents/import", { path: "paper/论文初稿.md" });
      expect(res.status).toBe(200);
      const data = await res.json() as { ok: boolean; imported: boolean; markdown: string | null; evidenceId: string; kind: string };
      expect(data.ok).toBe(true);
      expect(data.imported).toBe(true);
      expect(data.markdown).toContain("可编辑内容");
      expect(data.kind).toBe("manuscript");
      expect(data.evidenceId).toMatch(/^evidence_[a-f0-9]{16}$/);

      const evidence = await readFile(join(root, ".psyclaw", "evidence.jsonl"), "utf8");
      expect(evidence).toContain("论文初稿.md");
      expect(evidence).toContain('"accessStatus":"partial"');
      const imports = await readFile(join(root, ".psyclaw", "imports.jsonl"), "utf8");
      expect(imports).toContain("psyclaw/import/v1");

      // second import is a no-op returning the existing record without markdown
      const again = await (await postJson(base, "/api/documents/import", { path: "paper/论文初稿.md" })).json() as { alreadyImported: boolean; markdown: string | null };
      expect(again.alreadyImported).toBe(true);
      expect(again.markdown).toBeNull();

      const listing = await (await fetch(`${base}/api/documents`)).json() as { documents: Array<{ path: string; imported: boolean }> };
      expect(listing.documents.find((doc) => doc.path === "paper/论文初稿.md")!.imported).toBe(true);
    });
  });

  it("rejects escape paths and unsupported formats", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-docs-bad-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await mkdir(join(root, "analysis", "scripts"), { recursive: true });
    await writeFile(join(root, "analysis", "scripts", "analyze.py"), "print(1)", "utf8");
    await withServer(root, async (base) => {
      const escape = await postJson(base, "/api/documents/import", { path: "../escape.md" });
      expect(escape.status).toBe(400);
      expect(await escape.text()).toContain("relative document path");
      const unsupported = await postJson(base, "/api/documents/import", { path: "analysis/scripts/analyze.py" });
      expect(unsupported.status).toBe(400);
      expect(await unsupported.text()).toContain("unsupported document format");
    });
  });

  it.runIf(pandocOk)("imports a .docx manuscript via pandoc into editable markdown", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-docs-docx-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await mkdir(join(root, "paper"), { recursive: true });
    await writeFile(join(root, "paper", "草案.md"), "# 草案\n\n这一段会进入 docx。\n", "utf8");
    const made = await new Promise<number>((resolve) => {
      const child = spawn("pandoc", [join(root, "paper", "草案.md"), "-o", join(root, "paper", "草案.docx")], { stdio: "ignore", shell: process.platform === "win32" });
      child.on("error", () => resolve(1));
      child.on("close", (code) => resolve(code ?? 1));
    });
    expect(made).toBe(0);

    await withServer(root, async (base) => {
      const res = await postJson(base, "/api/documents/import", { path: "paper/草案.docx" });
      expect(res.status).toBe(200);
      const data = await res.json() as { ok: boolean; markdown: string | null; format: string };
      expect(data.ok).toBe(true);
      expect(data.format).toBe("docx");
      expect(data.markdown).toContain("草案");
      expect(data.markdown).toContain("这一段会进入 docx");
    });
  });
});
