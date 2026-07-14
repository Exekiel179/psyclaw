"""feat-135:任务中间状态外存——步骤级快照,便于召回。"""

from __future__ import annotations

from psyclaw import taskstate as TS


def test_save_and_load_steps(tmp_path):
    assert TS.save_step("meta", "load_effects", {"k": 8}, str(tmp_path))
    assert TS.save_step("meta", "analysis", {"pooled": 0.33}, str(tmp_path))
    steps = TS.load_steps("meta", str(tmp_path))
    assert [s["step"] for s in steps] == ["load_effects", "analysis"]
    assert steps[1]["data"]["pooled"] == 0.33


def test_append_only_keeps_history(tmp_path):
    TS.save_step("t", "s1", {}, str(tmp_path))
    TS.save_step("t", "s1", {"retry": 1}, str(tmp_path))   # 同名步骤不覆盖
    assert len(TS.load_steps("t", str(tmp_path))) == 2      # 保留完整轨迹


def test_summary_truncates_and_no_raw_dump(tmp_path):
    TS.save_step("t", "s", {"big": "x" * 500}, str(tmp_path))
    d = TS.load_steps("t", str(tmp_path))[0]["data"]
    assert len(d["big"]) < 260 and "…(+" in d["big"]       # 摘要不落原始全量


def test_list_tasks(tmp_path):
    TS.save_step("meta", "a", {}, str(tmp_path))
    TS.save_step("analysis", "b", {}, str(tmp_path))
    TS.save_step("analysis", "c", {}, str(tmp_path))
    rows = {r["task"]: r for r in TS.list_tasks(str(tmp_path))}
    assert rows["analysis"]["n_steps"] == 2 and rows["analysis"]["last_step"] == "c"


def test_recall_task_renders(tmp_path):
    TS.save_step("meta", "load_effects", {"k": 8}, str(tmp_path))
    block = TS.recall_task("meta", str(tmp_path))
    assert "任务中间状态回顾:meta" in block and "load_effects" in block and "k=8" in block


def test_recall_empty(tmp_path):
    assert TS.recall_task("nope", str(tmp_path)) == ""
    assert TS.list_tasks(str(tmp_path)) == []


def test_save_step_failsafe(tmp_path, monkeypatch):
    """写不了不抛(fail-safe)。"""
    monkeypatch.setattr(TS.Path, "mkdir",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
    assert TS.save_step("t", "s", {}, str(tmp_path)) is False
