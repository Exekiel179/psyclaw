"""System Skill packs and explicit enable/disable state."""
from __future__ import annotations

import json
import argparse
import subprocess
from pathlib import Path

from psyclaw.skills.packs import install_pack, list_packs, sync_pack_catalog, update_pack
from psyclaw.skills.registry import build_registry, search_skills
from psyclaw.skills.state import load_state, set_pack_enabled, set_skill_enabled
from psyclaw.toolloop import build_tools
from psyclaw.psych.method_skills import match_method_skill, skill_procedure


def _git_runner(args, **_kwargs):
    """Offline Git double that creates the checkout expected by pack update."""
    if args[:2] == ["git", "clone"]:
        target = Path(args[-1])
        (target / ".git").mkdir(parents=True)
    return subprocess.CompletedProcess(args, 0, "", "")


def test_core_pack_is_bundled_and_locked(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    packs = {p["id"]: p for p in list_packs(str(tmp_path))}
    assert packs["core"]["installed"] and packs["core"]["enabled"]
    assert install_pack("core", project_dir=str(tmp_path))["status"] == "bundled"
    assert set_pack_enabled("core", False, project_dir=str(tmp_path), locked=True)["status"] == "locked_core"
    assert set_skill_enabled("research-workflow", False, project_dir=str(tmp_path))["status"] == "locked_core"


def test_domain_pack_installs_and_enables_without_network_when_no_sources(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    monkeypatch.setenv("PSYCLAW_SKILL_PACK_HOME", str(home / "packs"))
    result = install_pack("research-design", project_dir=str(tmp_path), runner=_git_runner)
    assert result["ok"] and result["status"] == "installed" and result["enabled"]
    state = json.loads((home / ".psyclaw/skill_state.json").read_text())
    assert "research-design" in state["enabled_packs"]
    assert update_pack("research-design", project_dir=str(tmp_path), runner=_git_runner)["ok"]


def test_domain_skill_requires_pack_and_project_skill_overrides_pack(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    before = build_registry(str(tmp_path), include_external=False)
    sample = next(s for s in before["skills"] if s["name"] == "sample-size")
    assert sample["enabled"] is False and sample["enable_reason"] == "available"

    assert install_pack("research-design", project_dir=str(tmp_path), runner=_git_runner)["ok"]
    enabled = build_registry(str(tmp_path), include_external=False)
    assert next(s for s in enabled["skills"] if s["name"] == "sample-size")["enabled"] is True

    # A project-local single Skill setting wins over the global pack setting.
    assert set_skill_enabled("sample-size", False, project_dir=str(tmp_path), scope="project")["ok"]
    overridden = build_registry(str(tmp_path), include_external=False)
    sample = next(s for s in overridden["skills"] if s["name"] == "sample-size")
    assert sample["enabled"] is False and sample["enable_reason"] == "project_disabled"


def test_disabled_method_skill_cannot_be_routed_or_read(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    assert match_method_skill("样本量", str(tmp_path)) is None
    assert skill_procedure("sample-size", str(tmp_path)) == ""

    assert install_pack("research-design", project_dir=str(tmp_path), runner=_git_runner)["ok"]
    assert match_method_skill("样本量", str(tmp_path))["name"] == "sample-size"
    assert "功效分析" in skill_procedure("sample-size", str(tmp_path))

    assert set_skill_enabled("sample-size", False, project_dir=str(tmp_path), scope="project")["ok"]
    assert match_method_skill("样本量", str(tmp_path)) is None
    assert skill_procedure("sample-size", str(tmp_path)) == ""


def test_external_global_skill_is_available_until_enabled(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    skill = home / ".codex/skills/global-extra"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: global-extra\ndescription: Special global workflow\n---\n# Workflow\n",
        encoding="utf-8")
    registry = build_registry(str(tmp_path))
    item = next(x for x in registry["skills"] if x["name"] == "global-extra")
    assert item["enabled"] is False and item["enable_reason"] == "available"
    assert all(x["name"] != "global-extra" for x in
               search_skills("special global", registry=registry, project_dir=str(tmp_path)))
    assert set_skill_enabled("global-extra", True, project_dir=str(tmp_path))["ok"]
    refreshed = build_registry(str(tmp_path))
    assert search_skills("special global", registry=refreshed, project_dir=str(tmp_path))[0]["name"] == "global-extra"


def test_disabled_skill_registry_does_not_read_full_body(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    path = home / ".codex/skills/untrusted/SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text("---\nname: untrusted\ndescription: Inventory only\n---\nSECRET BODY\n",
                    encoding="utf-8")
    original = Path.read_text

    def deny_disabled_body(self, *args, **kwargs):
        if self.resolve() == path.resolve():
            raise AssertionError("disabled Skill body was read")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", deny_disabled_body)
    registry = build_registry(str(tmp_path))
    skill = next(s for s in registry["skills"] if s["name"] == "untrusted")
    assert skill["enabled"] is False and skill["sha256"] == "" and skill["headings"] == []


def test_pack_and_enable_tools_have_side_effect_flags(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    tools = build_tools(str(tmp_path))
    read_only = {"skill_pack_list"}
    writes = {"skill_pack_install", "skill_pack_update", "skill_pack_enable",
              "skill_pack_disable", "skill_enable", "skill_disable"}
    assert all(tools[name]["side_effect"] is False for name in read_only)
    assert all(tools[name]["side_effect"] is True for name in writes)


def test_cli_requires_source_selection_before_enabling_external_duplicate(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    monkeypatch.chdir(tmp_path)
    for root in (tmp_path / ".claude/skills", home / ".codex/skills"):
        skill = root / "same"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: same\ndescription: Duplicate\n---\n# Duplicate\n",
            encoding="utf-8")
    from psyclaw.cli import cmd_skills
    assert cmd_skills(argparse.Namespace(enable="same", disable=None, scope="global")) == 1


def test_project_root_under_home_is_project_scope(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = home / "Projects" / "study"
    root = project / ".claude" / "skills"
    root.mkdir(parents=True)
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    from psyclaw.skills.loader import _root_scope
    assert _root_scope(root, str(project)) == "project"


def test_pack_install_passes_ref_and_sparse_paths(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    catalog = {"schema": 1, "packs": [{
        "id": "remote-pack", "name": "Remote", "skills": ["one", "two"],
        "sources": [{"url": "https://github.com/example/skills.git", "ref": "v1.2.3",
                     "subdir": "skills", "skills": ["one", "two"]}],
    }]}
    monkeypatch.setattr("psyclaw.skills.packs.load_pack_catalog", lambda: catalog)
    calls = []

    def runner(args, **kwargs):
        calls.append(args)
        return _git_runner(args, **kwargs)

    assert install_pack("remote-pack", project_dir=str(tmp_path), runner=runner)["ok"]
    clone = next(call for call in calls if call[:2] == ["git", "clone"])
    assert "--branch" in clone and "v1.2.3" in clone and "--sparse" in clone
    sparse = next(call for call in calls if "sparse-checkout" in call)
    assert sparse[-2:] == ["skills/one", "skills/two"]

    calls.clear()
    assert update_pack("remote-pack", project_dir=str(tmp_path), runner=runner)["ok"]
    assert ["git", "-C", str(home / ".psyclaw/skill-packs/remote-pack/skills/skills"),
            "fetch", "--depth", "1", "origin", "v1.2.3"] in calls


def test_active_pack_checkout_overrides_shipped_skill(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    assert install_pack("research-design", project_dir=str(tmp_path), runner=_git_runner)["ok"]
    updated = home / ".psyclaw/skill-packs/research-design/skills/psyclaw/skills/sample-size/SKILL.md"
    updated.parent.mkdir(parents=True)
    updated.write_text(
        "---\nname: sample-size\ndescription: Remote updated sample sizing\ncategory: method\n---\n# Remote updated\n\nremote body\n",
        encoding="utf-8")
    from psyclaw.skills.registry import get_skill
    skill = get_skill("sample-size", project_dir=str(tmp_path))
    assert skill and skill["description"] == "Remote updated sample sizing"
    assert "remote body" in skill["body"]


def test_pack_rejects_invalid_scope_before_install(tmp_path):
    called = False

    def runner(*_args, **_kwargs):
        nonlocal called
        called = True
        return _git_runner(*_args, **_kwargs)

    result = install_pack("research-design", project_dir=str(tmp_path), scope="invalid", runner=runner)
    assert result["status"] == "invalid_scope" and called is False


def test_catalog_rejects_malformed_pack_shapes():
    class Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return self.payload

    bad_packs = sync_pack_catalog("https://github.com/catalog.json",
                                  opener=lambda *_a, **_k: Response(b'{"packs":["bad"]}'))
    bad_sources = sync_pack_catalog("https://github.com/catalog.json", opener=lambda *_a, **_k: Response(
        b'{"packs":[{"id":"bad","skills":[],"sources":["bad"]}]}'))
    assert bad_packs["status"] == "invalid_catalog"
    assert bad_sources["status"] == "invalid_catalog"


def test_malformed_state_is_normalised_without_enabling_unknown_values(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    state_path = home / ".psyclaw/skill_state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        '{"enabled_skills":null,"disabled_skills":["valid",42,"BAD"],'
        '"enabled_packs":"bad","source_preferences":[]}', encoding="utf-8")
    state = load_state(str(tmp_path), "global")
    assert state["enabled_skills"] == []
    assert state["disabled_skills"] == ["valid"]
    assert state["enabled_packs"] == [] and state["source_preferences"] == {}
    assert set_skill_enabled("sample-size", True, project_dir=str(tmp_path))["ok"]
