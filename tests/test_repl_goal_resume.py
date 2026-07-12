"""真实 REPL 回归:/goal 执行语义与命令结果后的空回复恢复。"""

from __future__ import annotations

from psyclaw import repl


def test_goal_context_is_bounded_and_identified():
    out = repl._goal_context("研究三组压力差异")
    assert "notes/goal.md" in out
    assert "研究三组压力差异" in out
    long = repl._goal_context("x" * (repl._MAX_GOAL_CONTEXT_CHARS + 10))
    assert "已截断" in long


def test_goal_command_writes_and_immediately_executes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s = repl.ReplSession.__new__(repl.ReplSession)
    sent = []
    s.ask = sent.append

    assert s.handle_command("/goal 比较三组干预后的压力") is True

    assert (tmp_path / "notes" / "goal.md").read_text(encoding="utf-8").strip() \
        == "比较三组干预后的压力"
    assert len(sent) == 1
    assert "比较三组干预后的压力" in sent[0]
    assert "立即开始执行" in sent[0]


def _empty_session():
    s = repl.ReplSession.__new__(repl.ReplSession)
    s._empty_reply_streak = 0
    return s


def test_internal_empty_reply_recovers_without_user_continue(capsys):
    s = _empty_session()
    follow = s._recover_empty_reply("", internal=True, follow=None)
    assert follow == repl._EMPTY_REPLY_NUDGE
    assert "不要等待用户" in follow
    assert "自动恢复" in capsys.readouterr().out


def test_empty_reply_recovery_is_bounded():
    s = _empty_session()
    for _ in range(repl._MAX_EMPTY_REPLY_RETRIES):
        assert s._recover_empty_reply("", True, None)
    assert s._recover_empty_reply("", True, None) is None


def test_nonempty_reply_resets_recovery_streak():
    s = _empty_session()
    s._empty_reply_streak = 2
    assert s._recover_empty_reply("已修复并继续", True, None) is None
    assert s._empty_reply_streak == 0


def test_existing_followup_wins_over_empty_recovery():
    s = _empty_session()
    assert s._recover_empty_reply("", True, "已有工具结果") == "已有工具结果"
    assert s._empty_reply_streak == 0
