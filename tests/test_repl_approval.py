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
    s._auto_approve_labels = set()
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
    monkeypatch.setattr(repl, "_hitl_confirm_all", lambda p: calls.append(p) or "yes")
    assert s._side_effect_ok("ls -la", label="执行") is True
    assert calls, "非 YOLO 非危险必须逐条确认(三态)"


# -- 「全部同意(a)」:确认一次,同类本会话不再问(用户实测)---------------------
def test_all_makes_label_sticky(monkeypatch):
    s = _sess(yolo=False)
    monkeypatch.setattr(repl, "_hitl_confirm_all", lambda p: "all")
    assert s._side_effect_ok("cp a b", label="执行 shell 命令") is True
    assert "执行 shell 命令" in s._auto_approve_labels
    # 之后同类不再问:把确认换成会炸的,证明根本没被调用
    def _boom(p):
        raise AssertionError("同类不该再问")
    monkeypatch.setattr(repl, "_hitl_confirm_all", _boom)
    assert s._side_effect_ok("cp c d", label="执行 shell 命令") is True


def test_all_is_per_label(monkeypatch):
    s = _sess(yolo=False)
    monkeypatch.setattr(repl, "_hitl_confirm_all", lambda p: "all")
    s._side_effect_ok("cp a b", label="执行 shell 命令")
    # 另一类(覆盖文件)仍要问
    asked = []
    monkeypatch.setattr(repl, "_hitl_confirm_all", lambda p: asked.append(p) or "yes")
    s._side_effect_ok("/f.py", label="覆盖已存在文件")
    assert asked, "『全部同意』只对说过的那一类生效,别的类仍问"


def test_all_never_offered_for_dangerous(monkeypatch):
    s = _sess(yolo=False)
    # 危险走两态 _hitl_confirm,不进 _auto_approve_labels
    monkeypatch.setattr(repl, "_hitl_confirm", lambda p: True)
    assert s._side_effect_ok("rm -rf x", dangerous=True, label="执行 shell 命令") is True
    assert "执行 shell 命令" not in s._auto_approve_labels
    # 即便之前对该类说过 all,危险仍逐条问(红线不放松)
    s._auto_approve_labels.add("执行 shell 命令")
    calls = []
    monkeypatch.setattr(repl, "_hitl_confirm", lambda p: calls.append(p) or False)
    assert s._side_effect_ok("rm -rf y", dangerous=True, label="执行 shell 命令") is False
    assert calls, "危险操作即使说过 all 也必须逐条问"


def test_hitl_confirm_all_non_tty_fail_closed():
    assert repl._hitl_confirm_all("go?") == "no"     # pytest 非 TTY → fail-closed


def test_hitl_confirm_all_parsing(monkeypatch):
    import builtins

    class _TTY:
        def isatty(self):
            return True

    monkeypatch.setattr("sys.stdin", _TTY())
    monkeypatch.setattr("sys.stdout", _TTY())
    for raw, exp in [("a", "all"), ("all", "all"), ("全部", "all"),
                     ("", "yes"), ("y", "yes"), ("是", "yes"),
                     ("n", "no"), ("nope", "no")]:
        monkeypatch.setattr(builtins, "input", lambda *a, _v=raw, **k: _v)
        assert repl._hitl_confirm_all("go?") == exp, raw


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


def test_approval_is_public_name_and_yolo_remains_alias(capsys):
    s = _sess(yolo=False)
    s._cmd_approval("auto")
    assert s.yolo is True
    s._cmd_approval("ask")
    assert s.yolo is False
    s._cmd_yolo("")                  # 旧名仍按原语义切换
    assert s.yolo is True
    assert "审批" in capsys.readouterr().out


def test_primary_repl_commands_hide_legacy_modes():
    assert {"/run", "/auto", "/approval", "/access"} <= set(repl.COMMANDS)
    assert {"/agent", "/research-loop", "/yolo", "/safemode"}.isdisjoint(repl.COMMANDS)


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


# -- no-progress 只管自主回合:用户逐条确认(打 y)不该被误判掐断(用户实测) ----------
def test_round_autonomous_nonyolo_shell_needs_human():
    s = _sess(yolo=False)
    assert s._round_is_autonomous([{"kind": "shell", "cmd": "python x.py"}], []) is False


def test_round_autonomous_nonyolo_psyclaw_is_auto():
    s = _sess(yolo=False)
    assert s._round_is_autonomous([{"kind": "psyclaw", "cmd": "version"}], []) is True


def test_round_autonomous_yolo_shell_is_auto():
    s = _sess(yolo=True)
    assert s._round_is_autonomous([{"kind": "shell", "cmd": "python x.py"}], []) is True


def test_round_autonomous_yolo_dangerous_needs_human():
    s = _sess(yolo=True)
    assert s._round_is_autonomous([{"kind": "shell", "cmd": "rm -rf /tmp/x"}], []) is False


def test_round_autonomous_reads_only_is_auto():
    s = _sess(yolo=False)
    assert s._round_is_autonomous([], ["a.csv"]) is True


def test_round_autonomous_mixed_shell_needs_human():
    s = _sess(yolo=False)
    runs = [{"kind": "psyclaw", "cmd": "version"}, {"kind": "shell", "cmd": "ls"}]
    assert s._round_is_autonomous(runs, []) is False   # 有一条要确认就算非自主


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
class TestCmdApprovalScope:
    def test_plain_program(self):
        assert repl.cmd_approval_scope("pytest -q tests/") == "pytest"
        assert repl.cmd_approval_scope("ls -la") == "ls"
    def test_subcommand_tools_include_second_token(self):
        assert repl.cmd_approval_scope("git status -sb") == "git status"
        assert repl.cmd_approval_scope("git push origin dev") == "git push"
        assert repl.cmd_approval_scope("python3 analyze.py --out x.png") \
            == "python3 analyze.py"
        assert repl.cmd_approval_scope("bash -c 'echo hi'") == "bash -c"
    def test_path_stripped_to_program_name(self):
        assert repl.cmd_approval_scope("/usr/bin/python3 run.py") == "python3 run.py"
    def test_compound_commands_not_generalized(self):
        scope = repl.cmd_approval_scope("cat a.csv | head -5")
        assert "|" in scope                       # 复合命令:范围=整条原文
        assert repl.cmd_approval_scope("a && b") == "a && b"
    def test_empty(self):
        assert repl.cmd_approval_scope("  ") == "空命令"
    def test_confirm_cmd_uses_scoped_label(self, monkeypatch):
        s = _sess()
        labels = []
        monkeypatch.setattr(
            repl.ReplSession, "_side_effect_ok",
            lambda self, d, dangerous=False, label="": labels.append(label) or True)
        s._confirm_cmd("git status -sb")
        assert labels == ["执行 shell 命令(git status)"]
    def test_scoped_all_does_not_leak_to_other_programs(self, monkeypatch):
        """同意了 git status 的「全部」,跑 rm 依然要问。"""
        s = _sess()
        s._auto_approve_labels = {"执行 shell 命令(git status)"}
        asked = []
        monkeypatch.setattr(repl, "_hitl_confirm_all",
                            lambda p: asked.append(p) or "no")
        assert s._confirm_cmd("git status") is True          # 已同意的范围放行
        assert not asked
        assert s._confirm_cmd("rm outputs/tmp.txt") is False  # 别的程序照问
        assert asked
