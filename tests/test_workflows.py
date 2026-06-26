"""Workflow 引擎 + 步骤 + 注册表 测试。

引擎用 mock 步骤端到端验证(门禁 fail-closed / 步骤跑 / artifact 记录 / 总验收 /
可选步骤出错跳过);screen_papers 子功能与 workflow_verdict 纯函数单测。
不触网络/真实 provider(auto 模式 + mock 步骤)。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from psyclaw.workflows.engine import (  # noqa: E402
    Step, run_workflow, workflow_verdict,
)
from psyclaw.workflows.registry import (  # noqa: E402
    WORKFLOWS, COMMAND_TO_WORKFLOW, get_workflow,
)
from psyclaw.workflows.steps import screen_papers  # noqa: E402


# --- screen_papers 子功能 --------------------------------------------------

def test_screen_keeps_relevant_drops_irrelevant():
    papers = [
        {"title": "mindfulness reduces anxiety in students",
         "abstract": "a mindfulness intervention lowered anxiety"},
        {"title": "cooking recipes for beginners",
         "abstract": "how to make pasta and bread"},
    ]
    res = screen_papers(papers, "mindfulness anxiety intervention")
    assert res["counts"]["screened"] == 2
    assert res["counts"]["included"] == 1
    assert res["counts"]["excluded"] == 1
    titles = [p["title"] for p in res["included"]]
    assert any("mindfulness" in t for t in titles)


def test_screen_degrades_when_almost_all_excluded():
    # 主题与题录完全跨语言/无重叠 → 不假装筛选,全部纳入待人工复核
    papers = [{"title": f"unrelated english paper {i}", "abstract": "foo bar"}
              for i in range(8)]
    res = screen_papers(papers, "中文主题完全不相关的术语")
    assert res["counts"]["included"] == 8
    assert res["counts"]["excluded"] == 0
    assert "待人工复核" in res["method"]


def test_screen_empty():
    res = screen_papers([], "topic")
    assert res["counts"] == {"screened": 0, "included": 0, "excluded": 0}


# --- workflow_verdict 纯函数 -----------------------------------------------

def _wf(steps):
    return {"id": "t", "name": "t", "steps": steps}


def test_verdict_all_done_passes():
    wf = _wf([Step("a", "A", run=lambda c: {}), Step("b", "B", run=lambda c: {})])
    results = [{"id": "a", "status": "done"}, {"id": "b", "status": "done"}]
    v = workflow_verdict(wf, results, stopped_at=None)
    assert v["overall_passed"] is True
    assert v["missing_required"] == []


def test_verdict_stopped_fails():
    wf = _wf([Step("a", "A", run=lambda c: {}), Step("b", "B", run=lambda c: {})])
    results = [{"id": "a", "status": "done"}]
    v = workflow_verdict(wf, results, stopped_at="b")
    assert v["overall_passed"] is False
    assert "b" in v["missing_required"]


def test_verdict_optional_skip_still_passes():
    wf = _wf([Step("a", "A", run=lambda c: {}),
              Step("b", "B", run=lambda c: {}, optional=True)])
    results = [{"id": "a", "status": "done"}, {"id": "b", "status": "skipped"}]
    v = workflow_verdict(wf, results, stopped_at=None)
    assert v["overall_passed"] is True   # 可选步骤跳过不影响总验收


# --- 引擎端到端(mock 步骤,auto 模式) --------------------------------------

def _writing_step(step_id, fname):
    def run(ctx):
        (ctx.project / "notes" / fname).write_text("x", encoding="utf-8")
        ctx.artifacts[step_id] = f"notes/{fname}"
        return {"ok": True}
    return run


def test_engine_runs_to_completion(tmp_path):
    wf = {
        "id": "mock", "name": "Mock", "research_type": "test",
        "steps": [
            Step("s1", "Step1", run=_writing_step("s1", "s1.md")),
            Step("s2", "Step2", run=_writing_step("s2", "s2.md")),
        ],
    }
    rc = run_workflow(wf, topic="测试主题", project_dir=str(tmp_path), auto=True)
    assert rc == 0
    assert (tmp_path / "notes" / "s1.md").exists()
    assert (tmp_path / "notes" / "s2.md").exists()
    summary = json.loads((tmp_path / "notes" / "workflow_summary.json").read_text(encoding="utf-8"))
    assert summary["verdict"]["overall_passed"] is True
    assert summary["artifacts"]["s1"] == "notes/s1.md"


def test_engine_gate_blocks_fail_closed(tmp_path):
    wf = {
        "id": "blocked", "name": "Blocked", "research_type": "test",
        "steps": [
            Step("gated", "Gated", run=_writing_step("gated", "g.md"),
                 gate=lambda ctx: (False, "门禁未过")),
            Step("after", "After", run=_writing_step("after", "a.md")),
        ],
    }
    rc = run_workflow(wf, topic="x", project_dir=str(tmp_path), auto=True)
    assert rc == 1
    assert not (tmp_path / "notes" / "g.md").exists()   # 被门禁拦下,没跑
    assert not (tmp_path / "notes" / "a.md").exists()   # 后续步骤也不跑
    summary = json.loads((tmp_path / "notes" / "workflow_summary.json").read_text(encoding="utf-8"))
    assert summary["verdict"]["overall_passed"] is False
    assert summary["verdict"]["stopped_at"] == "gated"


def test_engine_optional_step_error_skipped(tmp_path):
    def boom(ctx):
        raise RuntimeError("boom")
    wf = {
        "id": "opt", "name": "Opt", "research_type": "test",
        "steps": [
            Step("ok1", "OK1", run=_writing_step("ok1", "ok1.md")),
            Step("bad", "Bad", run=boom, optional=True),
            Step("ok2", "OK2", run=_writing_step("ok2", "ok2.md")),
        ],
    }
    rc = run_workflow(wf, topic="x", project_dir=str(tmp_path), auto=True)
    assert rc == 0                                       # 可选步骤出错不阻断
    assert (tmp_path / "notes" / "ok2.md").exists()      # 后续步骤照跑


def test_engine_no_topic_no_goal_fails(tmp_path):
    wf = {"id": "m", "name": "M", "steps": [Step("a", "A", run=lambda c: {})]}
    rc = run_workflow(wf, topic=None, project_dir=str(tmp_path), auto=True)
    assert rc == 1                                       # 无主题无 goal → fail-closed


# --- 注册表 ----------------------------------------------------------------

def test_registry_lit_review_present():
    wf = get_workflow("lit-review")
    assert wf is not None
    assert wf["command"] == "review-lit"
    step_ids = [s.id for s in wf["steps"]]
    assert step_ids == ["clarify", "lit_search", "screen", "synthesize", "review"]


def test_registry_command_maps_to_workflow():
    assert COMMAND_TO_WORKFLOW["review-lit"] == "lit-review"
    assert get_workflow("review-lit") is WORKFLOWS["lit-review"]


# --- 元分析子功能:validate_effects / generate_meta_script ------------------

import csv as _csv  # noqa: E402

from psyclaw.workflows.steps_meta import (  # noqa: E402
    generate_meta_script, validate_effects,
)


def _eff_csv(tmp_path, name, rows, header):
    p = tmp_path / name
    with p.open("w", encoding="utf-8", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)
    return str(p)


def test_validate_effects_se(tmp_path):
    p = _eff_csv(tmp_path, "se.csv",
                 [{"study": "A", "d": "0.3", "se": "0.1"},
                  {"study": "B", "d": "0.5", "se": "0.12"}],
                 ["study", "d", "se"])
    info = validate_effects(p)
    assert info["n_studies"] == 2
    assert info["effect_col"] == "d"
    assert info["variance_kind"] == "se"
    assert info["study_col"] == "study"


def test_validate_effects_variance(tmp_path):
    p = _eff_csv(tmp_path, "var.csv",
                 [{"yi": "0.3", "vi": "0.01"}, {"yi": "0.5", "vi": "0.02"}],
                 ["yi", "vi"])
    info = validate_effects(p)
    assert info["variance_kind"] == "variance" and info["effect_col"] == "yi"


def test_validate_effects_ci(tmp_path):
    p = _eff_csv(tmp_path, "ci.csv",
                 [{"g": "0.3", "ci_lower": "0.1", "ci_upper": "0.5"},
                  {"g": "0.5", "ci_lower": "0.2", "ci_upper": "0.8"}],
                 ["g", "ci_lower", "ci_upper"])
    assert validate_effects(p)["variance_kind"] == "ci"


def test_validate_effects_no_effect_col_raises(tmp_path):
    p = _eff_csv(tmp_path, "bad.csv", [{"foo": "1", "se": "0.1"}], ["foo", "se"])
    with pytest.raises(ValueError, match="效应量列"):
        validate_effects(p)


def test_validate_effects_too_few_raises(tmp_path):
    p = _eff_csv(tmp_path, "one.csv", [{"d": "0.3", "se": "0.1"}], ["d", "se"])
    with pytest.raises(ValueError, match="至少需 2"):
        validate_effects(p)


def test_validate_effects_missing_file_raises():
    with pytest.raises(ValueError, match="不存在"):
        validate_effects("nope_does_not_exist.csv")


def test_generate_meta_script_delegates_to_statsmodels(tmp_path):
    p = _eff_csv(tmp_path, "se.csv",
                 [{"study": "A", "d": "0.3", "se": "0.1"},
                  {"study": "B", "d": "0.5", "se": "0.12"}],
                 ["study", "d", "se"])
    info = validate_effects(p)
    script = generate_meta_script(p, info)
    # 统计外移:脚本委托 statsmodels,不在仓内算
    assert "combine_effects" in script
    assert 'method_re="dl"' in script
    assert info["effect_col"] in script
    assert "** 2" in script          # se → 方差 = se²


def test_registry_meta_present():
    wf = get_workflow("meta")
    assert wf is not None and wf["command"] == "meta"
    assert [s.id for s in wf["steps"]] == [
        "clarify", "load_effects", "meta_script", "write", "review"]
