"""agent 接入 MCP 工具(v0.5 feat-040)——merge_mcp_tools 用假 catalog + 真 echo 服务器。"""
from __future__ import annotations

from pathlib import Path

import psyclaw.mcp.agent_tools as AT

_ECHO_CMD = f"python {Path(__file__).with_name('_mcp_echo_server.py')}"


def _fake_catalog(monkeypatch, entries):
    monkeypatch.setattr("psyclaw.mcp.manager.list_mcp_catalog_with_health",
                        lambda project_dir=".": entries)


def _entry(**kw):
    base = {"name": "echo-srv", "command": _ECHO_CMD, "enabled": True,
            "health": {"ok": True}}
    base.update(kw)
    return base


def teardown_function():
    AT._close_all()


def test_merge_adds_prefixed_mcp_tools(monkeypatch):
    _fake_catalog(monkeypatch, [_entry()])
    tools = {}
    AT.merge_mcp_tools(tools, ".")
    assert "mcp__echo-srv__echo" in tools
    t = tools["mcp__echo-srv__echo"]
    assert t["side_effect"] is True                 # fail-closed
    assert "MCP:echo-srv" in t["desc"]
    assert "text:string" in t["args"]


def test_merged_tool_actually_calls_server(monkeypatch):
    _fake_catalog(monkeypatch, [_entry()])
    tools = {}
    AT.merge_mcp_tools(tools, ".")
    out = tools["mcp__echo-srv__echo"]["run"]({"text": "焦虑"})
    assert out == "echo: 焦虑"


def test_skips_disabled_and_unhealthy_and_no_command(monkeypatch):
    _fake_catalog(monkeypatch, [
        _entry(name="a", enabled=False),
        _entry(name="b", health={"ok": False}),
        _entry(name="c", command=""),
    ])
    tools = {}
    AT.merge_mcp_tools(tools, ".")
    assert tools == {}


def test_env_flag_disables(monkeypatch):
    monkeypatch.setenv("PSYCLAW_MCP_TOOLS", "0")
    _fake_catalog(monkeypatch, [_entry()])
    tools = {}
    AT.merge_mcp_tools(tools, ".")
    assert tools == {}


def test_bad_command_does_not_break(monkeypatch):
    _fake_catalog(monkeypatch, [_entry(name="bad", command="nonexist_bin_xyz --go")])
    tools = {}
    AT.merge_mcp_tools(tools, ".")            # 不抛
    assert all(not k.startswith("mcp__bad__") for k in tools)


def test_catalog_exception_is_swallowed(monkeypatch):
    def boom(project_dir="."):
        raise RuntimeError("catalog down")
    monkeypatch.setattr("psyclaw.mcp.manager.list_mcp_catalog_with_health", boom)
    tools = {}
    AT.merge_mcp_tools(tools, ".")            # 不抛
    assert tools == {}


def test_client_cache_reuses_process(monkeypatch):
    _fake_catalog(monkeypatch, [_entry()])
    AT.merge_mcp_tools({}, ".")
    AT.merge_mcp_tools({}, ".")
    assert len(AT._clients) == 1              # 同 command 复用一个客户端
