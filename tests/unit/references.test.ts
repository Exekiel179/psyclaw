import { describe, expect, it } from "vitest";
import { checkCitations, extractCitations, referenceFromVerification } from "../../src/core/references.js";

describe("extractCitations", () => {
  it("extracts English in-text citation groups", () => {
    const hits = extractCitations("其高发性已引起关注（Kessler et al., 2005; Wanberg et al., 2010）。");
    expect(hits).toContainEqual({ surname: "Kessler", years: [2005] });
    expect(hits).toContainEqual({ surname: "Wanberg", years: [2010] });
  });

  it("extracts Chinese author citations", () => {
    const hits = extractCitations("（张三，2020；李四 等，2018）");
    expect(hits).toContainEqual({ surname: "张三", years: [2020] });
    expect(hits).toContainEqual({ surname: "李四", years: [2018] });
  });

  it("merges repeated surnames across groups", () => {
    const hits = extractCitations("（Kessler et al., 2005）与（Kessler, 2010）");
    expect(hits).toContainEqual({ surname: "Kessler", years: [2005, 2010] });
  });

  it("returns [] when there are no citations", () => {
    expect(extractCitations("没有任何括号引用的普通文本。")).toEqual([]);
  });
});

describe("checkCitations", () => {
  const references = [
    {
      schemaVersion: "psyclaw/reference/v1",
      doi: "10.1000/kessler",
      title: "Kessler study",
      authors: ["Ronald C Kessler"],
      year: 2005,
      verified: true,
      verification: { schemaVersion: "psyclaw/doi-verify/v1", doi: "10.1000/kessler", status: "verified" as const, verifiedAt: "" },
      addedAt: "",
    },
  ];

  it("matches archived references by surname + year and flags gaps", () => {
    const result = checkCitations("（Kessler et al., 2005; Missing et al., 2012）", references);
    expect(result.matched).toBe(1);
    expect(result.unmatched).toBe(1);
    const kessler = result.citations.find((c) => c.surname === "Kessler");
    expect(kessler?.missing).toBe(false);
    expect(kessler?.matched[0]?.doi).toBe("10.1000/kessler");
    const missing = result.citations.find((c) => c.surname === "Missing");
    expect(missing?.missing).toBe(true);
  });

  it("does not match the same surname in a different year", () => {
    const result = checkCitations("（Kessler et al., 2019）", references);
    expect(result.citations.find((c) => c.surname === "Kessler")?.missing).toBe(true);
  });
});

describe("referenceFromVerification", () => {
  it("builds a record only from a verified/unverified DOI with metadata", () => {
    const record = referenceFromVerification({
      schemaVersion: "psyclaw/doi-verify/v1",
      doi: "10.1000/x",
      status: "verified",
      crossref: { title: "A Title", authors: ["John Smith"], year: 2021, container: "A Journal" },
      verifiedAt: "2026-01-01T00:00:00.000Z",
    });
    expect(record?.title).toBe("A Title");
    expect(record?.authors).toEqual(["John Smith"]);
    expect(record?.year).toBe(2021);
    expect(record?.venue).toBe("A Journal");
    expect(record?.verified).toBe(true);
  });

  it("returns null for an errored verification", () => {
    expect(referenceFromVerification({
      schemaVersion: "psyclaw/doi-verify/v1",
      doi: "bad",
      status: "error",
      error: "nope",
      verifiedAt: "",
    })).toBeNull();
  });
});
