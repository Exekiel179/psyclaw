"""环境教训卡自动失效测试 —— memory.archive_lesson + probe_env_card_stale + _reprobe。

场景:上次记下「本机没有 python / 没装 mne / mne.datasets.erpcore 改名」并确认生效;
后来环境变了(装上 python3 别名、pip 装了 mne、升级了 MNE)——再验证应把过时卡自动归档,
且**绝不**误删仍成立的卡(误删会让模型重新踩坑)。
"""

from __future__ import annotations

import subprocess

from psyclaw import memory, repl
from psyclaw.repl import distill_env_lessons, probe_env_card_stale


# -- distill 现在带 kind --------------------------------------------------
def test_distill_tags_kind():
    kinds = {le["trigger"]: le["kind"] for le in distill_env_lessons(
        "python: command not found\nNo module named 'mne'\n"
        "module 'mne.datasets' has no attribute 'erpcore'")}
    assert kinds["python"] == "cmd"
    assert kinds["mne"] == "module"
    assert kinds["mne.datasets.erpcore"] == "attr"


# -- memory.archive_lesson ------------------------------------------------
def _tmp_mem(monkeypatch, tmp_path):
    monkeypatch.setattr(memory, "MEM_DIR", tmp_path / "memory")


def test_archive_moves_active_to_archived(monkeypatch, tmp_path):
    _tmp_mem(monkeypatch, tmp_path)
    memory.draft_lesson("python", "没有 python,用 python3", source="error", kind="cmd")
    assert memory.confirm_lesson(0) is True
    assert len(memory.active_lessons()) == 1
    ok = memory.archive_lesson("python", "没有 python,用 python3", reason="已恢复")
    assert ok is True
    assert memory.active_lessons() == []
    arch = memory._load("lessons")["archived"]
    assert arch[0]["trigger"] == "python" and arch[0]["archived_reason"] == "已恢复"


def test_archive_precise_match_no_collateral(monkeypatch, tmp_path):
    _tmp_mem(monkeypatch, tmp_path)
    memory.draft_lesson("mne", "教训甲", source="error", kind="module")
    memory.draft_lesson("mne", "教训乙(方法学)", source="user")
    memory.confirm_lesson(0)
    memory.confirm_lesson(0)
    assert memory.archive_lesson("mne", "教训甲") is True
    remain = [c["lesson"] for c in memory.active_lessons()]
    assert remain == ["教训乙(方法学)"]        # 同 trigger 的另一张不被误删


def test_archive_miss_returns_false(monkeypatch, tmp_path):
    _tmp_mem(monkeypatch, tmp_path)
    assert memory.archive_lesson("ghost", "无此卡") is False


# -- probe_env_card_stale -------------------------------------------------
def test_probe_cmd_now_exists_is_stale(monkeypatch):
    monkeypatch.setattr(repl.shutil, "which", lambda c: "/usr/bin/python" if c == "python" else None)
    assert probe_env_card_stale({"trigger": "python", "kind": "cmd"}) is True


def test_probe_cmd_still_missing_not_stale(monkeypatch):
    monkeypatch.setattr(repl.shutil, "which", lambda c: None)
    assert probe_env_card_stale({"trigger": "python", "kind": "cmd"}) is False


def test_probe_module_import_ok_is_stale(monkeypatch):
    monkeypatch.setattr(repl.shutil, "which", lambda c: "/usr/bin/python3")

    class _R:
        returncode = 0
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _R())
    assert probe_env_card_stale({"trigger": "mne", "kind": "module"}) is True


def test_probe_module_import_fails_not_stale(monkeypatch):
    monkeypatch.setattr(repl.shutil, "which", lambda c: "/usr/bin/python3")

    class _R:
        returncode = 1
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _R())
    assert probe_env_card_stale({"trigger": "mne", "kind": "module"}) is False


def test_probe_unknown_kind_or_bad_trigger_is_none(monkeypatch):
    assert probe_env_card_stale({"trigger": "python", "kind": None}) is None
    assert probe_env_card_stale({"trigger": "x;rm -rf", "kind": "cmd"}) is None   # 非法字符→不测


def test_probe_module_no_interpreter_is_none(monkeypatch):
    monkeypatch.setattr(repl.shutil, "which", lambda c: None)
    assert probe_env_card_stale({"trigger": "mne", "kind": "module"}) is None


# -- _reprobe_env_lessons (会话集成) --------------------------------------
def _sess():
    s = repl.ReplSession.__new__(repl.ReplSession)
    s.session_lessons = [{"trigger": "python", "lesson": "没 python", "kind": "cmd"}]
    return s


def test_reprobe_archives_recovered_cmd_and_prunes_session(monkeypatch, tmp_path):
    _tmp_mem(monkeypatch, tmp_path)
    memory.draft_lesson("python", "没有 python,用 python3", source="error", kind="cmd")
    memory.confirm_lesson(0)
    monkeypatch.setattr(repl.shutil, "which", lambda c: "/usr/bin/python")  # 现在有了
    s = _sess()
    n = s._reprobe_env_lessons(include_slow=False)
    assert n == 1
    assert memory.active_lessons() == []                     # 已归档
    assert all(le["trigger"] != "python" for le in s.session_lessons)   # 会话记忆同步清


def test_reprobe_keeps_valid_card(monkeypatch, tmp_path):
    """仍缺失的卡必须留着——误删会让模型重新踩坑(自动失效的第一红线)。"""
    _tmp_mem(monkeypatch, tmp_path)
    memory.draft_lesson("python", "没有 python,用 python3", source="error", kind="cmd")
    memory.confirm_lesson(0)
    monkeypatch.setattr(repl.shutil, "which", lambda c: None)   # 仍然没有
    s = _sess()
    assert s._reprobe_env_lessons(include_slow=False) == 0
    assert len(memory.active_lessons()) == 1


def test_reprobe_skips_slow_kinds_when_not_included(monkeypatch, tmp_path):
    _tmp_mem(monkeypatch, tmp_path)
    memory.draft_lesson("mne", "没装 mne", source="error", kind="module")
    memory.confirm_lesson(0)
    # include_slow=False 不应触碰 module 卡(即使它已恢复也先不管,留给 /memory verify)
    called = {"n": 0}
    monkeypatch.setattr(repl, "probe_env_card_stale",
                        lambda c: called.__setitem__("n", called["n"] + 1) or True)
    s = _sess()
    assert s._reprobe_env_lessons(include_slow=False) == 0
    assert called["n"] == 0                                  # module 卡根本没被探测
