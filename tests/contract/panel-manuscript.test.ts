import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { bootstrapProject } from "../../src/project/bootstrap.js";
import { verifyDoi } from "../../src/panel/server.js";
import { postJson, withServer } from "../helpers.js";

describe("manuscript panel endpoints", () => {
  it("returns an honest empty manuscript before any file exists", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-panel-ms-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await withServer(root, async (base) => {
      const res = await fetch(`${base}/api/manuscript`);
      expect(res.status).toBe(200);
      const data = await res.json() as { exists: boolean; markdown: string };
      expect(data.exists).toBe(false);
      expect(data.markdown).toBe("");
    });
  });

  it("saves the manuscript to a real project file and reloads it", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-panel-ms-save-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await withServer(root, async (base) => {
      const save = await postJson(base, "/api/manuscript", {
        content: "# 标题\n\n正文含论断 [核心论断](claim:0)。",
        path: "notes/manuscript.md",
      });
      expect(save.status).toBe(200);
      const saved = await save.json() as { ok: boolean; path: string; bytes: number };
      expect(saved.ok).toBe(true);
      expect(saved.path).toBe("notes/manuscript.md");

      const onDisk = await readFile(join(root, "notes", "manuscript.md"), "utf8");
      expect(onDisk).toContain("# 标题");
      expect(onDisk).toContain("(claim:0)");

      const get = await fetch(`${base}/api/manuscript`);
      const data = await get.json() as { exists: boolean; path: string | null; markdown: string };
      expect(data.exists).toBe(true);
      expect(data.path).toBe("notes/manuscript.md");
      expect(data.markdown).toContain("核心论断");
    });
  });

  it("rejects manuscript paths outside notes/ and outputs/", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-panel-ms-escape-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await withServer(root, async (base) => {
      const res = await postJson(base, "/api/manuscript", { content: "x", path: "../escape.md" });
      expect(res.status).toBe(400);
      expect(await res.text()).toContain("relative manuscript path");
    });
  });

  it("falls back to a real report when no manuscript exists yet", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-panel-ms-fallback-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    const { mkdir } = await import("node:fs/promises");
    await mkdir(join(root, "outputs"), { recursive: true });
    await writeFile(join(root, "outputs", "literature-review.md"), "# 文献综述\n真实内容", "utf8");
    await withServer(root, async (base) => {
      const data = await (await fetch(`${base}/api/manuscript`)).json() as { exists: boolean; path: string | null; markdown: string };
      expect(data.exists).toBe(true);
      expect(data.path).toBe("outputs/literature-review.md");
      expect(data.markdown).toContain("真实内容");
    });
  });
});

describe("ledger claim and evidence endpoints", () => {
  it("appends a claim to the real .psyclaw/claims.jsonl ledger", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-panel-claim-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await withServer(root, async (base) => {
      const res = await postJson(base, "/api/claim", { text: "真实论断文本", kind: "result", status: "uncertain" });
      expect(res.status).toBe(200);
      const data = await res.json() as { ok: boolean; claim: { id: string; text: string; status: string } };
      expect(data.ok).toBe(true);
      expect(data.claim.id).toMatch(/^claim_[a-f0-9]{16}$/);
      expect(data.claim.status).toBe("uncertain");

      const onDisk = await readFile(join(root, ".psyclaw", "claims.jsonl"), "utf8");
      expect(onDisk).toContain("真实论断文本");

      const map = await (await fetch(`${base}/api/literature-map`)).json() as { claims: Array<{ id: string }> };
      expect(map.claims.some((claim) => claim.id === data.claim.id)).toBe(true);
    });
  });

  it("attaches evidence with a supports link, kept partial until audited", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-panel-evidence-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await withServer(root, async (base) => {
      const claimRes = await (await postJson(base, "/api/claim", { text: "被支持的论断", kind: "result", status: "uncertain" })).json() as { claim: { id: string } };
      const res = await postJson(base, "/api/evidence", {
        claimId: claimRes.claim.id,
        title: "Smith et al. (2021). A Study.",
        doi: "10.1000/sample",
        quote: "原文摘录",
      });
      expect(res.status).toBe(200);
      const data = await res.json() as { ok: boolean; evidence: { id: string; accessStatus: string; source: { kind: string; locator: string } }; link: { claimId: string; evidenceId: string; relation: string } };
      expect(data.ok).toBe(true);
      expect(data.evidence.source.kind).toBe("doi");
      expect(data.evidence.accessStatus).toBe("partial");
      expect(data.link.relation).toBe("supports");
      expect(data.link.claimId).toBe(claimRes.claim.id);

      const evidenceOnDisk = await readFile(join(root, ".psyclaw", "evidence.jsonl"), "utf8");
      expect(evidenceOnDisk).toContain("10.1000/sample");
      const claimsOnDisk = await readFile(join(root, ".psyclaw", "claims.jsonl"), "utf8");
      expect(claimsOnDisk).toContain(`"claimId":"${claimRes.claim.id}"`);
      expect(claimsOnDisk).toContain("supports");
    });
  });

  it("keeps /api/ledger read-only (POST rejected)", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-panel-ledger-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await withServer(root, async (base) => {
      expect((await postJson(base, "/api/ledger", {})).status).toBe(405);
    });
  });
});

describe("verifyDoi (real cross-source, never faked)", () => {
  it("returns verified when Crossref and OpenAlex agree", async () => {
    const fetchFn = async (url: string): Promise<Response> => {
      if (url.includes("crossref.org")) {
        return new Response(JSON.stringify({
          message: { title: ["Same Title"], author: [{ family: "Smith", given: "John" }], issued: { "date-parts": [[2021]] }, "container-title": ["A Journal"] },
        }), { status: 200 });
      }
      return new Response(JSON.stringify({ title: "Same Title", cited_by_count: 7 }), { status: 200 });
    };
    const result = await verifyDoi("10.1000/abc123", fetchFn as typeof fetch);
    expect(result.status).toBe("verified");
    expect(result.crossref?.title).toBe("Same Title");
    expect(result.crossref?.authors).toEqual(["John Smith"]);
    expect(result.crossref?.year).toBe(2021);
    expect(result.openalex?.citedBy).toBe(7);
  });

  it("flags a cross-source title mismatch as unverified", async () => {
    const fetchFn = async (url: string): Promise<Response> => {
      if (url.includes("crossref.org")) return new Response(JSON.stringify({ message: { title: ["Title A"] } }), { status: 200 });
      return new Response(JSON.stringify({ title: "Title B" }), { status: 200 });
    };
    const result = await verifyDoi("10.1000/abc123", fetchFn as typeof fetch);
    expect(result.status).toBe("unverified");
    expect(result.mismatch).toContain("Title A");
  });

  it("returns error for an invalid DOI without any network call", async () => {
    const result = await verifyDoi("not-a-doi", (async () => { throw new Error("network must not be touched"); }) as typeof fetch);
    expect(result.status).toBe("error");
    expect(result.error).toContain("合法 DOI");
  });

  it("returns error when both sources are unreachable", async () => {
    const fetchFn = async (): Promise<Response> => new Response("nope", { status: 503 });
    const result = await verifyDoi("10.1000/abc123", fetchFn as typeof fetch);
    expect(result.status).toBe("error");
  });
});
