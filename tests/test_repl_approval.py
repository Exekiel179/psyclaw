"""审批模式(YOLO / 逐条确认)+ 自动跟进深度 + readline 安全提示 测试。

覆盖用户实测的三个坑:
1. y 请求太多 → YOLO 自动放行(非危险),/yolo 切换;
2. 确认框与命令回显串行 → safe_prompt 包裹 ANSI;
3. 程序停在深度上限要人说「继续」→ 深度放宽 + YOLO 更深。
"""

from __future__ import annotations

import sys

import pytest

from psyclaw import repl, ui_input


def _sess(yolo=False):
    """跳过重构造函数,只装审批相关属性。"""
    s = repl.ReplSession.__new__(repl.ReplSession)
    s.yolo = yolo
    s.max_auto_depth = repl._YOLO_AUTO_DEPTH if yolo else repl._MAX_AUTO_DEPTH
    return s


# -- YOLO 放行 / 危险仍问 ---------------------------------------------------
def test_yolo_auto_approves_nondangerous():
    s = _sess(yolo=True)
    assert s._side_effect_ok("python3 analysis.py", label="执行") is True


def test_yolo_still_confirms_dangerous(monkeypatch):
    s = _sess(yolo=True)
    seen = []
    monkeypatch.setattr(repl, "_hitl_confirm", lambda p: seen.append(p) or False)
    assert s._side_effect_ok("rm -rf /tmp/x", dangerous=True) is False
    assert seen, "危险操作即使 YOLO 也必须问人"


def test_default_mode_always_confirms(monkeypatch):
    s = _sess(yolo=False)
    calls = []
    monkeypatch.setattr(repl, "_hitl_confirm", lambda p: calls.append(p) or True)
    assert s._side_effect_ok("ls -la", label="执行") is True
    assert calls, "非 YOLO 必须逐条确认"


def test_confirm_cmd_detects_danger(monkeypatch):
    s = _sess(yolo=True)
    seen = []
    monkeypatch.setattr(repl, "_hitl_confirm", lambda p: seen.append(p) or True)
    # 危险命令即使 YOLO 也走确认
    assert s._confirm_cmd("git push --force origin master") is True
    assert seen
    # 普通命令 YOLO 直接放行,不问
    seen.clear()
    assert s._confirm_cmd("python3 run.py") is True
    assert not seen


# -- /yolo 切换 + 深度联动 --------------------------------------------------
def test_cmd_yolo_toggles_mode_and_depth(capsys):
    s = _sess(yolo=False)
    s._cmd_yolo("on")
    assert s.yolo is True
    assert s.max_auto_depth == repl._YOLO_AUTO_DEPTH
    s._cmd_yolo("off")
    assert s.yolo is False
    assert s.max_auto_depth == repl._MAX_AUTO_DEPTH


def test_cmd_yolo_bare_toggle():
    s = _sess(yolo=False)
    s._cmd_yolo("")
    assert s.yolo is True
    s._cmd_yolo("")
    assert s.yolo is False


def test_depth_raised_from_old_default():
    # 回归:旧上限是 3,多步分析会「停等人继续」。现默认已放宽,YOLO 更深。
    assert repl._MAX_AUTO_DEPTH > 3
    assert repl._YOLO_AUTO_DEPTH > repl._MAX_AUTO_DEPTH


# -- readline 安全提示(修确认框与回显串行)---------------------------------
def test_safe_prompt_wraps_ansi_when_readline_loaded(monkeypatch):
    monkeypatch.setitem(sys.modules, "readline", object())
    wrapped = ui_input.safe_prompt("\033[33mhi\033[0m")
    assert "\001" in wrapped and "\002" in wrapped


def test_safe_prompt_noop_without_readline(monkeypatch):
    monkeypatch.delitem(sys.modules, "readline", raising=False)
    p = "\033[33mhi\033[0m"
    assert ui_input.safe_prompt(p) == p


# -- _ask_yn 仍守 fail-safe(EOF 返 default)--------------------------------
def test_ask_yn_eof_returns_default(monkeypatch):
    import builtins

    from psyclaw.loop import _ask_yn

    def _raise(*_a, **_k):
        raise EOFError

    monkeypatch.setattr(builtins, "input", _raise)
    assert _ask_yn("go?", default=True) is True
    assert _ask_yn("go?", default=False) is False


def test_ask_yn_reads_yes(monkeypatch):
    import builtins

    from psyclaw.loop import _ask_yn

    monkeypatch.setattr(builtins, "input", lambda *_a, **_k: "y")
    assert _ask_yn("go?", default=False) is True
    monkeypatch.setattr(builtins, "input", lambda *_a, **_k: "n")
    assert _ask_yn("go?", default=True) is False
