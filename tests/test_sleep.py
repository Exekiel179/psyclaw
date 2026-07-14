"""feat-116:睡眠整合——重放蒸馏(pending 待确认)→合并→衰减结算,自动触发。"""

from __future__ import annotations

import json

import pytest


@pytest.fixture()
def mem_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("psyclaw.memory.MEM_DIR", tmp_path / "memory")
    yield tmp_path / "memory"


@pytest.fixture()
def archive(tmp_path):
    from psyclaw.recall import ContextArchive
    a = ContextArchive(tmp_path)
    for i in range(25):
        a.record("s1", f"用户消息 {i}:约定缺失码是 99", f"助手回复 {i}")
    return tmp_path


class _SleepProvider:
    api_key = "k"
    name = "fake"

    def __init__(self):
        self.calls = []

    def chat(self, messages, system=""):
        body = messages[0]["content"] if messages else ""
        self.calls.append(body[:40])
        if "记忆固化器" in body:
            yield json.dumps({
                "facts": [{"concept": "缺失码", "statement": "缺失码是 99"}],
                "lessons": [{"trigger": "python", "lesson": "用 python3"}]},
                ensure_ascii=False)
        else:
            yield "同类环境坑先探测再调用"


def test_sleep_due_by_turn_count(mem_dir, archive):
    from psyclaw.sleep import sleep_due
    assert sleep_due(str(archive)) is True
    assert sleep_due(str(archive), min_turns=100) is False


def test_run_sleep_distills_to_pending(mem_dir, archive):
    """重放产物一律待确认:语义卡 status=pending 不注入,教训进 pending 区。"""
    from psyclaw.memory import _load, recall_facts
    from psyclaw.sleep import run_sleep
    rep = run_sleep(str(archive), provider=_SleepProvider())
    assert rep["replayed_turns"] == 25 and rep["fact_candidates"] == 1
    assert rep["lesson_candidates"] == 1 and rep["llm"] is True
    facts = _load("facts")["facts"]
    assert facts[0]["status"] == "pending"
    assert recall_facts("数据缺失码怎么处理") == []          # pending 不注入
    assert _load("lessons")["pending"][0]["source"] == "sleep-replay"


def test_approve_activates_pending_fact(mem_dir, archive):
    from psyclaw.memory import memory_cli, recall_facts
    from psyclaw.sleep import run_sleep
    run_sleep(str(archive), provider=_SleepProvider())
    memory_cli(["approve", "缺失码"])
    hits = recall_facts("数据缺失码怎么处理")
    assert hits and hits[0]["concept"] == "缺失码"           # 确认后开始注入


def test_sleep_without_llm_honest_skip(mem_dir, archive):
    """无 LLM:重放/合并如实跳过,绝不硬编;衰减照常结算。"""
    from psyclaw.sleep import render_report, run_sleep
    rep = run_sleep(str(archive), provider=None)
    assert rep["fact_candidates"] == 0 and rep["merged"] == 0
    assert rep["llm"] is False
    assert "如实跳过" in render_report(rep)


def test_sleep_state_advances_incremental(mem_dir, archive):
    from psyclaw.sleep import run_sleep, sleep_due
    run_sleep(str(archive), provider=None)
    assert sleep_due(str(archive)) is False                  # 状态推进,不重复睡
    rep2 = run_sleep(str(archive), provider=None)
    assert rep2["replayed_turns"] == 0                       # 增量:无新轮次


def test_merge_clusters_distills_principle(mem_dir, archive):
    from psyclaw.memory import _load, draft_lesson, confirm_lesson
    from psyclaw.sleep import run_sleep
    for i in range(3):
        draft_lesson("mne", f"EEG 坑 {i}", "error")
        confirm_lesson(0)
    rep = run_sleep(str(archive), provider=_SleepProvider())
    assert rep["merge_clusters"] == 1 and rep["merged"] == 1
    pend = _load("lessons")["pending"]
    assert any("睡眠合并原则" in c["lesson"] for c in pend)   # 原则卡待确认
