"""全文下载覆盖机构权限:不只 OA,还下 LibKey 全文直链 / 机构 IP 授权直连的 PDF。

缺口:fetch_and_save 此前只对 status==oa_pdf 真下载,机构权限(institutional)只返回链接。
打通后机构权限链接也纳入 PDF 候选真下载;需 SSO 会话的(EZProxy)urllib 下不了则给
browser_hint 引导浏览器,绝不把登录页 HTML 存成 PDF。
"""
from __future__ import annotations

from psyclaw.psych import litsearch as ls


def test_institutional_url_enters_pdf_candidates():
    res = {"status": "institutional", "url": "https://inst.libkey/pdf/10.1x"}
    cands = ls._pdf_candidates({"oa_url": None}, res)
    assert "https://inst.libkey/pdf/10.1x" in cands


def test_fetch_and_save_downloads_institutional(monkeypatch, tmp_path):
    monkeypatch.setattr(ls, "get_fulltext",
                        lambda paper, out_dir=None: {"status": "institutional",
                                                     "channel": "LibKey(机构订阅)",
                                                     "url": "https://libkey/pdf/x"})
    called = {}

    def _dl(url, dest, meta):
        called["url"] = url
        return {"ok": True, "path": str(tmp_path / "a.pdf"), "bytes": 2048, "url": url}
    monkeypatch.setattr(ls, "download_pdf", _dl)
    res = ls.fetch_and_save({"doi": "10.1/x", "title": "T", "authors": ["Li"]},
                            out_dir=str(tmp_path))
    assert res["downloaded"]["ok"] is True
    assert called["url"] == "https://libkey/pdf/x"


def test_fetch_and_save_institutional_needs_session_gives_browser_hint(monkeypatch, tmp_path):
    monkeypatch.setattr(ls, "get_fulltext",
                        lambda paper, out_dir=None: {"status": "institutional",
                                                     "channel": "EZProxy",
                                                     "url": "https://ezproxy/login?url=pub"})
    # EZProxy 拿到的是登录页 HTML,download_pdf 靠 %PDF 校验如实失败
    monkeypatch.setattr(ls, "download_pdf",
                        lambda url, dest, meta: {"ok": False, "url": url,
                                                 "note": "非 PDF(HTML 登录页)"})
    res = ls.fetch_and_save({"doi": "10.1/x", "title": "T", "authors": ["Li"]},
                            out_dir=str(tmp_path))
    assert res["downloaded"]["ok"] is False
    assert "browser_hint" in res["downloaded"]
    assert "ezproxy" in res["downloaded"]["browser_hint"]


def test_closed_paywall_still_not_downloaded(monkeypatch, tmp_path):
    monkeypatch.setattr(ls, "get_fulltext",
                        lambda paper, out_dir=None: {"status": "closed",
                                                     "note": "付费墙,不绕过"})
    res = ls.fetch_and_save({"doi": "10.1/x"}, out_dir=str(tmp_path))
    assert res["status"] == "closed" and "downloaded" not in res
