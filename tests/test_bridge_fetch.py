"""WebBridge 驱动已登录浏览器直抓付费墙全文(feat-191)。

分工:capture_from_downloads 要用户点一下「Download PDF」(零安装,永远可用);
本路装了扩展后连点都不用——在**用户自己的浏览器**里 fetch,带着他登录后的会话
拿到字节流。用的仍是用户本人的权限,不绕过任何付费墙。

守住的要点:
- 落盘前必须过 %PDF 魔数(出版社常把登录页/拦截页当 200 返回);
- 字节数对不上就不落盘(分片传输可能中断);
- 桥不可用时说清**缺哪一步**并给退路,而不是一句「不可用」。
"""
from __future__ import annotations

import base64
import json

from psyclaw.psych.bridge_fetch import bridge_ready, fetch_pdf_via_browser

PDF = b"%PDF-1.7\n" + bytes(range(256)) * 40      # ~10KB,跨多次分片


def _caller(data=PDF, pdf_url="https://pub/x.pdf", ok=True, status=200):
    """假桥:按 evaluate 的 code 特征返回对应结果。"""
    def _c(action, args=None, **kw):
        args = args or {}
        if action != "evaluate":
            return {"success": True, "result": None}
        code = args.get("code", "")
        if "citation_pdf_url" in code:
            return {"success": True, "result": pdf_url}
        if "arrayBuffer" in code:
            return {"success": True, "result": json.dumps(
                {"ok": ok, "status": status, "len": len(data),
                 "type": "application/pdf"})}
        if "subarray" in code:
            import re
            m = re.search(r"subarray\((\d+), (\d+)\)", code)
            s, e = int(m.group(1)), int(m.group(2))
            return {"success": True,
                    "result": base64.b64encode(data[s:e]).decode()}
        return {"success": True, "result": None}
    return _c


def test_fetches_and_writes_pdf(tmp_path):
    out = tmp_path / "outputs" / "pdfs" / "a.pdf"
    r = fetch_pdf_via_browser("https://pub/article", out, caller=_caller())
    assert r["ok"] is True
    assert out.read_bytes() == PDF                 # 分片拼接必须字节级一致
    assert r["bytes"] == len(PDF)


def test_chunking_covers_large_file(tmp_path):
    big = b"%PDF-1.7\n" + b"z" * 500_000           # 强制多次分片
    out = tmp_path / "b.pdf"
    r = fetch_pdf_via_browser("https://pub/article", out, caller=_caller(big))
    assert r["ok"] is True and out.read_bytes() == big


def test_rejects_non_pdf_payload(tmp_path):
    """登录页被当 200 返回是常态——魔数不对就不许落盘。"""
    out = tmp_path / "c.pdf"
    r = fetch_pdf_via_browser("https://pub/article", out,
                              caller=_caller(b"<html>Sign in</html>"))
    assert r["ok"] is False and "不是 PDF" in r["note"]
    assert not out.exists()


def test_http_error_reported(tmp_path):
    out = tmp_path / "d.pdf"
    r = fetch_pdf_via_browser("https://pub/article", out,
                              caller=_caller(ok=False, status=403))
    assert r["ok"] is False and "403" in r["note"]
    assert not out.exists()


def test_no_pdf_link_found_gives_next_step(tmp_path):
    out = tmp_path / "e.pdf"
    r = fetch_pdf_via_browser("https://pub/article", out, caller=_caller(pdf_url=""))
    assert r["ok"] is False
    assert "lit_capture_pdf" in r["note"]          # 给退路,别让路走死


def test_truncated_transfer_does_not_write(tmp_path):
    """分片中断必须整篇作废,绝不落一个半截 PDF。"""
    def _c(action, args=None, **kw):
        code = (args or {}).get("code", "")
        if "citation_pdf_url" in code:
            return {"success": True, "result": "https://pub/x.pdf"}
        if "arrayBuffer" in code:
            return {"success": True,
                    "result": json.dumps({"ok": True, "status": 200,
                                          "len": 999_999, "type": "application/pdf"})}
        if "subarray" in code:
            return {"success": False, "error": "extension disconnected"}
        return {"success": True, "result": None}
    out = tmp_path / "f.pdf"
    r = fetch_pdf_via_browser("https://pub/article", out, caller=_c)
    assert r["ok"] is False and "中断" in r["note"]
    assert not out.exists()


def test_bridge_ready_says_which_step_is_missing():
    assert "webbridge install" in bridge_ready(bin_fn=lambda: False)["note"]
    r = bridge_ready(bin_fn=lambda: True, status_fn=lambda: None)
    assert "webbridge start" in r["note"]
    r = bridge_ready(bin_fn=lambda: True,
                     status_fn=lambda: {"extension_connected": False})
    assert "扩展没连上" in r["note"]
    r = bridge_ready(bin_fn=lambda: True,
                     status_fn=lambda: {"extension_connected": True})
    assert r["ok"] is True


def test_tool_registered_and_falls_back_when_bridge_down(monkeypatch):
    from psyclaw.toolloop import build_tools
    t = build_tools(".")
    assert "lit_fetch_via_browser" in t
    assert t["lit_fetch_via_browser"]["side_effect"] is True
    monkeypatch.setattr("psyclaw.psych.bridge_fetch.bridge_ready",
                        lambda *a, **k: {"ok": False, "note": "没装"})
    out = t["lit_fetch_via_browser"]["run"]({"doi": "10.1/x"})
    assert "lit_capture_pdf" in out and "lit_open_institutional" in out
