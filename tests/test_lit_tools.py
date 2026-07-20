"""文献能力做成对话原生工具:模型在 chat 里直接调 lit_search/lit_snowball/lit_download,
不用用户记 CLI。用户主要以对话形式工作,能力就该是工具。
"""
from __future__ import annotations

from psyclaw.psych import litsearch as ls
from psyclaw.toolloop import build_tools


def test_lit_tools_registered():
    tools = build_tools(".")
    for name in ("lit_search", "lit_snowball", "lit_download"):
        assert name in tools, f"缺工具 {name}"
    assert tools["lit_download"]["side_effect"] is True     # 下载写盘,需批准
    assert tools["lit_search"]["side_effect"] is False      # 检索只读,自动执行


def test_lit_search_tool_runs(monkeypatch):
    monkeypatch.setattr(ls, "search", lambda q, **k: {
        "per_source": {"openalex": 1}, "n_deduped": 1,
        "results": [{"title": "公正世界信念研究", "authors": ["杜建政", "祝振兵"],
                     "year": 2007, "doi": "10.1/x", "oa_status": "closed",
                     "citations": 88}]})
    out = build_tools(".")["lit_search"]["run"]({"query": "公正世界信念"})
    assert "公正世界信念研究" in out and "doi:10.1/x" in out and "被引88" in out


def test_lit_snowball_tool_runs(monkeypatch):
    monkeypatch.setattr(ls, "snowball", lambda doi, **k: [
        {"title": "引用了它的新文献", "authors": ["A"], "year": 2022, "doi": "10.2/y"}])
    out = build_tools(".")["lit_snowball"]["run"]({"doi": "10.1/x", "direction": "citations"})
    assert "引用了它的新文献" in out


def test_lit_download_tool_runs(monkeypatch, tmp_path):
    monkeypatch.setattr(ls, "search", lambda q, **k: {"results": [{"doi": "10.1/x", "title": "T"}]})
    monkeypatch.setattr(ls, "fetch_and_save", lambda p, out_dir=None: {
        "status": "oa_pdf", "channel": "Unpaywall OA",
        "downloaded": {"ok": True, "path": str(tmp_path / "Li_2020_T.pdf"), "bytes": 4096}})
    out = build_tools(str(tmp_path))["lit_download"]["run"]({"query": "x"})
    assert "下载 1 篇" in out and "Li_2020_T.pdf" in out


def test_lit_download_reports_paywall(monkeypatch, tmp_path):
    """付费墙要**指路**而非只报「跳过」——用户往往有机构权限,只是需要去浏览器登录。"""
    monkeypatch.setattr(ls, "fetch_and_save", lambda p, out_dir=None: {"status": "closed"})
    out = build_tools(str(tmp_path))["lit_download"]["run"]({"doi": "10.1/x"})
    assert "付费墙 1 篇" in out
    assert "lit_open_institutional" in out       # feat-189:给下一步,别让路走死


def test_lit_search_needs_query():
    assert "需要 query" in build_tools(".")["lit_search"]["run"]({})
