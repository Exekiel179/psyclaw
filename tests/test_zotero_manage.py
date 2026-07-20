"""Zotero 连带管理:文库搜索/入库/取全文都要能在对话里调到(离线,全注入)。

历史缺口:zotero_client 有 110 行可用的 Web API v3 客户端,但 add_by_doi 是空壳
(只返回「请你自己去 Zotero 点一下」),search_library/add_by_doi 的外部调用点为 0,
toolloop 里一个 zotero 工具都没有——能力在,对话里够不着。
"""
from __future__ import annotations

import json

from psyclaw.psych import zotero_client as z
from psyclaw.toolloop import build_tools

CR = {"message": {"DOI": "10.1000/x", "title": ["A real paper"],
                  "author": [{"given": "Li", "family": "Wang"}],
                  "container-title": ["Journal of Testing"],
                  "issued": {"date-parts": [[2021]]},
                  "volume": "3", "issue": "2", "page": "1-10",
                  "URL": "https://doi.org/10.1000/x"}}


def _creds(monkeypatch, on=True):
    monkeypatch.setenv("ZOTERO_API_KEY", "k" if on else "")
    monkeypatch.setenv("ZOTERO_LIBRARY_ID", "1" if on else "")


def test_to_zotero_item_maps_crossref_fields():
    it = z._to_zotero_item(CR["message"])
    assert it["itemType"] == "journalArticle"
    assert it["title"] == "A real paper"
    assert it["creators"][0]["lastName"] == "Wang"
    assert it["publicationTitle"] == "Journal of Testing" and it["date"] == "2021"
    assert it["DOI"] == "10.1000/x"


def test_add_by_doi_posts_item(monkeypatch):
    _creds(monkeypatch)
    monkeypatch.setattr(z, "find_by_doi", lambda d: None)
    sent = {}

    def _poster(body):
        sent["item"] = json.loads(body.decode())[0]
        return {"successful": {"0": {"key": "ABC123"}}, "failed": {}}
    r = z.add_by_doi("10.1000/x", getter=lambda u: CR, poster=_poster)
    assert r["status"] == "added" and r["key"] == "ABC123"
    assert sent["item"]["title"] == "A real paper"


def test_add_by_doi_is_idempotent(monkeypatch):
    """已在库不重复写——Zotero 允许重复条目,重复写会污染用户文库。"""
    _creds(monkeypatch)
    monkeypatch.setattr(z, "find_by_doi", lambda d: {"key": "OLD"})
    called = {"posted": False}

    def _poster(body):
        called["posted"] = True
        return {}
    r = z.add_by_doi("10.1000/x", getter=lambda u: CR, poster=_poster)
    assert r["status"] == "exists" and called["posted"] is False


def test_add_by_doi_refuses_when_metadata_missing(monkeypatch):
    """Crossref 查不到就不写——宁可不写,也不给用户文库塞空条目。"""
    _creds(monkeypatch)
    monkeypatch.setattr(z, "find_by_doi", lambda d: None)
    posted = {"n": 0}

    def _poster(body):
        posted["n"] += 1
        return {}
    r = z.add_by_doi("10.1000/none", getter=lambda u: {"message": {}},
                     poster=_poster)
    assert r["status"] == "not_found" and posted["n"] == 0


def test_add_by_doi_does_not_write_when_dedup_check_fails(monkeypatch):
    """查重本身失败时不能盲写(否则网络抖动就产生重复条目)。"""
    _creds(monkeypatch)

    def _boom(d):
        raise OSError("net")
    monkeypatch.setattr(z, "find_by_doi", _boom)
    posted = {"n": 0}
    r = z.add_by_doi("10.1000/x", getter=lambda u: CR,
                     poster=lambda b: posted.__setitem__("n", posted["n"] + 1))
    assert r["status"] == "error" and posted["n"] == 0


def test_add_by_doi_reports_zotero_rejection(monkeypatch):
    _creds(monkeypatch)
    monkeypatch.setattr(z, "find_by_doi", lambda d: None)
    r = z.add_by_doi("10.1000/x", getter=lambda u: CR,
                     poster=lambda b: {"successful": {},
                                       "failed": {"0": {"message": "bad"}}})
    assert r["status"] == "error" and "拒收" in r["note"]


def test_zotero_tools_registered():
    t = build_tools(".")
    for name in ("zotero_search", "zotero_fulltext", "zotero_add"):
        assert name in t, f"{name} 未注册为对话工具"
    assert t["zotero_add"]["side_effect"] is True      # 写用户文库须走审批
    assert t["zotero_search"]["side_effect"] is False  # 只读不必打扰


def test_zotero_tools_guide_when_unconfigured(monkeypatch):
    _creds(monkeypatch, on=False)
    t = build_tools(".")
    out = t["zotero_search"]["run"]({"query": "x"})
    assert "ZOTERO_API_KEY" in out          # 给配置指引而非裸报错


def test_sandbox_allows_sources_actually_used():
    """白名单漏域的表现是「沙箱一开某个源静默查不到」,极难归因。"""
    from psyclaw.sandbox import DEFAULT_POLICY
    allowed = DEFAULT_POLICY["net"]["allow_domains"]
    for host in ("api.crossref.org", "api.openalex.org",
                 "api.semanticscholar.org", "api.zotero.org"):
        assert host in allowed, f"{host} 不在沙箱网络白名单"
