from pathlib import Path

import json

from psyclaw.knowledge_compile import append_claim, compile_materials, promote_compiled_skill, record_validation


def test_compile_materials_builds_replayable_skill_tree(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "Study Notes.md").write_text("# Findings\n\nA claim with evidence.\n", encoding="utf-8")
    (source / "table.csv").write_text("variable,value\nStress,2.1\n", encoding="utf-8")
    out = tmp_path / "compiled"

    result = compile_materials(source, out, skill_name="Study Evidence Skill")

    assert result["ok"] is True
    assert result["total"] == result["converted"] == 2
    assert (out / "INDEX.md").is_file()
    assert (out / "SKILL.md").read_text(encoding="utf-8").startswith("---\nname:")
    manifest = (out / "manifest.json").read_text(encoding="utf-8")
    assert "source_sha256" in manifest and "study-notes" in manifest
    assert len(list((out / "materials").glob("*.md"))) == 2
    assert (out / "claims.json").is_file() and (out / "validation.json").is_file()


def test_compile_materials_rejects_empty_directory(tmp_path: Path):
    result = compile_materials(tmp_path / "empty", tmp_path / "out")
    assert result["ok"] is False and result["status"] == "missing"


def test_promotion_requires_claims_and_all_four_validation_types(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "notes.md").write_text("# Evidence\n\nSupported claim.\n", encoding="utf-8")
    bundle = tmp_path / "bundle"
    compile_materials(source, bundle)
    assert promote_compiled_skill(bundle, reviewer="A")["status"] == "not_ready"
    (bundle / "claims.json").write_text(json.dumps([
        {"claim": "Supported", "source": "notes", "status": "verified"}
    ]), encoding="utf-8")
    for kind in ("known", "forward", "contrast", "boundary"):
        assert record_validation(bundle, kind=kind, passed=True, evidence=[f"tests/{kind}.json"])["ok"]
    promoted = promote_compiled_skill(bundle, reviewer="A")
    assert promoted["ok"] is True and promoted["evidence_level"] == "v3"
    assert "status: promoted" in (bundle / "SKILL.md").read_text(encoding="utf-8")


def test_append_claim_defaults_to_unverified(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "notes.md").write_text("Evidence", encoding="utf-8")
    bundle = tmp_path / "bundle"
    compile_materials(source, bundle)
    result = append_claim(bundle, claim="A claim", source="notes.md")
    assert result["ok"] is True and result["claim"]["status"] == "unverified"
