"""更好的文献查找:加 Crossref(中文核心 DOI)+ Semantic Scholar(摘要/TL;DR/被引)+ 引用滚雪球。

替代脆弱的网页桥:公开 API 稳定、可编程、无需登录/浏览器。中文核心期刊(有 DOI)
Crossref/OpenAlex 本就覆盖;引用滚雪球从种子文献沿引用网络扩展,是综述正道。
"""
from __future__ import annotations

from psyclaw.psych import litsearch as ls


def test_crossref_parses(monkeypatch):
    sample = {"message": {"items": [
        {"DOI": "10.3724/sp.j.1042.2013.00144",
         "title": ["公正世界信念:一把双刃剑"],
         "author": [{"given": "春燕", "family": "周"}, {"given": "永玉", "family": "郭"}],
         "issued": {"date-parts": [[2013]]},
         "container-title": ["心理科学进展"], "abstract": "<p>摘要正文</p>"}]}}
    monkeypatch.setattr(ls, "_get", lambda *a, **k: sample)
    out = ls.search_crossref("公正世界信念")
    assert len(out) == 1
    r = out[0]
    assert r["doi"] == "10.3724/sp.j.1042.2013.00144"
    assert r["year"] == 2013 and "周" in r["authors"][0]
    assert "<p>" not in r["abstract"] and "摘要正文" in r["abstract"]
    assert r["source"] == "Crossref"


def test_semantic_scholar_parses_tldr_and_citations(monkeypatch):
    sample = {"data": [
        {"title": "Belief in a Just World", "year": 2015,
         "authors": [{"name": "A. Lerner"}],
         "externalIds": {"DOI": "10.1/x"}, "abstract": "full abstract",
         "tldr": {"text": "一句话总结"}, "citationCount": 321,
         "openAccessPdf": {"url": "http://oa/x.pdf"}}]}
    monkeypatch.setattr(ls, "_get", lambda *a, **k: sample)
    out = ls.search_semantic_scholar("just world")
    r = out[0]
    assert r["doi"] == "10.1/x" and r["citations"] == 321
    assert "TL;DR: 一句话总结" in r["abstract"]
    assert r["oa_status"] == "gold" and r["oa_url"] == "http://oa/x.pdf"


def test_search_includes_crossref_by_default(monkeypatch):
    monkeypatch.setattr(ls, "search_openalex", lambda *a, **k: [])
    monkeypatch.setattr(ls, "search_europepmc", lambda *a, **k: [])
    seen = {}
    monkeypatch.setattr(ls, "search_crossref",
                        lambda *a, **k: seen.setdefault("cr", True) or [])
    r = ls.search("公正世界信念")
    assert "crossref" in r["per_source"]          # 默认源含 crossref
    assert seen.get("cr")


def test_snowball_citations_and_references(monkeypatch):
    seed = {"cited_by_api_url": "https://api.openalex.org/works?filter=cites:W1",
            "referenced_works": ["https://openalex.org/W9", "https://openalex.org/W8"]}
    cited = {"results": [{"title": "引用了种子的新文献", "publication_year": 2022,
                          "doi": "https://doi.org/10.9/new", "authorships": []}]}
    refs = {"results": [{"title": "种子引用的经典", "publication_year": 2001,
                         "doi": "https://doi.org/10.9/old", "authorships": []}]}

    def _get(url, *a, **k):
        if "works/https://doi.org/" in url:
            return seed
        if "filter=cites" in url or "cited_by" in url:
            return cited
        if "openalex_id:" in url:
            return refs
        return {}
    monkeypatch.setattr(ls, "_get", _get)

    cites = ls.snowball("10.1/seed", direction="citations")
    assert any("新文献" in p["title"] for p in cites)
    both = ls.snowball("10.1/seed", direction="both")
    titles = [p["title"] for p in both]
    assert any("新文献" in t for t in titles) and any("经典" in t for t in titles)


def test_snowball_failsafe(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(ls, "_get", _boom)
    assert ls.snowball("10.1/x") == []             # 异常不抛,返回空
