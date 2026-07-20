"""付费墙 → 唤起浏览器走机构登录(feat-189)。

此前的死路:fetch_and_save 遇付费墙只返回一句「配置机构权限/用 Zotero」,不做任何
事;lit_download 只说「跳过 N 篇」。用户看到的就是「❌ 付费墙 ——」然后没有下一步,
模型据此告诉用户「无法获取」——**而用户本人往往是有权限的**(在校/VPN/机构账号),
缺的只是在真实浏览器里登一下。真实浏览器带着他的 SSO 会话,出版社认的正是那个会话。

不绕过任何付费墙:用的是用户自己的权限,psyclaw 只负责把他送到门口,
且全程不碰账号密码(登录在浏览器里由用户自己完成)。
"""
from __future__ import annotations

from psyclaw.psych import paywall
from psyclaw.toolloop import build_tools

DOI = "10.1177/0146167225123456"


def test_falls_back_to_doi_org_when_no_institution(monkeypatch):
    from psyclaw.psych import institution
    monkeypatch.setattr(institution, "libkey_fulltext", lambda d: None)
    monkeypatch.setattr(institution, "ezproxy_url", lambda u: None)
    r = paywall.resolve_entry(DOI)
    assert r["url"].endswith(DOI)
    assert "doi.org" in r["url"]


def test_libkey_wins_when_configured(monkeypatch):
    from psyclaw.psych import institution
    monkeypatch.setattr(institution, "libkey_fulltext",
                        lambda d: {"url": "https://libkey.io/pdf/1"})
    r = paywall.resolve_entry(DOI)
    assert r["url"] == "https://libkey.io/pdf/1"
    assert "LibKey" in r["channel"]


def test_ezproxy_used_when_no_libkey(monkeypatch):
    from psyclaw.psych import institution
    monkeypatch.setattr(institution, "libkey_fulltext", lambda d: None)
    monkeypatch.setattr(institution, "ezproxy_url",
                        lambda u: f"https://ezp.univ.edu/login?url={u}")
    r = paywall.resolve_entry(DOI)
    assert r["url"].startswith("https://ezp.univ.edu/login?url=")
    assert "EZProxy" in r["channel"]


def test_institution_errors_do_not_break_handoff(monkeypatch):
    """机构层报错不能让整条路断掉——至少还能落到 doi.org。"""
    from psyclaw.psych import institution

    def _boom(*a, **k):
        raise RuntimeError("conf broken")
    monkeypatch.setattr(institution, "libkey_fulltext", _boom)
    monkeypatch.setattr(institution, "ezproxy_url", _boom)
    r = paywall.resolve_entry(DOI)
    assert "doi.org" in r["url"]


def test_browser_handoff_opens_url_and_makes_pdf_dir(tmp_path):
    opened = []
    r = paywall.browser_handoff(DOI, project_dir=str(tmp_path),
                                opener=lambda u: opened.append(u) or True)
    assert r["ok"] is True and opened and DOI in opened[0]
    assert (tmp_path / "outputs" / "pdfs").is_dir()   # 目录先建好,用户另存时就在


def test_handoff_message_gives_concrete_next_steps(tmp_path):
    r = paywall.browser_handoff(DOI, project_dir=str(tmp_path),
                                opener=lambda u: True)
    msg = paywall.handoff_message(r, DOI)
    assert "机构账号登录" in msg
    assert str(r["pdf_dir"]) in msg                   # 明确告诉用户存到哪
    assert "read_file" in msg                         # 只指向真实存在的能力


def test_message_references_no_nonexistent_tool(tmp_path):
    """引导文案不许提不存在的工具(第一版曾写了并不存在的 lit_import)。"""
    r = paywall.browser_handoff(DOI, project_dir=str(tmp_path), opener=lambda u: True)
    msg = paywall.handoff_message(r, DOI)
    tools = set(build_tools(".")) | {"read_file"}
    import re
    for name in re.findall(r"\b(lit_[a-z_]+|zotero_[a-z_]+)\b", msg):
        assert name in tools, f"引导文案提到了不存在的工具:{name}"


def test_no_doi_no_url_is_rejected():
    r = paywall.browser_handoff("", project_dir=".", opener=lambda u: True)
    assert r["ok"] is False


def test_tool_registered_and_needs_approval():
    t = build_tools(".")
    assert "lit_open_institutional" in t
    assert t["lit_open_institutional"]["side_effect"] is True   # 会弹浏览器,先问


def test_download_result_points_to_handoff(monkeypatch):
    """lit_download 撞付费墙时必须指路,而不是只说「跳过 N 篇」。"""
    from psyclaw.psych import litsearch
    monkeypatch.setattr(litsearch, "search", lambda *a, **k: {
        "results": [{"doi": "10.1/x", "title": "T"}], "per_source": {},
        "n_raw": 1, "n_deduped": 1, "n_duplicates": 0})
    monkeypatch.setattr(litsearch, "fetch_and_save",
                        lambda p, out_dir=None: {"status": "closed"})
    out = build_tools(".")["lit_download"]["run"]({"query": "x", "limit": 1})
    assert "lit_open_institutional" in out
    assert "10.1/x" in out                            # 列出待取的 DOI
