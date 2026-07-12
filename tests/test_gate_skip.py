"""前置检查跳过测试 —— engine skip_gates(留痕+探索性标注)+ auto-loop skip_clarify。"""

from __future__ import annotations

import json

from psyclaw.autoloop import discover_backlog
from psyclaw.workflows.engine import Step, run_workflow


def _wf():
    return {
        "id": "t-wf", "name": "测试流程", "research_type": "test",
        "steps": [
            Step(id="s1", title="前置检查未通过的步骤",
                 run=lambda ctx: {"ok": True},
                 gate=lambda ctx: (False, "澄清未完成")),
            Step(id="s2", title="普通步骤", run=lambda ctx: {}),
        ],
    }


def test_default_still_fail_closed(tmp_path):
    rc = run_workflow(_wf(), topic="t", project_dir=str(tmp_path), auto=True)
    assert rc == 1                                   # 默认行为不变:流程暂停
    summary = json.loads((tmp_path / "notes" / "workflow_summary.json")
                         .read_text(encoding="utf-8"))
    assert summary["verdict"]["overall_passed"] is False
    assert "gates_skipped" not in summary


def test_skip_gates_runs_and_leaves_trail(tmp_path):
    rc = run_workflow(_wf(), topic="t", project_dir=str(tmp_path), auto=True,
                      skip_gates=True)
    assert rc == 0                                   # 用户要求跳过 → 跑通
    summary = json.loads((tmp_path / "notes" / "workflow_summary.json")
                         .read_text(encoding="utf-8"))
    assert summary["verdict"]["overall_passed"] is True
    assert summary["exploratory"] is True            # 产出按探索性对待
    assert summary["gates_skipped"][0]["step"] == "s1"
    trail = (tmp_path / "notes" / "gate_skips.md").read_text(encoding="utf-8")
    assert "澄清未完成" in trail and "探索性" in trail


def test_skip_gates_passing_gate_no_trail(tmp_path):
    wf = _wf()
    wf["steps"][0] = Step(id="s1", title="前置检查通过的步骤",
                          run=lambda ctx: {}, gate=lambda ctx: (True, "ok"))
    run_workflow(wf, topic="t", project_dir=str(tmp_path), auto=True, skip_gates=True)
    assert not (tmp_path / "notes" / "gate_skips.md").exists()   # 没跳过就不留痕


def test_discover_backlog_skip_clarify(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "goal.md").write_text("正念与焦虑", encoding="utf-8")   # 有目标、无澄清卡
    default = discover_backlog(str(tmp_path))
    assert default and default[0].get("blocker") is True            # 默认:clarify blocker
    skipped = discover_backlog(str(tmp_path), skip_clarify=True)
    assert skipped and skipped[0]["action"] == "lit-loop"           # 跳过:直接给 lit-loop
    assert not skipped[0].get("blocker")
