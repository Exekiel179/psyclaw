"""Kaggle MCP registry, setup, and Agent tool integration."""

from __future__ import annotations

import argparse
from types import SimpleNamespace

from psyclaw.mcp.manager import SERVER_NOTES, list_mcp_catalog


PINNED_REF = "47bb38e53f7041d3a0feee6e20a3573ae6af80fa"


def _kaggle_entry() -> dict:
    return next(entry for entry in list_mcp_catalog(".")
                if entry.get("name") == "kaggle")


def test_kaggle_registry_uses_pinned_external_stdio_server():
    entry = _kaggle_entry()
    command = entry["command"]

    assert entry["category"] == "data"
    assert entry["origin"] == "optional"
    assert entry["enable_when"] == "detect:uvx"
    assert command.startswith("uvx --from git+https://github.com/")
    assert PINNED_REF in command
    assert command.endswith("kaggle-mcp --stdio")
    assert "@latest" not in command


def test_kaggle_registry_exposes_dataset_workflow_tools():
    tools = _kaggle_entry()["tools"]
    for name in ("search_datasets", "dataset_details", "list_dataset_files",
                 "get_dataset_metadata", "download_dataset"):
        assert name in tools
    assert "Kaggle API token" in SERVER_NOTES["kaggle"]


def test_kaggle_tools_merge_lazily_and_require_approval(monkeypatch, tmp_path):
    from psyclaw.mcp import agent_tools as agent_mcp

    entry = _kaggle_entry()
    monkeypatch.setattr(
        "psyclaw.mcp.manager.list_mcp_catalog_with_health",
        lambda project_dir=".", include_runtime=False: [
            {**entry, "enabled": True, "health": {"ok": True}}
        ],
    )
    tools: dict = {}
    agent_mcp.merge_mcp_tools(tools, str(tmp_path))

    search = tools["mcp__kaggle__search_datasets"]
    download = tools["mcp__kaggle__download_dataset"]
    assert search["side_effect"] is True
    assert download["side_effect"] is True
    assert entry["command"] not in agent_mcp._clients


def test_kaggle_setup_uses_argv_and_standard_credentials_file(monkeypatch, capsys):
    import psyclaw.cli as cli

    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    rc = cli.cmd_mcp(argparse.Namespace(setup_name="kaggle", name=None))

    assert rc == 0
    argv, kwargs = calls[0]
    assert argv[:2] == ["uvx", "--from"]
    assert PINNED_REF in argv[2]
    assert argv[-3:] == ["kaggle-mcp", "--setup", "--no-env"]
    assert kwargs == {"check": False}
    assert "~/.kaggle/kaggle.json" in capsys.readouterr().out


def test_kaggle_setup_accepts_new_token_file(monkeypatch, tmp_path, capsys):
    import psyclaw.cli as cli

    source = tmp_path / "kaggle-token.txt"
    source.write_text("KGAT_test\n", encoding="utf-8")
    home = tmp_path / "home"
    monkeypatch.setattr("pathlib.Path.home", lambda: home)

    rc = cli.cmd_mcp(argparse.Namespace(
        setup_name="kaggle", name=None, access_token_file=str(source)))

    assert rc == 0
    target = home / ".kaggle" / "access_token"
    assert target.read_text(encoding="utf-8") == "KGAT_test\n"
    assert "KGAT_test" not in capsys.readouterr().out


def test_setup_modules_offer_kaggle_data():
    from psyclaw.cli import _SETUP_MODULES

    module = next(item for item in _SETUP_MODULES if item[0] == "kaggle")
    assert module[3] == "external-mcp"
