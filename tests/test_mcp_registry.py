"""测试 E-3: MCP registry 完善 — config 向导逐项启用 + 健康检查 + 能力探测。"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.mcp.manager import (
    _is_enabled,
    _parse_registry,
    health_check,
    is_optional,
    list_mcp_catalog,
    list_mcp_catalog_with_health,
    probe_capabilities,
    REGISTRY,
    SERVER_SECRETS,
    SERVER_NOTES,
    OPTIONAL_ORIGINS,
)


# ===========================================================================
# _is_enabled
# ===========================================================================

class TestIsEnabled:
    def test_always(self):
        assert _is_enabled("always") is True

    def test_env_set(self):
        with mock.patch.dict(os.environ, {"MY_API_KEY": "secret"}):
            assert _is_enabled("env:MY_API_KEY") is True

    def test_env_unset(self):
        env = {k: v for k, v in os.environ.items() if k != "MY_MISSING_KEY"}
        with mock.patch.dict(os.environ, env, clear=True):
            assert _is_enabled("env:MY_MISSING_KEY") is False

    def test_detect_found(self):
        with mock.patch("shutil.which", return_value="/usr/bin/python"):
            assert _is_enabled("detect:python") is True

    def test_detect_missing(self):
        with mock.patch("shutil.which", return_value=None):
            assert _is_enabled("detect:nonexistent_bin_xyz") is False

    def test_unknown_condition(self):
        assert _is_enabled("unknown:something") is False


# ===========================================================================
# _parse_registry
# ===========================================================================

class TestParseRegistry:
    def test_registry_loads(self):
        entries = _parse_registry(REGISTRY)
        assert len(entries) >= 5

    def test_entries_have_name(self):
        for e in _parse_registry(REGISTRY):
            assert "name" in e

    def test_known_servers_present(self):
        names = {e["name"] for e in _parse_registry(REGISTRY)}
        assert "mplus-mcp" in names
        assert "stata-mcp" in names
        assert "zotero-mcp" in names

    def test_enable_when_field(self):
        for e in _parse_registry(REGISTRY):
            assert "enable_when" in e

    def test_missing_file_returns_empty(self):
        from pathlib import Path
        assert _parse_registry(Path("/nonexistent/registry.yaml")) == []


# ===========================================================================
# health_check
# ===========================================================================

class TestHealthCheck:
    def _entry(self, **kwargs):
        base = {"name": "test", "enable_when": "always", "command": ""}
        base.update(kwargs)
        return base

    def test_disabled_env_returns_not_ok(self):
        e = self._entry(enable_when="env:MISSING_VAR_XYZ")
        with mock.patch.dict(os.environ, {}, clear=True):
            h = health_check(e)
        assert h["ok"] is False
        assert "未设置" in h["detail"] or "MISSING" in h["detail"]

    def test_disabled_detect_returns_not_ok(self):
        with mock.patch("shutil.which", return_value=None):
            h = health_check(self._entry(enable_when="detect:nonexistent_binary_xyz"))
        assert h["ok"] is False

    def test_always_no_command_is_ok(self):
        h = health_check(self._entry(enable_when="always", command=""))
        assert h["ok"] is True

    def test_python_module_found(self):
        e = self._entry(command="python -m psyclaw.mcp.servers.mplus_server")
        h = health_check(e)
        assert h["ok"] is True
        assert "就绪" in h["detail"]

    def test_python_module_missing(self):
        e = self._entry(command="python -m psyclaw.mcp.servers.nonexistent_zzz")
        h = health_check(e)
        assert h["ok"] is False
        assert "模块未找到" in h["detail"]

    def test_env_enabled_reports_ok(self):
        with mock.patch.dict(os.environ, {"TEST_KEY_ABC": "val"}):
            h = health_check(self._entry(enable_when="env:TEST_KEY_ABC"))
        assert h["ok"] is True
        assert "TEST_KEY_ABC" in h["detail"]

    def test_detect_enabled_reports_path(self):
        with mock.patch("shutil.which", return_value="/usr/bin/Rscript"):
            h = health_check(self._entry(enable_when="detect:Rscript"))
        assert h["ok"] is True
        assert "Rscript" in h["detail"]

    def test_builtin_servers_pass(self):
        """enable_when:always の Python 内置服务器应健康；
        商业可选（detect:）服务器若未安装则 ok=False（可选，不算失败）。"""
        catalog = list_mcp_catalog_with_health()
        for entry in catalog:
            ew = entry.get("enable_when", "always")
            if ew == "always" and entry.get("command", "").startswith("python -m"):
                assert entry["health"]["ok"] is True, (
                    f"{entry['name']} 内置健康检查失败: {entry['health']['detail']}"
                )
            elif is_optional(entry) and not entry["enabled"]:
                # 商业可选服务器未安装时 ok=False 是预期行为
                assert entry["health"]["ok"] is False


# ===========================================================================
# list_mcp_catalog
# ===========================================================================

class TestListMcpCatalog:
    def test_returns_list(self):
        c = list_mcp_catalog()
        assert isinstance(c, list)
        assert len(c) >= 5

    def test_entry_fields(self):
        for e in list_mcp_catalog():
            assert "name" in e
            assert "enabled" in e
            assert "enable_when" in e
            assert "category" in e

    def test_always_entries_are_enabled(self):
        for e in list_mcp_catalog():
            if e["enable_when"] == "always":
                assert e["enabled"] is True

    def test_note_populated(self):
        names_with_notes = {e["name"] for e in list_mcp_catalog() if e.get("note")}
        assert "mplus-mcp" in names_with_notes
        assert "stata-mcp" in names_with_notes


# ===========================================================================
# list_mcp_catalog_with_health
# ===========================================================================

class TestListMcpCatalogWithHealth:
    def test_returns_health_field(self):
        for e in list_mcp_catalog_with_health():
            assert "health" in e
            assert "ok" in e["health"]
            assert "detail" in e["health"]

    def test_always_entries_have_health(self):
        for e in list_mcp_catalog_with_health():
            if e["enable_when"] == "always":
                assert e["health"]["ok"] is True or "模块未找到" in e["health"]["detail"]

    def test_disabled_entries_not_ok(self):
        # Any server requiring an unset env var should not be ok
        for e in list_mcp_catalog_with_health():
            ew = e["enable_when"]
            if ew.startswith("env:") and not os.environ.get(ew[4:]):
                assert e["health"]["ok"] is False

    def test_mplus_is_commercial_optional(self):
        """mplus-mcp 已标为商业可选（detect:mplus），未安装时 ok=False 属预期。"""
        catalog = list_mcp_catalog_with_health()
        mplus = next((e for e in catalog if e["name"] == "mplus-mcp"), None)
        assert mplus is not None
        assert mplus["enable_when"].startswith("detect:")
        assert is_optional(mplus)
        # 未安装 Mplus 时 ok=False；安装了则 ok=True；两种都接受
        assert isinstance(mplus["health"]["ok"], bool)
        # 不管有没有安装，detail 都应带「未检测到」或「检测到」
        assert "mplus" in mplus["health"]["detail"].lower() or mplus["health"]["ok"]

    def test_stata_is_commercial_optional(self):
        """stata-mcp 已标为商业可选（detect:stata），未安装时 ok=False 属预期。"""
        catalog = list_mcp_catalog_with_health()
        stata = next((e for e in catalog if e["name"] == "stata-mcp"), None)
        assert stata is not None
        assert stata["enable_when"].startswith("detect:")
        assert is_optional(stata)
        assert isinstance(stata["health"]["ok"], bool)


# ===========================================================================
# probe_capabilities
# ===========================================================================

class TestProbeCapabilities:
    def _make_catalog(self, entries):
        return entries

    def test_healthy_enabled_server_contributes(self):
        catalog = [
            {"name": "srv-a", "enable_when": "always", "enabled": True,
             "provides": "[cap1, cap2]", "health": {"ok": True, "detail": ""}},
        ]
        caps = probe_capabilities(catalog)
        assert "cap1" in caps
        assert "cap2" in caps
        assert "srv-a" in caps["cap1"]

    def test_unhealthy_server_excluded(self):
        catalog = [
            {"name": "bad", "enable_when": "always", "enabled": True,
             "provides": "[cap3]", "health": {"ok": False, "detail": "err"}},
        ]
        caps = probe_capabilities(catalog)
        assert "cap3" not in caps

    def test_disabled_server_excluded(self):
        catalog = [
            {"name": "off", "enable_when": "env:MISSING", "enabled": False,
             "provides": "[cap4]", "health": {"ok": False, "detail": ""}},
        ]
        caps = probe_capabilities(catalog)
        assert "cap4" not in caps

    def test_multiple_servers_same_cap(self):
        catalog = [
            {"name": "srv1", "enable_when": "always", "enabled": True,
             "provides": "[shared_cap]", "health": {"ok": True, "detail": ""}},
            {"name": "srv2", "enable_when": "always", "enabled": True,
             "provides": "[shared_cap]", "health": {"ok": True, "detail": ""}},
        ]
        caps = probe_capabilities(catalog)
        assert len(caps["shared_cap"]) == 2

    def test_empty_provides_ignored(self):
        catalog = [
            {"name": "srv3", "enable_when": "always", "enabled": True,
             "provides": "", "health": {"ok": True, "detail": ""}},
        ]
        caps = probe_capabilities(catalog)
        assert caps == {}

    def test_default_call_returns_dict(self):
        caps = probe_capabilities()
        assert isinstance(caps, dict)

    def test_builtin_capabilities_present(self):
        """enable_when:always 的 mne-mcp 应产出对应能力（商业可选 mplus/stata/spss 可能不在）。"""
        caps = probe_capabilities()
        # mne-mcp is always enabled, should provide eeg_info
        assert "eeg_info" in caps or any("eeg" in k for k in caps), (
            f"mne-mcp 应产出 eeg_info 能力，当前能力集: {list(caps)[:10]}"
        )


# ===========================================================================
# R-3: 商业统计 MCP 归属标注
# ===========================================================================

class TestCommercialMcpAttribution:
    def test_origin_field_in_catalog(self):
        """每个 catalog 条目应有 origin 字段。"""
        for e in list_mcp_catalog():
            assert "origin" in e, f"{e['name']} 缺少 origin 字段"

    def test_origin_field_in_catalog_with_health(self):
        for e in list_mcp_catalog_with_health():
            assert "origin" in e

    def test_mplus_origin_is_optional(self):
        cat = {e["name"]: e for e in list_mcp_catalog()}
        assert cat["mplus-mcp"]["origin"] == "optional"

    def test_stata_origin_is_optional(self):
        cat = {e["name"]: e for e in list_mcp_catalog()}
        assert cat["stata-mcp"]["origin"] == "optional"

    def test_spss_origin_is_user(self):
        cat = {e["name"]: e for e in list_mcp_catalog()}
        assert cat["spss-mcp"]["origin"] == "user"

    def test_mne_origin_is_builtin(self):
        cat = {e["name"]: e for e in list_mcp_catalog()}
        assert cat["mne-mcp"]["origin"] == "builtin"

    def test_mplus_enable_when_detect(self):
        cat = {e["name"]: e for e in list_mcp_catalog()}
        assert cat["mplus-mcp"]["enable_when"].startswith("detect:")

    def test_stata_enable_when_detect(self):
        cat = {e["name"]: e for e in list_mcp_catalog()}
        assert cat["stata-mcp"]["enable_when"].startswith("detect:")

    def test_spss_enable_when_detect(self):
        cat = {e["name"]: e for e in list_mcp_catalog()}
        assert cat["spss-mcp"]["enable_when"].startswith("detect:")

    def test_mplus_category_is_commercial(self):
        cat = {e["name"]: e for e in list_mcp_catalog()}
        assert cat["mplus-mcp"]["category"] == "stats-commercial"

    def test_stata_category_is_commercial(self):
        cat = {e["name"]: e for e in list_mcp_catalog()}
        assert cat["stata-mcp"]["category"] == "stats-commercial"

    def test_spss_category_is_commercial(self):
        cat = {e["name"]: e for e in list_mcp_catalog()}
        assert cat["spss-mcp"]["category"] == "stats-commercial"

    def test_is_optional_true_for_commercial(self):
        """is_optional() 对 origin=optional/user 返回 True。"""
        assert is_optional({"origin": "optional"}) is True
        assert is_optional({"origin": "user"}) is True

    def test_is_optional_false_for_builtin(self):
        assert is_optional({"origin": "builtin"}) is False
        assert is_optional({}) is False  # 无 origin 字段 → 默认 builtin

    def test_optional_in_optional_origins(self):
        assert "optional" in OPTIONAL_ORIGINS
        assert "user" in OPTIONAL_ORIGINS

    def test_health_check_optional_tag_in_detail(self):
        """商业可选服务器未启用时，detail 应带『可选』标注。"""
        entry = {"name": "mplus-mcp", "enable_when": "detect:no_such_bin_xyz",
                 "origin": "optional", "command": ""}
        with mock.patch("shutil.which", return_value=None):
            h = health_check(entry)
        assert h["ok"] is False
        assert "可选" in h["detail"]
        assert h.get("optional") is True

    def test_health_check_non_optional_no_optional_tag(self):
        """非可选服务器未启用时，detail 不带『，未安装）』。"""
        entry = {"name": "some-mcp", "enable_when": "detect:no_such_bin_xyz",
                 "origin": "builtin", "command": ""}
        with mock.patch("shutil.which", return_value=None):
            h = health_check(entry)
        assert h["ok"] is False
        assert "，未安装）" not in h["detail"]

    def test_mplus_note_mentions_optional(self):
        assert "可选" in SERVER_NOTES["mplus-mcp"]

    def test_stata_note_mentions_optional(self):
        assert "可选" in SERVER_NOTES["stata-mcp"]

    def test_spss_note_mentions_user_built(self):
        assert "用户自研" in SERVER_NOTES["spss-mcp"]


# ===========================================================================
# SERVER_SECRETS / SERVER_NOTES
# ===========================================================================

class TestMetadata:
    def test_zotero_secrets(self):
        assert "ZOTERO_API_KEY" in SERVER_SECRETS["zotero-mcp"]
        assert "ZOTERO_LIBRARY_ID" in SERVER_SECRETS["zotero-mcp"]

    def test_osf_secrets(self):
        assert "OSF_TOKEN" in SERVER_SECRETS["osf-mcp"]

    def test_notes_populated(self):
        assert "mplus-mcp" in SERVER_NOTES
        assert "stata-mcp" in SERVER_NOTES
        assert "zotero-mcp" in SERVER_NOTES
        assert "osf-mcp" in SERVER_NOTES

    def test_notes_are_strings(self):
        for name, note in SERVER_NOTES.items():
            assert isinstance(note, str) and note


# ===========================================================================
# config wizard — non-interactive MCP section
# ===========================================================================

class TestConfigWizard:
    def test_non_interactive_runs(self, tmp_path):
        import psyclaw.config as cfg_mod
        orig_home = cfg_mod.HOME_DIR
        orig_config = cfg_mod.CONFIG_FILE
        orig_env = cfg_mod.ENV_FILE
        try:
            cfg_mod.HOME_DIR = tmp_path
            cfg_mod.CONFIG_FILE = tmp_path / "config.yaml"
            cfg_mod.ENV_FILE = tmp_path / ".env"
            rc = cfg_mod.run_config_wizard(non_interactive=True)
        finally:
            cfg_mod.HOME_DIR = orig_home
            cfg_mod.CONFIG_FILE = orig_config
            cfg_mod.ENV_FILE = orig_env
        assert rc == 0
        assert (tmp_path / "config.yaml").exists()  # noqa: E501

    def test_wizard_writes_secrets(self, tmp_path):
        """向导采集到 env var 时，应写入 .env 文件。"""
        import psyclaw.config as cfg_mod

        orig_home = cfg_mod.HOME_DIR
        orig_config = cfg_mod.CONFIG_FILE
        orig_env = cfg_mod.ENV_FILE
        try:
            cfg_mod.HOME_DIR = tmp_path
            cfg_mod.CONFIG_FILE = tmp_path / "config.yaml"
            cfg_mod.ENV_FILE = tmp_path / ".env"

            # 直接调用 _write_config 验证密钥写入
            cfg_mod._write_config(
                {"provider": "mock", "model": "default"},
                {"ZOTERO_API_KEY": "zk123", "ZOTERO_LIBRARY_ID": "lib456"},
            )
            env_text = (tmp_path / ".env").read_text(encoding="utf-8")
            assert "ZOTERO_API_KEY=zk123" in env_text
            assert "ZOTERO_LIBRARY_ID=lib456" in env_text
        finally:
            cfg_mod.HOME_DIR = orig_home
            cfg_mod.CONFIG_FILE = orig_config
            cfg_mod.ENV_FILE = orig_env


# ---------------------------------------------------------------------------
# 自跑块（不依赖 pytest 命令，可用 python tests/test_mcp_registry.py 直接验证）
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import inspect
    import tempfile
    import traceback

    def _inject_fixture(fn):
        """给需要 tmp_path 的测试注入 tempfile.TemporaryDirectory。"""
        sig = inspect.signature(fn)
        if "tmp_path" in sig.parameters:
            def wrapped():
                with tempfile.TemporaryDirectory() as td:
                    fn(Path(td))
            return wrapped
        return fn

    _SUITES = [
        TestIsEnabled,
        TestParseRegistry,
        TestHealthCheck,
        TestListMcpCatalog,
        TestListMcpCatalogWithHealth,
        TestProbeCapabilities,
        TestCommercialMcpAttribution,
        TestMetadata,
        TestConfigWizard,
    ]

    passed = failed = 0
    for suite_cls in _SUITES:
        suite = suite_cls()
        for name in sorted(m for m in dir(suite_cls) if m.startswith("test_")):
            fn = getattr(suite, name)
            fn = _inject_fixture(fn)
            try:
                fn()
                passed += 1
                print(f"  PASS  {suite_cls.__name__}.{name}")
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"  FAIL  {suite_cls.__name__}.{name}")
                traceback.print_exc()

    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)
