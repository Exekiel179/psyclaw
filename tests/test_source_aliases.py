"""不认识的检索源必须现形,不能静默返回 0 条(feat-187)。

真实事故:模型写 `--source pubmed`,而 search() 用 `if s in fn` 静默跳过不认识的
源 → per_source {} 、0 条结果。「全不认识」与「这领域真没论文」输出完全一样,
模型据此断定「没有检索能力/没有相关文献」而放弃。

而 pubmed 其实**有对应**:EuropePMC 就索引 PubMed。所以:能映射的映射,
映射不了的在 per_source["_note"] 里明说,并退回默认源,不让调用方空手而归。
"""
from __future__ import annotations

from psyclaw.psych import litsearch


def _stub(monkeypatch, tag="openalex"):
    """把所有源函数换成可辨识的桩,避免测试打网。"""
    for name in ("search_openalex", "search_europepmc", "search_arxiv",
                 "search_crossref", "search_semantic_scholar"):
        monkeypatch.setattr(litsearch, name,
                            lambda *a, _n=name, **k: [
                                litsearch._paper(title=f"T-{_n}", authors=["A"],
                                                 year=2024, doi=f"10.1/{_n}",
                                                 abstract="", source=_n)])


def test_pubmed_maps_to_europepmc(monkeypatch):
    """PubMed 的内容 EuropePMC 就在索引——这是真对应,不是糊弄。"""
    _stub(monkeypatch)
    r = litsearch.search("x", sources=["pubmed"])
    assert "europepmc" in r["per_source"]
    assert r["n_deduped"] >= 1


def test_unknown_source_falls_back_and_says_so(monkeypatch):
    _stub(monkeypatch)
    r = litsearch.search("x", sources=["scopus"])
    note = r["per_source"].get("_note", "")
    assert "scopus" in note and "默认源" in note
    assert r["n_deduped"] >= 1          # 退回默认源,不空手而归


def test_partial_unknown_keeps_known_and_notes(monkeypatch):
    _stub(monkeypatch)
    r = litsearch.search("x", sources=["openalex", "webofscience"])
    assert r["per_source"].get("openalex") == 1
    assert "webofscience" in r["per_source"].get("_note", "")


def test_no_sources_uses_defaults(monkeypatch):
    _stub(monkeypatch)
    r = litsearch.search("x")
    for s in litsearch.DEFAULT_SOURCES:
        assert s in r["per_source"]


def test_alias_case_and_duplicates_normalized(monkeypatch):
    _stub(monkeypatch)
    r = litsearch.search("x", sources=["PubMed", "medline", "europepmc"])
    # 三个名字都指向 EuropePMC,只应查一次
    assert list(r["per_source"]).count("europepmc") == 1
