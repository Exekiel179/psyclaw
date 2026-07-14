"""feat-136:网络镜像回退 + sequential-thinking MCP 内置。"""

from __future__ import annotations

from psyclaw import mirror


def test_force_mirror_env(monkeypatch):
    monkeypatch.setenv("PSYCLAW_FORCE_MIRROR", "1")
    mirror._probe_cache.clear()
    assert mirror.official_reachable() is False
    assert mirror.pip_index_args() == ["--index-url", mirror.PIP_MIRRORS[0]]
    env = mirror.npm_env()
    assert env["npm_config_registry"] == mirror.NPM_MIRROR


def test_official_reachable_uses_default_source(monkeypatch):
    monkeypatch.delenv("PSYCLAW_FORCE_MIRROR", raising=False)
    mirror._probe_cache.clear()
    monkeypatch.setattr(mirror, "official_reachable", lambda timeout=4.0: True)
    assert mirror.pip_index_args() == []                 # 官方可达=默认源
    assert "npm_config_registry" not in mirror.npm_env()


def test_describe_reflects_state(monkeypatch):
    monkeypatch.setattr(mirror, "official_reachable", lambda timeout=4.0: False)
    assert "国内镜像" in mirror.describe()
    monkeypatch.setattr(mirror, "official_reachable", lambda timeout=4.0: True)
    assert "默认源" in mirror.describe()


def test_warm_npx_no_npx(monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "which", lambda x: None)
    r = mirror.warm_npx("@x/y")
    assert r["ok"] is False and "npx" in r["note"]


def test_sequential_thinking_in_registry():
    from psyclaw.mcp.manager import list_mcp_catalog
    st = [e for e in list_mcp_catalog(".") if e["name"] == "sequential-thinking"]
    assert st, "registry.yaml 应含 sequential-thinking 条目"
    assert "server-sequential-thinking" in st[0]["command"]
    assert st[0]["enable_when"] == "detect:npx"          # 开箱即用,无需手配


def test_setup_modules_include_new_capabilities():
    from psyclaw.cli import _SETUP_MODULES
    keys = {m[0] for m in _SETUP_MODULES}
    assert {"sequential-thinking", "mne", "journal"} <= keys
    # 每个板块声明 kind(pip/npx/mcp/skill)供 setup 分派
    kinds = {m[3] for m in _SETUP_MODULES}
    assert kinds <= {"pip", "npx", "mcp", "skill"}
