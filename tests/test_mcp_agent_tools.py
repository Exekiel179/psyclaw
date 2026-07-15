"""agent 接入 MCP 工具(v0.5 feat-040)——merge_mcp_tools 用假 catalog + 真 echo 服务器。

feat-138:惰性化——有缓存/provides 的服务器 merge 时不起子进程,首次真调用才起。
"""
from __future__ import annotations

import json
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
    AT._refreshed.clear()


def test_merge_adds_prefixed_mcp_tools(monkeypatch, tmp_path):
    _fake_catalog(monkeypatch, [_entry()])
    tools = {}
    AT.merge_mcp_tools(tools, str(tmp_path))
    assert "mcp__echo-srv__echo" in tools
    t = tools["mcp__echo-srv__echo"]
    assert t["side_effect"] is True                 # fail-closed
    assert "MCP:echo-srv" in t["desc"]
    assert "text:string" in t["args"]


def test_merged_tool_actually_calls_server(monkeypatch, tmp_path):
    _fake_catalog(monkeypatch, [_entry()])
    tools = {}
    AT.merge_mcp_tools(tools, str(tmp_path))
    out = tools["mcp__echo-srv__echo"]["run"]({"text": "焦虑"})
    assert out == "echo: 焦虑"


def test_skips_disabled_and_unhealthy_and_no_command(monkeypatch, tmp_path):
    _fake_catalog(monkeypatch, [
        _entry(name="a", enabled=False),
        _entry(name="b", health={"ok": False}),
        _entry(name="c", command=""),
    ])
    tools = {}
    AT.merge_mcp_tools(tools, str(tmp_path))
    assert tools == {}


def test_env_flag_disables(monkeypatch, tmp_path):
    monkeypatch.setenv("PSYCLAW_MCP_TOOLS", "0")
    _fake_catalog(monkeypatch, [_entry()])
    tools = {}
    AT.merge_mcp_tools(tools, str(tmp_path))
    assert tools == {}


def test_bad_command_does_not_break(monkeypatch, tmp_path):
    _fake_catalog(monkeypatch, [_entry(name="bad", command="nonexist_bin_xyz --go")])
    tools = {}
    AT.merge_mcp_tools(tools, str(tmp_path))  # 不抛
    assert all(not k.startswith("mcp__bad__") for k in tools)


def test_catalog_exception_is_swallowed(monkeypatch):
    def boom(project_dir="."):
        raise RuntimeError("catalog down")
    monkeypatch.setattr("psyclaw.mcp.manager.list_mcp_catalog_with_health", boom)
    tools = {}
    AT.merge_mcp_tools(tools, ".")            # 不抛
    assert tools == {}


def test_client_cache_reuses_process(monkeypatch, tmp_path):
    _fake_catalog(monkeypatch, [_entry()])
    AT.merge_mcp_tools({}, str(tmp_path))
    AT.merge_mcp_tools({}, str(tmp_path))
    assert len(AT._clients) == 1              # 同 command 复用一个客户端


# ---- feat-138 惰性化:merge 不冷启子进程,首次真调用才起 ----------------------


def test_lazy_registers_from_provides_without_starting(monkeypatch, tmp_path):
    """有 provides 的服务器:merge 只登记工具名,不起子进程(command 坏也不报)。"""
    _fake_catalog(monkeypatch, [
        _entry(name="slow", command="nonexist_bin_xyz --go",
               provides="[echo, boom]")])
    tools = {}
    AT.merge_mcp_tools(tools, str(tmp_path))
    assert "mcp__slow__echo" in tools
    assert "mcp__slow__boom" in tools
    assert tools["mcp__slow__echo"]["side_effect"] is True
    assert "nonexist_bin_xyz --go" not in AT._clients   # 没起任何客户端


def test_lazy_prefers_tools_key_over_provides(monkeypatch, tmp_path):
    """provides 是能力标签不是工具名;registry 写了 tools: 时按真名登记。"""
    _fake_catalog(monkeypatch, [
        _entry(name="pystat", command="nonexist_bin_xyz --go",
               tools="[pystat_describe, pystat_ttest]",
               provides="[pingouin, statsmodels, descriptive]")])
    tools = {}
    AT.merge_mcp_tools(tools, str(tmp_path))
    assert "mcp__pystat__pystat_describe" in tools
    assert "mcp__pystat__pystat_ttest" in tools
    assert "mcp__pystat__pingouin" not in tools      # 能力标签不当工具名
    assert "mcp__pystat__descriptive" not in tools


def test_builtin_registry_lazy_names_are_real(monkeypatch, tmp_path):
    """内置 registry 惰性登记出的 pystat/mne 工具名必须是服务器真名。"""
    monkeypatch.setattr("psyclaw.mcp.agent_tools._load_tool_cache",
                        lambda project_dir: {})
    tools = {}
    AT.merge_mcp_tools(tools, str(tmp_path))
    assert "mcp__pystat__pystat_describe" in tools
    assert "mcp__mne-mcp__mne_info" in tools
    assert "mcp__pystat__pingouin" not in tools


def test_lazy_call_starts_server_and_backfills_cache(monkeypatch, tmp_path):
    """首次真调用才起子进程;调用后全目录回填缓存(不止 provides 列到的)。"""
    _fake_catalog(monkeypatch, [_entry(provides="[echo]")])
    tools = {}
    AT.merge_mcp_tools(tools, str(tmp_path))
    assert _ECHO_CMD not in AT._clients                 # merge 阶段零进程
    out = tools["mcp__echo-srv__echo"]["run"]({"text": "焦虑"})
    assert out == "echo: 焦虑"
    cache = json.loads((tmp_path / ".psyclaw" / "mcp_tools_cache.json")
                       .read_text(encoding="utf-8"))
    names = [t["name"] for t in cache[_ECHO_CMD]]
    assert "echo" in names and "boom" in names


def test_lazy_cache_gives_full_catalog_and_args(monkeypatch, tmp_path):
    """有缓存时按缓存登记(全目录 + args 提示),优先于 provides,且不起进程。"""
    (tmp_path / ".psyclaw").mkdir()
    (tmp_path / ".psyclaw" / "mcp_tools_cache.json").write_text(json.dumps({
        _ECHO_CMD: [
            {"name": "echo", "description": "回声", "args": "text:string"},
            {"name": "extra", "description": "缓存里多出的", "args": ""},
        ]}), encoding="utf-8")
    _fake_catalog(monkeypatch, [_entry(provides="[echo]")])
    tools = {}
    AT.merge_mcp_tools(tools, str(tmp_path))
    assert "mcp__echo-srv__extra" in tools              # 缓存全目录,不止 provides
    assert tools["mcp__echo-srv__echo"]["args"] == "text:string"
    assert "回声" in tools["mcp__echo-srv__echo"]["desc"]
    assert _ECHO_CMD not in AT._clients


def test_lazy_env_off_restores_eager(monkeypatch, tmp_path):
    """PSYCLAW_MCP_LAZY=0 回到 eager:merge 即 list_tools 全目录。"""
    monkeypatch.setenv("PSYCLAW_MCP_LAZY", "0")
    _fake_catalog(monkeypatch, [_entry(provides="[echo]")])
    tools = {}
    AT.merge_mcp_tools(tools, str(tmp_path))
    assert "mcp__echo-srv__boom" in tools               # eager 拿到全目录
    assert tools["mcp__echo-srv__echo"]["run"]({"text": "hi"}) == "echo: hi"


def test_eager_path_backfills_cache(monkeypatch, tmp_path):
    """无 provides 无缓存 → 保持 eager(行为不回归),并写缓存供下次惰性。"""
    _fake_catalog(monkeypatch, [_entry()])
    tools = {}
    AT.merge_mcp_tools(tools, str(tmp_path))
    assert "mcp__echo-srv__echo" in tools               # eager 老路径不回归
    cache = json.loads((tmp_path / ".psyclaw" / "mcp_tools_cache.json")
                       .read_text(encoding="utf-8"))
    assert any(t["name"] == "echo" for t in cache[_ECHO_CMD])
