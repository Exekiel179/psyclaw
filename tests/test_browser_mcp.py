"""feat-107:浏览器 MCP 接入——psyclaw 亲自驱动浏览器执行路线 B。

浏览器与统计同一铁律:能力外移到 MCP,仓内零浏览器代码。psyclaw 只是
把标准 MCP 服务器(chrome-devtools-mcp)注册进目录,agent 循环自动并入其工具。
"""

from __future__ import annotations

import shutil

import pytest

from psyclaw.mcp.manager import health_check, list_mcp_catalog


def _browser_entry():
    for e in list_mcp_catalog("."):
        if e.get("name") == "browser":
            return e
    return None


def test_browser_entry_registered():
    e = _browser_entry()
    assert e is not None, "registry.yaml 应含 browser 条目"
    assert "chrome-devtools-mcp" in e.get("command", "")
    assert e.get("enable_when") == "detect:npx"
    assert e.get("category") == "literature"


@pytest.mark.skipif(shutil.which("npx") is None, reason="本机无 npx")
def test_browser_health_ok_with_npx():
    e = _browser_entry()
    h = health_check(e)
    assert h["ok"] is True


def test_browser_tools_merge_into_agent_toolset(monkeypatch):
    """catalog 里 browser 健康时,其工具以 mcp__browser__ 前缀并入 agent 工具集,
    side_effect=True 走审批(外部进程,fail-closed)。用假客户端,不真起 npx。"""
    from psyclaw.mcp import agent_tools as AT

    class _FakeClient:
        def list_tools(self):
            return [{"name": "navigate_page", "description": "打开页面",
                     "inputSchema": {"properties": {"url": {"type": "string"}}}},
                    {"name": "take_snapshot", "description": "页面快照",
                     "inputSchema": {}}]

        def call_tool(self, name, args):
            return f"called:{name}"

    monkeypatch.setattr(AT, "_get_client", lambda cmd: _FakeClient())
    monkeypatch.setattr(
        "psyclaw.mcp.manager.list_mcp_catalog_with_health",
        lambda project_dir=".": [{
            "name": "browser", "command": "npx -y chrome-devtools-mcp@latest",
            "enabled": True, "health": {"ok": True},
        }])
    tools: dict = {}
    AT.merge_mcp_tools(tools)
    assert "mcp__browser__navigate_page" in tools
    assert tools["mcp__browser__navigate_page"]["side_effect"] is True
    assert tools["mcp__browser__navigate_page"]["run"]({"url": "x"}) \
        == "called:navigate_page"


def test_adapt_appends_executable_path(monkeypatch):
    """无 Chrome 有 Edge/Arc 时自动补 --executablePath(python→sys.executable 同一先例)。"""
    from psyclaw.mcp import manager as M
    monkeypatch.setattr(M, "detect_chromium_executable", lambda: "/App/Edge")
    e = {"name": "browser", "command": "npx -y chrome-devtools-mcp@latest"}
    M._adapt_browser_command(e)
    assert e["command"].endswith('--executablePath "/App/Edge"')


def test_adapt_respects_user_custom_and_absence(monkeypatch):
    from psyclaw.mcp import manager as M
    custom = {"name": "browser",
              "command": 'npx -y chrome-devtools-mcp@latest --executablePath "/x"'}
    M._adapt_browser_command(custom)
    assert custom["command"].count("--executablePath") == 1   # 用户自定义不动
    monkeypatch.setattr(M, "detect_chromium_executable", lambda: None)
    plain = {"name": "browser", "command": "npx -y chrome-devtools-mcp@latest"}
    M._adapt_browser_command(plain)
    assert plain["command"] == "npx -y chrome-devtools-mcp@latest"  # 找不到留原样
    other = {"name": "pystat", "command": "python -m x"}
    M._adapt_browser_command(other)
    assert other["command"] == "python -m x"                  # 只动 browser 条目


def test_search_plan_mentions_psyclaw_self_drive():
    """检索计划路线 B 首选 psyclaw 亲自执行(/agent on + mcp__browser__*)。"""
    from psyclaw.psych.litplan import build_search_plan, render_search_plan_md
    md = render_search_plan_md(build_search_plan("x"))
    assert "psyclaw 可亲自执行" in md
    assert "/agent on" in md and "mcp__browser__" in md
