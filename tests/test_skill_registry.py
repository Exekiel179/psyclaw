"""Agent-facing Skill registry: indexing, classification, retrieval and boundaries."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from psyclaw.skills.registry import (
    build_registry, get_skill, rebuild_registry, search_skills, skill_categories,
)
from psyclaw.toolloop import build_tools


def _git_runner(args, **_kwargs):
    if args[:2] == ["git", "clone"]:
        (Path(args[-1]) / ".git").mkdir(parents=True)
    return subprocess.CompletedProcess(args, 0, "", "")


def _skill(root, name, description, category="domain", extra=""):
    path = root / name
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\ncategory: {category}\ntags: [meta, bias]\n---\n# {name.title()}\n\n{extra}\n",
        encoding="utf-8")


def test_registry_is_deterministic_and_classified(tmp_path, monkeypatch):
    root = tmp_path / ".claude" / "skills"
    root.mkdir(parents=True)
    _skill(root, "meta-bias", "Meta-analysis publication bias funnel plot", "meta")
    monkeypatch.setenv("PSYCLAW_SKILLS_PATH", str(root))
    a = build_registry(str(tmp_path))
    b = build_registry(str(tmp_path))
    assert a == b
    item = next(s for s in a["skills"] if s["name"] == "meta-bias")
    assert item["category"] == "evidence"
    # Untrusted/disabled Skills stay metadata-only: no full-body hash/index.
    assert item["sha256"] == "" and item["evidence_level"] == "unverified"
    assert item["headings"] == []


def test_search_filters_and_no_match(tmp_path, monkeypatch):
    root = tmp_path / ".claude" / "skills"
    root.mkdir(parents=True)
    _skill(root, "meta-bias", "Meta-analysis publication bias", "meta")
    _skill(root, "interview-coding", "Qualitative interview coding", "qualitative")
    monkeypatch.setenv("PSYCLAW_SKILLS_PATH", str(root))
    assert search_skills("发表偏倚", category="meta", project_dir=str(tmp_path)) == []
    assert search_skills("quantum teleportation", project_dir=str(tmp_path)) == []


def test_registry_persists_and_get_is_name_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    rebuilt = rebuild_registry(str(tmp_path), include_external=False)
    assert json.loads((tmp_path / ".psyclaw/skill_registry.json").read_text())["schema"] == 4
    assert rebuilt["count"] > 0
    assert get_skill("sample-size", project_dir=str(tmp_path)) is None
    from psyclaw.skills.packs import install_pack
    assert install_pack("research-design", project_dir=str(tmp_path), runner=_git_runner)["ok"]
    skill = get_skill("sample-size", project_dir=str(tmp_path))
    assert skill and "body" in skill and "样本量" in skill["body"]
    assert get_skill("../../etc/passwd", project_dir=str(tmp_path)) is None


def test_native_skill_tools_are_structured_and_read_only(tmp_path):
    tools = build_tools(str(tmp_path))
    assert {"skill_search", "skill_get", "skill_categories", "skill_duplicates",
            "skill_plugin_catalog", "skill_registry_rebuild"} <= set(tools)
    assert all(tools[n]["side_effect"] is False for n in ("skill_search", "skill_get", "skill_categories"))
    result = json.loads(tools["skill_search"]["run"]({"query": "样本量 功效", "top_k": 2}))
    assert result["ok"] and result["results"]
    missing = json.loads(tools["skill_get"]["run"]({"name": "does-not-exist"}))
    assert missing == {"ok": False, "status": "not_found", "name": "does-not-exist"}


def test_duplicate_sources_are_retained_for_audit(tmp_path, monkeypatch):
    project_root = tmp_path / ".claude" / "skills"
    project_root.mkdir(parents=True)
    _skill(project_root, "same", "Project copy")
    home = tmp_path / "home"
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    global_root = home / ".codex" / "skills"
    _skill(global_root, "same", "Global copy")
    registry = build_registry(str(tmp_path))
    item = next(x for x in registry["skills"] if x["name"] == "same" and x["selected"])
    assert len(registry["duplicates"]) == 1
    assert len(item["duplicate_sources"]) == 2
    # Ambiguous external Skills remain audit-visible but are not routable until
    # the user selects a source and explicitly enables it.
    assert search_skills("same", project_dir=str(tmp_path), registry=registry) == []
    assert len(search_skills("same", project_dir=str(tmp_path), registry=registry,
                             include_duplicates=True, include_disabled=True)) == 2
