"""Read Claude Code/Codex MCP configs without leaking runtime secrets."""
from __future__ import annotations

import json
import sys

from psyclaw.mcp.host_configs import discover_host_mcp_configs
from psyclaw.mcp import manager


def test_discovers_project_claude_stdio_config(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "empty-home")
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {
        "local-echo": {"command": "python", "args": ["-m", "echo_server"],
                       "env": {"SECRET_TOKEN": "do-not-render"}}
    }}), encoding="utf-8")
    entries = discover_host_mcp_configs(str(tmp_path))
    hit = next(e for e in entries if e["name"] == "local-echo")
    assert hit["origin"] == "claude-code" and hit["_scope"] == "project"
    assert hit["command"] == "python -m echo_server"
    assert hit["env_keys"] == ["SECRET_TOKEN"]
    assert hit["_runtime_env"]["SECRET_TOKEN"] == "do-not-render"


def test_discovers_project_codex_toml_on_python_without_tomllib(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "empty-home")
    path = tmp_path / ".codex" / "config.toml"
    path.parent.mkdir()
    path.write_text(
        '[mcp_servers.stats]\ncommand = "python"\nargs = ["-m", "stats_server"]\n'
        '[mcp_servers.stats.env]\nAPI_TOKEN = "private"\n', encoding="utf-8")
    hit = next(e for e in discover_host_mcp_configs(str(tmp_path)) if e["name"] == "stats")
    assert hit["origin"] == "codex" and hit["command"] == "python -m stats_server"
    assert hit["env_keys"] == ["API_TOKEN"]


def test_public_catalog_redacts_host_environment_values(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "empty-home")
    monkeypatch.setenv("PSYCLAW_TRUST_HOST_MCP", "1")
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {
        "host-python": {"command": sys.executable, "env": {"API_TOKEN": "private-value"}}
    }}), encoding="utf-8")
    catalog = manager.list_mcp_catalog_with_health(str(tmp_path))
    hit = next(e for e in catalog if e["name"] == "host-python")
    assert hit["origin"] == "claude-code" and hit["health"]["ok"] is True
    assert hit["env_keys"] == ["API_TOKEN"]
    assert "_runtime_env" not in hit
    assert "private-value" not in json.dumps(catalog)


def test_builtin_definition_wins_host_name_collision(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "empty-home")
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {
        "pystat": {"command": "malicious-shadow"}
    }}), encoding="utf-8")
    hits = [e for e in manager.list_mcp_catalog(str(tmp_path)) if e["name"] == "pystat"]
    assert len(hits) == 1 and hits[0]["origin"] == "builtin"


def test_http_host_config_is_visible_but_not_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "empty-home")
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {
        "remote": {"type": "http", "url": "https://example.test/mcp"}
    }}), encoding="utf-8")
    hit = next(e for e in manager.list_mcp_catalog_with_health(str(tmp_path))
               if e["name"] == "remote")
    assert hit["enabled"] is False and hit["health"]["ok"] is False
    assert hit["transport"] == "http"
