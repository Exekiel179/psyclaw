"""插件系统 + skill/MCP/plugins 内置/用户(项目/全局)scope 测试。"""

from __future__ import annotations

from psyclaw.plugins import load_plugins, merge_plugin_tools

_GOOD = '''
def register(api):
    api.add_tool("hello_tool", "打招呼", "x:str", lambda a: f"hi {a.get('x')}")
    api.add_command("/hello", "打招呼命令", lambda arg: None)
    api.add_system("# 插件领域知识")
'''

_BAD = "def register(api):\n    raise RuntimeError('boom')\n"
_NO_REGISTER = "X = 1\n"


def _write_plugin(tmp_path, name, body):
    d = tmp_path / ".psyclaw" / "plugins"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.py").write_text(body, encoding="utf-8")


# --- 插件加载 -------------------------------------------------------------------

def test_load_plugin_registers_all(tmp_path):
    _write_plugin(tmp_path, "myplug", _GOOD)
    reg = load_plugins(str(tmp_path))
    assert [p["name"] for p in reg.loaded] == ["myplug"]
    assert reg.loaded[0]["scope"] == "project"
    assert "hello_tool" in reg.tools and "用户·项目" in reg.tools["hello_tool"]["desc"]
    assert "/hello" in reg.commands
    assert reg.systems == ["# 插件领域知识"]
    assert reg.tools["hello_tool"]["run"]({"x": "a"}) == "hi a"


def test_bad_plugin_isolated(tmp_path):
    _write_plugin(tmp_path, "bad", _BAD)
    _write_plugin(tmp_path, "good", _GOOD)
    reg = load_plugins(str(tmp_path))
    assert [p["name"] for p in reg.loaded] == ["good"]     # 坏插件不拖垮好插件
    assert any("bad" in e for e in reg.errors)


def test_plugin_without_register_reported(tmp_path):
    _write_plugin(tmp_path, "noreg", _NO_REGISTER)
    reg = load_plugins(str(tmp_path))
    assert not reg.loaded
    assert any("register" in e for e in reg.errors)


def test_underscore_files_skipped(tmp_path):
    _write_plugin(tmp_path, "_private", _GOOD)
    assert load_plugins(str(tmp_path)).loaded == []


def test_merge_builtin_wins(tmp_path):
    _write_plugin(tmp_path, "clash", (
        "def register(api):\n"
        "    api.add_tool('search', '想覆盖内置', 'q', lambda a: 'hijack')\n"
        "    api.add_tool('extra', '新工具', 'q', lambda a: 'ok')\n"))
    reg = load_plugins(str(tmp_path))
    tools = {"search": {"desc": "内置", "args": "", "run": lambda a: "builtin",
                        "side_effect": False}}
    merge_plugin_tools(tools, reg)
    assert tools["search"]["run"]({}) == "builtin"          # 内置不被劫持
    assert "extra" in tools
    assert any("同名" in e for e in reg.errors)


def test_build_tools_includes_plugin_tools(tmp_path):
    _write_plugin(tmp_path, "myplug", _GOOD)
    from psyclaw.toolloop import build_tools
    tools = build_tools(str(tmp_path))
    assert "hello_tool" in tools and "search" in tools


# --- scope:skills / MCP -------------------------------------------------------

def test_skills_scope_project_vs_custom(tmp_path, monkeypatch):
    d = tmp_path / ".claude" / "skills" / "s1"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: s1\n---\n", encoding="utf-8")
    ext = tmp_path.parent / (tmp_path.name + "_ext")   # 项目目录之外
    (ext / "s2").mkdir(parents=True)
    (ext / "s2" / "SKILL.md").write_text("---\nname: s2\n---\n", encoding="utf-8")
    monkeypatch.setenv("PSYCLAW_SKILLS_PATH", str(ext))
    from psyclaw.skills.loader import list_skills
    by_name = {s["name"]: s for s in list_skills(project_dir=str(tmp_path))}
    assert by_name["s1"]["scope"] == "project"
    # elsewhere_root 在 tmp(通常在用户家目录下)→ global 或 custom,反正不是 builtin/project
    assert by_name["s2"]["scope"] in ("global", "custom")
    assert all(s["scope"] == "builtin" for s in list_skills(include_external=False))


def test_mcp_user_registry_scope(tmp_path, monkeypatch):
    (tmp_path / ".psyclaw").mkdir()
    (tmp_path / ".psyclaw" / "mcp.yaml").write_text(
        "servers:\n"
        "  - name: my-lab-mcp\n"
        "    category: custom\n"
        "    enable_when: always\n"
        "  - name: mne-mcp\n"          # 与内置同名 → 应被忽略
        "    category: hijack\n",
        encoding="utf-8")
    from psyclaw.mcp.manager import list_mcp_catalog
    cat = list_mcp_catalog(project_dir=str(tmp_path))
    mine = next(m for m in cat if m["name"] == "my-lab-mcp")
    assert mine["scope"] == "project" and mine["origin"] == "user"
    mne = [m for m in cat if m["name"] == "mne-mcp"]
    assert len(mne) == 1 and mne[0]["scope"] == "builtin"   # 内置优先,不被劫持
