"""chat/run/auto 三种公开模式的路由契约。"""

from __future__ import annotations

import pytest

from psyclaw import modes
from psyclaw.cli import build_parser


@pytest.mark.parametrize(("raw", "expected"), [
    ("analysis", "analysis"), ("analysis-loop", "analysis"),
    ("lit", "literature"), ("lit-loop", "literature"),
    ("qual", "qualitative"), ("research", "research"),
    ("loop", "task"),
])
def test_normalize_run_type_keeps_legacy_aliases(raw, expected):
    assert modes.normalize_run_type(raw) == expected


def test_normalize_run_type_rejects_unknown():
    with pytest.raises(ValueError, match="未知运行类型"):
        modes.normalize_run_type("mystery")


def test_analysis_routes_to_existing_workflow(monkeypatch):
    seen = {}
    monkeypatch.setattr("psyclaw.workflows.get_workflow", lambda wid: {"id": wid})

    def fake_run(wf, **kwargs):
        seen.update(workflow=wf, **kwargs)
        return 7

    monkeypatch.setattr("psyclaw.workflows.run_workflow", fake_run)
    rc = modes.run_mode("analysis", "data/clean/scores.csv", topic="压力研究",
                        auto=True, skip_gates=True)
    assert rc == 7
    assert seen["workflow"]["id"] == "analysis"
    assert seen["seed"] == {"data_csv": "data/clean/scores.csv"}
    assert seen["topic"] == "压力研究"
    assert seen["auto"] is True and seen["skip_gates"] is True


def test_public_run_defaults_to_continuous_and_supports_resume(monkeypatch):
    seen = {}
    monkeypatch.setattr("psyclaw.workflows.get_workflow", lambda wid: {"id": wid})
    monkeypatch.setattr("psyclaw.workflows.run_workflow",
                        lambda wf, **kw: seen.update(kw) or 0)
    assert modes.run_mode("literature", "正念", resume=True) == 0
    assert seen["auto"] is True
    assert seen["resume"] is True


def test_resume_data_workflow_recovers_saved_input(monkeypatch):
    seen = {}
    monkeypatch.setattr("psyclaw.workflows.get_workflow", lambda wid: {"id": wid})
    monkeypatch.setattr("psyclaw.workflows.run_workflow",
                        lambda wf, **kw: seen.update(kw) or 0)
    monkeypatch.setattr("psyclaw.workflows.engine.checkpoint_value",
                        lambda project, workflow, key: "data/clean/saved.csv")
    assert modes.run_mode("analysis", resume=True) == 0
    assert seen["seed"] == {"data_csv": "data/clean/saved.csv"}


def test_only_stable_workflows_are_public_run_types():
    assert modes.RUN_TYPES == ("analysis", "meta", "literature", "qualitative")
    assert {"research", "task"}.isdisjoint(modes.RUN_TYPES)


def test_data_modes_require_target():
    for kind in ("analysis", "meta", "qualitative"):
        with pytest.raises(ValueError, match="需要输入路径"):
            modes.run_mode(kind)


def test_literature_uses_target_as_topic(monkeypatch):
    seen = {}
    monkeypatch.setattr("psyclaw.workflows.get_workflow", lambda wid: {"id": wid})
    monkeypatch.setattr("psyclaw.workflows.run_workflow",
                        lambda wf, **kw: seen.update(workflow=wf, **kw) or 0)
    assert modes.run_mode("literature", "正念与焦虑") == 0
    assert seen["workflow"]["id"] == "lit-review"
    assert seen["topic"] == "正念与焦虑"


def test_research_and_task_reuse_existing_engines(monkeypatch):
    seen = []
    monkeypatch.setattr("psyclaw.pipeline.run_pipeline",
                        lambda **kw: seen.append(("research", kw)) or 3)
    monkeypatch.setattr("psyclaw.loop.run_loop",
                        lambda **kw: seen.append(("task", kw)) or 4)
    assert modes.run_mode("research", "完整研究", revise=True) == 3
    assert modes.run_mode("task", "整理材料", auto=True) == 4
    assert seen[0][1]["topic"] == "完整研究" and seen[0][1]["revise"] is True
    assert seen[1][1]["topic"] == "整理材料" and seen[1][1]["auto"] is True


def test_auto_defaults_to_autonomous_dispatch(monkeypatch):
    seen = {}
    monkeypatch.setattr("psyclaw.autoloop.run_autoloop",
                        lambda **kw: seen.update(kw) or 0)
    assert modes.run_auto(max_iters=2) == 0
    assert seen["auto"] is True and seen["max_iters"] == 2
    modes.run_auto(confirm_each=True)
    assert seen["auto"] is False


def test_cli_registers_three_public_modes_and_legacy_aliases():
    p = build_parser()
    assert p.parse_args(["chat"]).func.__name__ == "cmd_chat"
    run = p.parse_args(["run", "analysis", "data.csv", "--yes"])
    assert run.func.__name__ == "cmd_run" and run.kind == "analysis" and run.yes is True
    run2 = p.parse_args(["run", "analysis", "data.csv", "--confirm-each",
                         "--exploratory", "--resume"])
    assert run2.confirm_each and run2.exploratory and run2.resume
    auto = p.parse_args(["auto", "--confirm-each"])
    assert auto.func.__name__ == "cmd_auto" and auto.confirm_each is True
    # 兼容期内旧脚本仍可解析。
    assert p.parse_args(["analysis-loop", "data.csv"]).func.__name__ == "cmd_analysis"
    assert p.parse_args(["prepare"]).func.__name__ == "cmd_clarify"
    assert p.parse_args(["clarify"]).func.__name__ == "cmd_clarify"


def test_cli_approval_uses_public_vocabulary_with_legacy_value():
    p = build_parser()
    assert p.parse_args(["--approval", "ask", "chat"]).approval == "ask"
    assert p.parse_args(["--approval", "auto", "chat"]).approval == "auto"
    assert p.parse_args(["--approval", "suggest", "chat"]).approval == "suggest"
