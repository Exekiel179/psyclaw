"""错误学习测试 —— distill_env_lessons(纯)+ _learn_from_output(会话记忆 + 落卡)。

覆盖用户实测反复踩的坑:python→python3、系统 Python 无 mne、mne.datasets.erpcore 改名。
"""

from __future__ import annotations

from psyclaw import memory, repl
from psyclaw.repl import distill_env_lessons


# -- 纯蒸馏 -----------------------------------------------------------------
def test_python_not_found_bash():
    les = distill_env_lessons("bash: python: command not found")
    assert len(les) == 1
    assert les[0]["trigger"] == "python"
    assert "python3" in les[0]["lesson"]


def test_python_not_found_zsh():
    les = distill_env_lessons("zsh: command not found: python")
    assert les and les[0]["trigger"] == "python" and "python3" in les[0]["lesson"]


def test_zsh_prefix_not_mistaken_for_missing_command():
    """回归:zsh 报错前缀 `zsh:` 不能被当成缺失命令(只应记 python)。"""
    trig = {le["trigger"] for le in distill_env_lessons("zsh: command not found: python")}
    assert trig == {"python"}
    assert "zsh" not in trig


def test_dash_line_number_not_mistaken():
    trig = {le["trigger"] for le in distill_env_lessons("sh: 1: python: not found")}
    assert "python" in trig and "1" not in trig


def test_generic_command_not_found_no_alt():
    les = distill_env_lessons("bash: footool: command not found")
    assert les and les[0]["trigger"] == "footool"
    assert "PATH" in les[0]["lesson"]          # 无内置替代 → 提示确认安装/PATH


def test_module_not_found():
    les = distill_env_lessons("ModuleNotFoundError: No module named 'mne'")
    assert les and les[0]["trigger"] == "mne"
    assert "pip3 install" in les[0]["lesson"]


def test_module_not_found_submodule_uses_top():
    les = distill_env_lessons("No module named 'sklearn.utils'")
    assert les[0]["trigger"] == "sklearn"      # 顶层包名


def test_attribute_error_renamed_api():
    les = distill_env_lessons(
        "AttributeError: module 'mne.datasets' has no attribute 'erpcore'")
    assert les and les[0]["trigger"] == "mne.datasets.erpcore"
    assert "改名" in les[0]["lesson"] or "API" in les[0]["lesson"]


def test_no_lessons_from_clean_output():
    assert distill_env_lessons("$ echo ok\n(rc=0)\nok") == []
    assert distill_env_lessons("") == []


def test_dedup_same_error_twice():
    out = ("python: command not found\n"
           "$ python x.py\npython: command not found")
    les = distill_env_lessons(out)
    assert len(les) == 1                        # 同一条只记一次


def test_multiple_distinct_lessons():
    out = ("python: command not found\n"
           "ModuleNotFoundError: No module named 'pandas'")
    trig = {le["trigger"] for le in distill_env_lessons(out)}
    assert trig == {"python", "pandas"}


# -- 会话记忆 + 落卡 --------------------------------------------------------
def _sess():
    s = repl.ReplSession.__new__(repl.ReplSession)
    s.session_lessons = []
    s._session_lesson_keys = set()
    return s


def test_learn_populates_session_and_dedups(monkeypatch, capsys):
    drafted = []
    monkeypatch.setattr(memory, "draft_lesson",
                        lambda t, l, source, kind=None: drafted.append((t, l, source, kind)))
    s = _sess()
    s._learn_from_output("python: command not found")
    s._learn_from_output("python: command not found")   # 重复不再加
    assert len(s.session_lessons) == 1
    assert s.session_lessons[0]["trigger"] == "python"
    assert len(drafted) == 1 and drafted[0][2] == "error"   # 落 pending 卡,source=error
    assert drafted[0][3] == "cmd"                            # kind 一并落卡(供自动失效再验证)
    assert "记下环境教训" in capsys.readouterr().out


def test_learn_is_best_effort_when_draft_fails(monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("memory unavailable")
    monkeypatch.setattr(memory, "draft_lesson", _boom)
    s = _sess()
    s._learn_from_output("No module named 'mne'")   # draft 抛错也不应炸
    assert len(s.session_lessons) == 1              # 会话记忆仍记下


def test_learn_noop_on_clean_output(monkeypatch):
    monkeypatch.setattr(memory, "draft_lesson", lambda *a, **k: None)
    s = _sess()
    s._learn_from_output("$ ls\n(rc=0)\na.txt")
    assert s.session_lessons == []
