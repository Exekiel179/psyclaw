"""Auto-Loop 自主科研回路测试 — 五步控制流的纯函数(确定性,不触网络/provider)。

覆盖:① 感知 discover_backlog + classify_csv · ② 选择 select_next ·
③ 独立验收 verify_result · ④ 状态 load/save/record · ⑤ 决定 decide。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from psyclaw import autoloop  # noqa: E402
from psyclaw.autoloop import (  # noqa: E402
    classify_csv, decide, discover_backlog, load_state, record_iteration,
    save_state, select_next, verify_result,
)
from psyclaw.psych.clarify import SLOTS  # noqa: E402


# --- fixtures --------------------------------------------------------------

def _notes(tmp_path: Path) -> Path:
    n = tmp_path / "notes"
    n.mkdir(parents=True, exist_ok=True)
    return n


def _complete_card(tmp_path: Path) -> None:
    """写一张 17 个研究准备项全 resolved 的清单(通过研究准备检查)。"""
    lines = ["| 研究准备项 | 状态 | 内容 |", "|---|---|---|"]
    for sid, *_ in SLOTS:
        lines.append(f"| {sid} | resolved | 测试内容 |")
    (_notes(tmp_path) / "clarification.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")


def _set_goal(tmp_path: Path, text: str = "正念干预能否降低大学生焦虑") -> None:
    (_notes(tmp_path) / "goal.md").write_text(text + "\n", encoding="utf-8")


def _write_csv(path: Path, header: str, rows: list[str]) -> None:
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


# --- classify_csv ----------------------------------------------------------

def test_classify_effects_table(tmp_path):
    p = tmp_path / "effects.csv"
    _write_csv(p, "study,d,se", ["A,0.3,0.1", "B,0.5,0.12"])
    assert classify_csv(str(p)) == "effects"


def test_classify_data_table(tmp_path):
    p = tmp_path / "data.csv"
    _write_csv(p, "group,score,age", ["ctrl,12,20", "trt,18,21"])
    assert classify_csv(str(p)) == "data"


def test_classify_data_with_d_col_but_no_study_or_var(tmp_path):
    # 含 'd' 列但缺(收紧后的)研究标签/方差来源 → 保守判为普通数据表(不误路由到元分析)
    p = tmp_path / "x.csv"
    _write_csv(p, "id,d,height", ["1,2,170", "2,3,165"])
    assert classify_csv(str(p)) == "data"


def test_classify_ambiguous_generic_cols_are_data(tmp_path):
    # 回归:`id,d,v` / `name,d,se` 这类泛化列名的数据表不得被误判成效应量表
    # (id/name 不再算研究标签,v 不再算方差)——否则会误路由 meta-loop、漏掉 analysis-loop。
    for header in ("id,d,v", "name,d,se", "id,r,se", "name,g,variance"):
        p = tmp_path / f"{header.replace(',', '_')}.csv"
        _write_csv(p, header, ["1,0.2,0.1", "2,0.3,0.1"])
        assert classify_csv(str(p)) == "data", header


def test_classify_effects_needs_explicit_study_label(tmp_path):
    # 明确的研究标签(study/author)+ 效应量 + 方差 → 才算效应量表
    p = tmp_path / "ok.csv"
    _write_csv(p, "author,d,se", ["Smith,0.2,0.1", "Lee,0.4,0.1"])
    assert classify_csv(str(p)) == "effects"


def test_classify_missing_file(tmp_path):
    assert classify_csv(str(tmp_path / "nope.csv")) == "data"


# --- discover_backlog ------------------------------------------------------

def test_discover_empty_project(tmp_path):
    # 无目标、无数据、无转录稿 → 无可发现的研究输入
    assert discover_backlog(str(tmp_path)) == []


def test_discover_goal_yields_lit(tmp_path):
    _complete_card(tmp_path)
    _set_goal(tmp_path)
    bl = discover_backlog(str(tmp_path))
    assert [b["action"] for b in bl] == ["lit-loop"]
    assert bl[0]["blocker"] is False


def test_discover_incomplete_clarify_is_blocker(tmp_path):
    # 有事可做(设了目标)但澄清未完 → 短路成单个 clarify blocker
    _set_goal(tmp_path)  # 不写澄清卡 → 全部 unresolved
    bl = discover_backlog(str(tmp_path))
    assert len(bl) == 1
    assert bl[0]["action"] == "clarify" and bl[0]["blocker"] is True


def test_discover_data_yields_analysis(tmp_path):
    _complete_card(tmp_path)
    _write_csv(tmp_path / "scores.csv", "group,score", ["a,1", "b,2"])
    bl = discover_backlog(str(tmp_path))
    assert any(b["action"] == "analysis-loop" for b in bl)
    item = next(b for b in bl if b["action"] == "analysis-loop")
    assert item["seed"]["data_csv"].endswith("scores.csv")


def test_discover_effects_yields_meta(tmp_path):
    _complete_card(tmp_path)
    _write_csv(tmp_path / "eff.csv", "study,g,se", ["A,.2,.1", "B,.4,.1"])
    bl = discover_backlog(str(tmp_path))
    assert any(b["action"] == "meta-loop" for b in bl)


def test_discover_transcripts_yields_qual(tmp_path):
    _complete_card(tmp_path)
    tdir = tmp_path / "transcripts"
    tdir.mkdir()
    (tdir / "p01.txt").write_text("访谈内容……", encoding="utf-8")
    bl = discover_backlog(str(tmp_path))
    assert any(b["action"] == "qual-loop" for b in bl)


def test_discover_priority_order(tmp_path):
    # lit(P1) 应排在 analysis(P2) 之前
    _complete_card(tmp_path)
    _set_goal(tmp_path)
    _write_csv(tmp_path / "d.csv", "group,score", ["a,1", "b,2"])
    bl = discover_backlog(str(tmp_path))
    assert bl[0]["action"] == "lit-loop"


def test_discover_both_effects_and_data(tmp_path):
    # 效应量表 + 数据表同在 → 两个候选都出现;同为 P2,meta 先于 analysis(稳定排序)
    _complete_card(tmp_path)
    _write_csv(tmp_path / "eff.csv", "study,g,se", ["A,.2,.1", "B,.4,.1"])
    _write_csv(tmp_path / "scores.csv", "group,score", ["a,1", "b,2"])
    actions = [b["action"] for b in discover_backlog(str(tmp_path))]
    assert "meta-loop" in actions and "analysis-loop" in actions
    assert actions.index("meta-loop") < actions.index("analysis-loop")


def test_discover_data_yields_only_analysis_not_meta(tmp_path):
    # 纯数据表不应同时冒出 meta-loop(分类应判为 data)
    _complete_card(tmp_path)
    _write_csv(tmp_path / "scores.csv", "group,score", ["a,1", "b,2"])
    actions = [b["action"] for b in discover_backlog(str(tmp_path))]
    assert "analysis-loop" in actions and "meta-loop" not in actions


def test_discover_filters_done_actions(tmp_path):
    _complete_card(tmp_path)
    _set_goal(tmp_path)
    bl = discover_backlog(str(tmp_path), done_actions=frozenset({"lit-loop"}))
    assert bl == []


def test_discover_filters_existing_artifact(tmp_path):
    # 标志产物已在磁盘 → 该阶段视为已做,不再发现(幂等收敛)
    _complete_card(tmp_path)
    _set_goal(tmp_path)
    (_notes(tmp_path) / "lit_review.md").write_text("已有综述", encoding="utf-8")
    assert discover_backlog(str(tmp_path)) == []


def test_discover_ignores_data_raw(tmp_path):
    # data/raw 受保护:自动发现不读它,放在 raw 的数据不应被发现
    _complete_card(tmp_path)
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True)
    _write_csv(raw / "secret.csv", "group,score", ["a,1", "b,2"])
    assert discover_backlog(str(tmp_path)) == []


# --- select_next -----------------------------------------------------------

def test_select_next_picks_first():
    bl = [{"action": "lit-loop"}, {"action": "meta-loop"}]
    assert select_next(bl)["action"] == "lit-loop"
    assert select_next([]) is None


# --- verify_result(独立验收)------------------------------------------------

def _write_summary(tmp_path: Path, wf: str, passed: bool) -> None:
    (_notes(tmp_path) / "workflow_summary.json").write_text(json.dumps({
        "workflow": wf,
        "verdict": {"overall_passed": passed, "reasons": [] if passed else ["x"]},
    }), encoding="utf-8")


def test_verify_no_summary_fails(tmp_path):
    _notes(tmp_path)
    assert verify_result(str(tmp_path), "lit-loop")["passed"] is False


def test_verify_wrong_workflow_fails(tmp_path):
    # 产物写齐,使"验收对象不符"成为唯一失败因(隔离 workflow-id 守卫)
    _write_summary(tmp_path, "meta", True)
    (_notes(tmp_path) / "lit_review.md").write_text("综述", encoding="utf-8")
    res = verify_result(str(tmp_path), "lit-loop")  # 期望 lit-review,落盘 meta
    assert res["passed"] is False
    assert any("验收对象不符" in r for r in res["reasons"])


def test_verify_passed_with_artifact(tmp_path):
    _write_summary(tmp_path, "lit-review", True)
    (_notes(tmp_path) / "lit_review.md").write_text("综述", encoding="utf-8")
    assert verify_result(str(tmp_path), "lit-loop")["passed"] is True


def test_verify_passed_but_artifact_missing_fails(tmp_path):
    # 总验收说过了,但标志产物不在磁盘 → 独立验收判不过(只信仓库真实存在的东西)
    _write_summary(tmp_path, "lit-review", True)
    res = verify_result(str(tmp_path), "lit-loop")
    assert res["passed"] is False
    assert any("产物缺失" in r for r in res["reasons"])


# --- decide ----------------------------------------------------------------

def test_decide_max_iters():
    d, why = decide({"iteration": 6}, [{"action": "lit-loop"}], max_iters=6)
    assert d == "stop" and "上限" in why


def test_decide_empty_backlog():
    d, why = decide({"iteration": 0}, [], max_iters=6)
    assert d == "stop" and "backlog" in why


def test_decide_blocker_stops():
    d, why = decide({"iteration": 0}, [{"blocker": True, "reason": "x"}], max_iters=6)
    assert d == "stop" and "前置检查" in why


def test_decide_max_iters_precedes_blocker():
    # 同时撞上限且 backlog 顶是 blocker → 按 max_iters 停(理由是上限,不是前置检查)
    d, why = decide({"iteration": 6}, [{"blocker": True, "reason": "x"}], max_iters=6)
    assert d == "stop" and "上限" in why


def test_decide_continue():
    d, _ = decide({"iteration": 1}, [{"blocker": False, "title": "t"}], max_iters=6)
    assert d == "continue"


# --- 强制检查 fail-closed / 派发副作用 ---------------------------------------

def test_clarify_card_fails_closed_on_exception(tmp_path, monkeypatch):
    # 澄清卡损坏/不可读 → 当作未完成(fail-closed),而非放行
    import psyclaw.psych.clarify as clar
    from psyclaw.autoloop import _clarify_incomplete

    def boom(*a, **k):
        raise RuntimeError("corrupt card")
    monkeypatch.setattr(clar, "check_card", boom)
    assert _clarify_incomplete(Path(str(tmp_path))) is True


def _patch_engine_writes_goal(monkeypatch):
    """把 run_workflow 替换成「据 topic 落 goal.md」的桩(模拟引擎 set_goal 副作用)。"""
    import psyclaw.workflows as wf
    from psyclaw.tasks import goal_path

    def fake_run(workflow, topic=None, project_dir=".", auto=False, seed=None,
                 skip_gates=False):
        if topic:
            gp = goal_path(project_dir)
            gp.parent.mkdir(parents=True, exist_ok=True)
            gp.write_text(topic, encoding="utf-8")
        return 0
    monkeypatch.setattr(wf, "run_workflow", fake_run)
    monkeypatch.setattr(wf, "get_workflow", lambda wid: {"id": wid})


def test_dispatch_does_not_persist_derived_goal(tmp_path, monkeypatch):
    from psyclaw.autoloop import _dispatch
    from psyclaw.tasks import get_goal
    _patch_engine_writes_goal(monkeypatch)
    _notes(tmp_path)
    item = {"action": "analysis-loop", "seed": {"data_csv": str(tmp_path / "d.csv")}}
    _dispatch(item, str(tmp_path))
    assert get_goal(str(tmp_path)) == ""  # 派生标签未固化成研究目标(跑完即清)


def test_dispatch_preserves_existing_human_goal(tmp_path, monkeypatch):
    from psyclaw.autoloop import _dispatch
    from psyclaw.tasks import get_goal
    _patch_engine_writes_goal(monkeypatch)
    _set_goal(tmp_path, "真实研究目标")
    item = {"action": "analysis-loop", "seed": {"data_csv": str(tmp_path / "d.csv")}}
    _dispatch(item, str(tmp_path))
    assert get_goal(str(tmp_path)) == "真实研究目标"  # 人工目标保留


# --- state(外部记忆)-------------------------------------------------------

def test_state_roundtrip_and_record(tmp_path):
    st = load_state(str(tmp_path))
    assert st["iteration"] == 0 and st["completed_actions"] == []

    record_iteration(st, {"action": "lit-loop", "title": "文献综述"},
                     {"passed": True, "reasons": []})
    assert st["iteration"] == 1
    assert "lit-loop" in st["completed_actions"]

    record_iteration(st, {"action": "meta-loop", "title": "元分析"},
                     {"passed": False, "reasons": ["数据不足"]})
    assert st["iteration"] == 2
    assert "meta-loop" in st["needs_attention"]
    assert "meta-loop" not in st["skipped"]
    assert len(st["history"]) == 2

    save_state(st, str(tmp_path))
    st2 = load_state(str(tmp_path))
    assert st2["iteration"] == 2
    assert st2["completed_actions"] == ["lit-loop"]
    assert st2["skipped"] == []
    assert st2["needs_attention"] == ["meta-loop"]


def test_state_path_under_notes(tmp_path):
    assert autoloop.state_path(str(tmp_path)).name == "autoloop_state.json"


def test_old_failed_skips_migrate_to_retryable_attention(tmp_path):
    notes = _notes(tmp_path)
    (notes / "autoloop_state.json").write_text(json.dumps({
        "iteration": 3,
        "completed_actions": [],
        "skipped": ["analysis-loop"],
        "history": [],
    }), encoding="utf-8")
    state = load_state(str(tmp_path))
    assert state["skipped"] == []
    assert state["needs_attention"] == ["analysis-loop"]


# --- feat-020:感知阶段挂 skill 推荐 ----------------------------------------

def _ext_skill(name, desc):
    return {"name": name, "description": desc, "category": "domain", "source": "/ext"}


def test_skill_hints_matches_action_type():
    pool = [
        _ext_skill("forge-meta", "random-effects meta-analysis, forest plot, heterogeneity"),
        _ext_skill("forge-qual", "thematic analysis of interview transcripts (COREQ)"),
    ]
    assert autoloop.skill_hints("meta-loop", skills=pool) == ["forge-meta"]
    assert autoloop.skill_hints("qual-loop", skills=pool) == ["forge-qual"]


def test_skill_hints_empty_when_no_match_or_no_skills():
    assert autoloop.skill_hints("analysis-loop", skills=[]) == []
    pool = [_ext_skill("unrelated", "make slides and posters")]
    assert autoloop.skill_hints("meta-loop", skills=pool) == []


def test_skill_hints_ignores_bundled_only():
    # 内置包不作为「外部技能推荐」(external_only)。
    pool = [{"name": "ars", "description": "meta-analysis toolkit",
             "category": "domain", "source": "bundled"}]
    assert autoloop.skill_hints("meta-loop", skills=pool) == []
