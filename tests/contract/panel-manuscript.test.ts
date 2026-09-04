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

  it("stays read-only: /api/manuscript rejects writes (405) and reflects real project files", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-panel-ms-save-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await withServer(root, async (base) => {
      // The panel is a read-only projection; manuscript writes happen through
      // the agent workflow layer, never through the panel HTTP surface.
      const save = await postJson(base, "/api/manuscript", {
        content: "# 标题\n\n正文含论断 [核心论断](claim:0)。",
        path: "notes/manuscript.md",
      });
      expect(save.status).toBe(405);
      expect(save.headers.get("allow")).toContain("GET");

      // A manuscript written to the real project file is served read-only.
      await writeFile(join(root, "notes", "manuscript.md"), "# 标题\n\n正文含论断 [核心论断](claim:0)。\n", "utf8");
      const get = await fetch(`${base}/api/manuscript`);
      const data = await get.json() as { exists: boolean; path: string | null; markdown: string };
      expect(data.exists).toBe(true);
      expect(data.path).toBe("notes/manuscript.md");
      expect(data.markdown).toContain("核心论断");
    });
  });

  it("rejects panel write attempts for any path, including escapes", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-panel-ms-escape-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await withServer(root, async (base) => {
      // Path validation now lives in the workflow write layer; the panel
      // refuses every mutation attempt at the method gate before any path is
      // interpreted, so escape attempts cannot reach a writer.
      const res = await postJson(base, "/api/manuscript", { content: "x", path: "../escape.md" });
      expect(res.status).toBe(405);
      expect(await res.text()).toContain("method not allowed");
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
  it("keeps the ledger append-only from the agent layer; panel claim writes are refused", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-panel-claim-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await withServer(root, async (base) => {
      const res = await postJson(base, "/api/claim", { text: "真实论断文本", kind: "result", status: "uncertain" });
      expect(res.status).toBe(405);
      expect(await res.text()).toContain("method not allowed");

      // Claims appended through the real ledger writer are served read-only.
      const { appendClaim } = await import("../../src/research/ledger.js");
      await appendClaim(root, { id: "claim_0123456789abcdef", text: "面板展示论断", kind: "definition", evidenceIds: [], status: "supported" });
      const map = await (await fetch(`${base}/api/literature-map`)).json() as { claims: Array<{ id: string; text: string }> };
      expect(map.claims.some((claim) => claim.id === "claim_0123456789abcdef" && claim.text === "面板展示论断")).toBe(true);
    });
  });

  it("refuses evidence writes over HTTP; ledger projections stay read-only", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-panel-evidence-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    await withServer(root, async (base) => {
      const res = await postJson(base, "/api/evidence", {
        claimId: "claim_does_not_matter",
        title: "Smith et al. (2021). A Study.",
        doi: "10.1000/sample",
        quote: "原文摘录",
      });
      expect(res.status).toBe(405);
      expect(await res.text()).toContain("method not allowed");

      // The API must not have interpreted the payload: nothing was written.
      const evidenceOnDisk = await readFile(join(root, ".psyclaw", "evidence.jsonl"), "utf8").catch(() => "");
      expect(evidenceOnDisk).not.toContain("10.1000/sample");
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
