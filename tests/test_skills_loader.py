"""Skill 加载器测试 —— 内置 + 外部(.claude/skills / PSYCLAW_SKILLS_PATH)发现与去重。"""

from __future__ import annotations

from psyclaw.skills import loader


def _write_skill(root, name, desc="desc", category="domain"):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {desc}\ncategory: {category}\n---\n正文\n",
        encoding="utf-8")
    return d


def test_bundled_skills_have_source():
    skills = loader.list_skills(include_external=False)
    assert skills, "至少应有内置 skill"
    assert all(s["source"] == "bundled" for s in skills)


def test_legacy_bundled_skill_hidden_by_default():
    visible = {s["name"] for s in loader.list_skills(include_external=False)}
    assert "ars" not in visible

    all_bundled = {s["name"] for s in loader.list_skills(
        include_external=False, include_legacy=True)}
    assert "ars" in all_bundled


def test_discovers_project_claude_skills(tmp_path):
    _write_skill(tmp_path / ".claude" / "skills", "forge-genomics",
                 desc="Genomics analysis", category="bioinformatics")
    skills = loader.list_skills(project_dir=str(tmp_path))
    hit = [s for s in skills if s["name"] == "forge-genomics"]
    assert hit and ".claude" in hit[0]["source"]
    assert hit[0]["category"] == "bioinformatics"


def test_discovers_via_env_path(tmp_path, monkeypatch):
    root = tmp_path / "myforge"
    _write_skill(root, "af-drug-discovery", desc="Cheminformatics")
    monkeypatch.setenv("PSYCLAW_SKILLS_PATH", str(root))
    names = {s["name"] for s in loader.list_skills(project_dir=str(tmp_path))}
    assert "af-drug-discovery" in names


def test_discovers_one_level_category_nesting(tmp_path):
    # AcademicForge 常按学科分组:.claude/skills/<domain>/<skill>/SKILL.md
    _write_skill(tmp_path / ".claude" / "skills" / "clinical", "trial-design")
    names = {s["name"] for s in loader.list_skills(project_dir=str(tmp_path))}
    assert "trial-design" in names


def test_include_external_false_skips_external(tmp_path):
    _write_skill(tmp_path / ".claude" / "skills", "should-not-appear")
    skills = loader.list_skills(project_dir=str(tmp_path), include_external=False)
    assert all(s["name"] != "should-not-appear" for s in skills)


def test_dedup_bundled_wins(tmp_path, monkeypatch):
    # 外部放一个与内置同名的 skill;去重后应保留内置(source=bundled)。
    bundled = loader.list_skills(include_external=False)
    dup = bundled[0]["name"]
    root = tmp_path / "ext"
    _write_skill(root, dup, desc="external override")
    monkeypatch.setenv("PSYCLAW_SKILLS_PATH", str(root))
    got = [s for s in loader.list_skills(project_dir=str(tmp_path)) if s["name"] == dup]
    assert len(got) == 1 and got[0]["source"] == "bundled"


def test_bad_utf8_skill_does_not_crash(tmp_path, monkeypatch):
    # 第三方技能包含非法 UTF-8 时,不能炸掉整份 skills 列表(psyclaw skills / --for / setup)。
    root = tmp_path / "ext"
    good = root / "good"
    good.mkdir(parents=True)
    (good / "SKILL.md").write_text("---\nname: good-skill\n---\n正文\n", encoding="utf-8")
    bad = root / "bad"
    bad.mkdir()
    (bad / "SKILL.md").write_bytes(b"---\nname: bad\xff\xfe skill\n---\n")
    monkeypatch.setenv("PSYCLAW_SKILLS_PATH", str(root))
    names = {s["name"] for s in loader.list_skills(project_dir=str(tmp_path))}  # 不抛异常
    assert "good-skill" in names


def test_external_roots_only_existing(tmp_path):
    (tmp_path / ".claude" / "skills").mkdir(parents=True)
    roots = loader.external_skill_roots(str(tmp_path))
    assert any(".claude" in str(r) for r in roots)
    assert all(r.is_dir() for r in roots)
