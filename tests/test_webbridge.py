"""feat-108:Kimi WebBridge 接入——真实浏览器登录态 + 默认浏览器识别。"""

from __future__ import annotations

import io
import json
import plistlib

import pytest

from psyclaw import webbridge as wb


# ---------------------------------------------------------------------------
# 默认浏览器识别(macOS LaunchServices)
# ---------------------------------------------------------------------------

def _fake_ls_plist(tmp_path, bundle_id: str):
    data = {"LSHandlers": [
        {"LSHandlerURLScheme": "mailto", "LSHandlerRoleAll": "com.apple.mail"},
        {"LSHandlerURLScheme": "http", "LSHandlerRoleAll": bundle_id},
    ]}
    p = tmp_path / "ls.plist"
    p.write_bytes(plistlib.dumps(data))
    return p


def test_default_browser_arc(tmp_path, monkeypatch):
    """Arc(company.thebrowser.Browser)被识别为 Chromium 系默认浏览器。"""
    p = _fake_ls_plist(tmp_path, "company.thebrowser.Browser")
    monkeypatch.setattr("sys.platform", "darwin")

    class _FakePath:
        def read_bytes(self):
            return p.read_bytes()
    import pathlib
    real_home = pathlib.Path.home()
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: real_home))
    # 直接替换 plist 读取路径:构造与真实结构同形的临时 HOME
    home = tmp_path / "home"
    dst = home / "Library" / "Preferences" / "com.apple.LaunchServices"
    dst.mkdir(parents=True)
    (dst / "com.apple.launchservices.secure.plist").write_bytes(p.read_bytes())
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))
    db = wb.default_browser()
    assert db == {"bundle_id": "company.thebrowser.browser", "name": "Arc",
                  "chromium": True}


def test_default_browser_safari_not_chromium(tmp_path, monkeypatch):
    import pathlib
    home = tmp_path / "home"
    dst = home / "Library" / "Preferences" / "com.apple.LaunchServices"
    dst.mkdir(parents=True)
    (dst / "com.apple.launchservices.secure.plist").write_bytes(
        _fake_ls_plist(tmp_path, "com.apple.Safari").read_bytes())
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))
    db = wb.default_browser()
    assert db["name"] == "Safari" and db["chromium"] is False


def test_default_browser_none_when_plist_missing(tmp_path, monkeypatch):
    import pathlib
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: tmp_path))
    assert wb.default_browser() is None


# ---------------------------------------------------------------------------
# daemon 通信(stdlib http 服务器假守护进程)
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_daemon(monkeypatch):
    import http.server
    import threading

    calls = []

    class _H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"running": True, "version": "v9.9",
                               "extension_connected": True}).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            calls.append(json.loads(self.rfile.read(n)))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "echo": True}).encode())

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(wb, "DAEMON", f"http://127.0.0.1:{srv.server_port}")
    yield calls
    srv.shutdown()


def test_daemon_status_and_call(fake_daemon):
    st = wb.daemon_status()
    assert st and st["extension_connected"] is True
    out = wb.call("navigate", {"url": "https://x"}, session="s1")
    assert out["success"] is True
    assert fake_daemon[-1] == {"action": "navigate",
                               "args": {"url": "https://x"}, "session": "s1"}


def test_call_unreachable_honest_error(monkeypatch):
    monkeypatch.setattr(wb, "DAEMON", "http://127.0.0.1:1")     # 必然拒连
    monkeypatch.setattr(wb, "start_daemon", lambda: False)
    out = wb.call("snapshot")
    assert out["success"] is False and "不可达" in out["error"]


# ---------------------------------------------------------------------------
# agent 工具并入
# ---------------------------------------------------------------------------

def test_merge_tools_when_binary_present(monkeypatch, fake_daemon):
    monkeypatch.setattr(wb, "binary_installed", lambda: True)
    tools: dict = {}
    wb.merge_webbridge_tools(tools)
    assert "web__navigate" in tools and "web__snapshot" in tools
    assert tools["web__navigate"]["side_effect"] is True
    out = json.loads(tools["web__navigate"]["run"]({"url": "https://x"}))
    assert out["success"] is True
    assert fake_daemon[-1]["session"] == wb.DEFAULT_SESSION   # 默认会话名


def test_merge_tools_absent_without_binary(monkeypatch):
    monkeypatch.setattr(wb, "binary_installed", lambda: False)
    tools: dict = {}
    wb.merge_webbridge_tools(tools)
    assert not tools


def test_search_plan_prefers_webbridge():
    from psyclaw.psych.litplan import build_search_plan, render_search_plan_md
    md = render_search_plan_md(build_search_plan("x"))
    assert "Kimi WebBridge(首选" in md and "psyclaw webbridge install" in md
    assert "web__navigate" in md
