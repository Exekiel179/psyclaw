import json

from psyclaw.academic_orchestrator import orchestrate_academic_task, route_task


def test_route_is_explicit_and_conservative():
    assert route_task("帮我做一个导师知识蒸馏") ["mode"] == "distill"
    assert route_task("检查每条引用的证据", requested="evidence")["mode"] == "evidence"
    assert route_task("随便做点事")["mode"] == "distill"


def test_distill_orchestrator_compiles_and_stages_unverified_claims(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "mentor.md").write_text("# Method\n\nThe mentor values direct evidence and replication.\n",
                                      encoding="utf-8")
    result = orchestrate_academic_task("蒸馏导师方法论", project_dir=tmp_path,
                                      source_dir="source", output_dir="notes/skill")
    assert result["ok"] is True and result["status"] == "staged"
    assert result["executed"][1]["count"] >= 1
    claims = json.loads((tmp_path / "notes/skill/claims.json").read_text(encoding="utf-8"))
    assert claims and all(c["status"] == "unverified" for c in claims)


def test_plan_mode_does_not_write(tmp_path):
    result = orchestrate_academic_task("整理材料并蒸馏", project_dir=tmp_path, execute=False)
    assert result["status"] == "planned"
    assert not (tmp_path / "notes").exists()


def test_evidence_and_handoff_routes_execute_explicit_steps(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "notes.md").write_text("Evidence", encoding="utf-8")
    from psyclaw.knowledge_compile import compile_materials
    compile_materials(source, tmp_path / "bundle")
    evidence = orchestrate_academic_task("核验引用", project_dir=tmp_path, mode="evidence",
                                         output_dir="bundle", claims=[{"claim": "Evidence", "source": "notes.md"}])
    assert evidence["status"] == "staged"
    handoff = orchestrate_academic_task("交接当前任务", project_dir=tmp_path, mode="handoff",
                                        output_dir="HANDOFF.md", handoff_goal="Continue",
                                        next_steps=["Review evidence"])
    assert handoff["status"] == "completed" and (tmp_path / "HANDOFF.md").is_file()


def test_orchestrator_rejects_external_source(tmp_path):
    result = orchestrate_academic_task("蒸馏材料", project_dir=tmp_path,
                                      source_dir="/tmp", output_dir="notes/skill")
    assert result["status"] == "blocked"
