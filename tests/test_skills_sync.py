"""内置 skill 上游同步清单与 dry-run。"""

from __future__ import annotations

from psyclaw.skills.loader import list_skills
from psyclaw.skills.sync import list_syncable_skills, sync_skills


def test_ctx2skill_and_opid_are_bundled_skills():
    names = {s["name"] for s in list_skills(include_external=False)}
    assert "ctx2skill" in names
    assert "opid" in names


def test_syncable_skill_manifests_are_discovered():
    syncable = {s.name: s for s in list_syncable_skills()}
    assert syncable["ctx2skill"].repo.endswith("S1s-Z/Ctx2Skill.git")
    assert syncable["ctx2skill"].target.name == "upstream"
    assert syncable["opid"].repo.endswith("jinyangwu/OPID.git")
    assert syncable["opid"].target.name == "upstream"


def test_sync_dry_run_does_not_require_network():
    res = sync_skills(name="ctx2skill", dry_run=True)
    assert len(res) == 1
    assert res[0]["ok"] is True
    assert res[0]["name"] == "ctx2skill"
    assert res[0]["note"] == "dry-run"
