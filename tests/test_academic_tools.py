import json

from psyclaw.toolloop import build_tools


EXPECTED = {
    "academic_orchestrate",
    "material_convert", "material_compile", "skill_claim_record", "skill_validate",
    "skill_promote", "skill_bundle_status", "session_handoff_write", "figure_compose",
}


def test_academic_tools_are_native_not_cli_wrappers(tmp_path):
    tools = build_tools(str(tmp_path))
    assert EXPECTED <= set(tools)
    assert all(tools[name]["side_effect"] for name in EXPECTED - {"skill_bundle_status"})
    assert tools["skill_bundle_status"]["side_effect"] is False
    assert "compile" not in tools and "convert" not in tools and "handoff" not in tools


def test_agent_can_complete_compile_claim_validate_promote_cycle(tmp_path):
    source = tmp_path / "materials"
    source.mkdir()
    (source / "notes.md").write_text("# Evidence\n\nSupported claim.\n", encoding="utf-8")
    tools = build_tools(str(tmp_path))

    compiled = json.loads(tools["material_compile"]["run"]({
        "source_dir": "materials", "output_dir": "notes/skill", "skill_name": "Agent Skill"
    }))
    assert compiled["ok"] is True
    claim = json.loads(tools["skill_claim_record"]["run"]({
        "bundle": "notes/skill", "claim": "Supported claim", "source": "notes.md",
        "status": "verified", "locator": "paragraph 1"
    }))
    assert claim["ok"] is True
    for kind in ("known", "forward", "contrast", "boundary"):
        checked = json.loads(tools["skill_validate"]["run"]({
            "bundle": "notes/skill", "kind": kind, "passed": True,
            "evidence": [f"tests/{kind}.json"]
        }))
        assert checked["ok"] is True
    promoted = json.loads(tools["skill_promote"]["run"]({
        "bundle": "notes/skill", "reviewer": "test"
    }))
    assert promoted["ok"] is True and promoted["evidence_level"] == "v3"


def test_academic_tools_reject_paths_outside_project(tmp_path):
    tools = build_tools(str(tmp_path))
    result = json.loads(tools["material_compile"]["run"]({
        "source_dir": "../outside", "output_dir": "notes/skill"
    }))
    assert result["ok"] is False and result["status"] == "denied"


def test_academic_tools_return_structured_error_for_bad_payload(tmp_path):
    tools = build_tools(str(tmp_path))
    result = json.loads(tools["skill_claim_record"]["run"]({
        "bundle": "missing", "claim": "", "source": ""
    }))
    assert result["ok"] is False
    assert result["status"] in {"missing", "tool_error"}
