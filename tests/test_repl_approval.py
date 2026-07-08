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
    s.max_auto_depth = repl._MAX_AUTO_DEPTH
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


# -- /yolo 切换(仅审批,不再动深度)---------------------------------------
def test_cmd_yolo_toggles_mode(capsys):
    s = _sess(yolo=False)
    s._cmd_yolo("on")
    assert s.yolo is True
    s._cmd_yolo("off")
    assert s.yolo is False


def test_cmd_yolo_bare_toggle():
    s = _sess(yolo=False)
    s._cmd_yolo("")
    assert s.yolo is True
    s._cmd_yolo("")
    assert s.yolo is False


def test_depth_is_high_safety_backstop_not_functional_limit():
    # 回归:旧上限是 3,多步分析会「停等人继续」。现深度只是高位安全兜底,停机靠 no-progress。
    assert repl._MAX_AUTO_DEPTH >= 50
    assert repl._MAX_FOLLOWUP_REPEAT <= 3


# -- no-progress 检测(流式路径:原地打转即停,替代低深度上限)----------------
def _sess_np():
    s = repl.ReplSession.__new__(repl.ReplSession)
    s._followup_prev_sig = None
    s._followup_repeat = 0
    return s


def test_followup_signature_pure():
    sig = repl._followup_signature
    assert sig([], []) is None                       # 空 → 不参与判重
    a = sig([{"kind": "shell", "cmd": "python x.py"}], [])
    b = sig([{"kind": "shell", "cmd": "python x.py"}], [])
    assert a == b                                    # 相同请求 → 相同签名
    assert a != sig([{"kind": "shell", "cmd": "python y.py"}], [])
    # 顺序无关(同一组请求换序仍判相同)
    assert sig([{"kind": "shell", "cmd": "a"}, {"kind": "shell", "cmd": "b"}], []) \
        == sig([{"kind": "shell", "cmd": "b"}, {"kind": "shell", "cmd": "a"}], [])
    # 读取也计入
    assert sig([], ["f.csv"]) != sig([], ["g.csv"])


def test_noprogress_stops_on_repeat(capsys):
    s = _sess_np()
    runs = [{"kind": "shell", "cmd": "python fail.py"}]
    assert s._noprogress_stop(runs, []) is False     # 第 1 次
    assert s._noprogress_stop(runs, []) is False     # 第 2 次(repeat=1)
    assert s._noprogress_stop(runs, []) is True      # 第 3 次(repeat=2≥阈值)→ 停
    assert "无新进展" in capsys.readouterr().out


def test_noprogress_never_triggers_on_real_progress():
    """每轮换不同命令(真有进展)→ 永不触发 no-progress,不会掐断合法多步链。"""
    s = _sess_np()
    for i in range(30):
        runs = [{"kind": "shell", "cmd": f"python step{i}.py"}]
        assert s._noprogress_stop(runs, []) is False


def test_noprogress_resets_on_new_request():
    s = _sess_np()
    r1 = [{"kind": "shell", "cmd": "a"}]
    r2 = [{"kind": "shell", "cmd": "b"}]
    assert s._noprogress_stop(r1, []) is False
    assert s._noprogress_stop(r1, []) is False       # repeat=1
    assert s._noprogress_stop(r2, []) is False       # 换了请求 → 重置
    assert s._noprogress_stop(r1, []) is False       # 又换回 → 仍重置,不累加


def test_noprogress_ignores_empty_rounds():
    s = _sess_np()
    assert s._noprogress_stop([], []) is False
    assert s._noprogress_stop([], []) is False
    assert s._followup_repeat == 0                   # 空轮不累加计数


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
