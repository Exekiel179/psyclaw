"""feat-146:斜杠命令回显 + 联想完整性 + 打错给「你是不是想输入」。

用户反馈:斜杠命令后要有显示(分辨是否生效)、输入 / 要弹联想。
实查发现 7 个已处理命令(/agent /plan /audit /research /yolo /safemode
/research-loop)不在 COMMANDS 里 → 从来不联想;打错命令只回冷冰冰「未知命令」。
"""
from __future__ import annotations

import re

from psyclaw.repl import COMMANDS, _suggest_command
from psyclaw.ui_input import _slash_completions


# ---- 联想完整性:每个被处理的命令都要能联想到 -------------------------------

def _handled_commands() -> set[str]:
    src = open("psyclaw/repl.py", encoding="utf-8").read()
    # 只取 handle_command 函数体
    start = src.index("def handle_command")
    end = src.index("\n    def ", start + 1)
    body = src[start:end]
    handled: set[str] = set()
    for m in re.finditer(r'cmd (?:==|in) \(([^)]*)\)', body):
        handled |= set(re.findall(r"'(/[a-z-]+)'", m.group(1)))
    for m in re.finditer(r'cmd == "(/[a-z-]+)"', body):
        handled.add(m.group(1))
    return handled


def test_all_handled_commands_are_suggestable():
    from psyclaw.repl import _ALIAS_COMMANDS
    missing = _handled_commands() - set(COMMANDS) - set(_ALIAS_COMMANDS)
    assert not missing, f"这些命令被处理但不在 COMMANDS/别名(不会联想):{sorted(missing)}"


def test_newly_surfaced_commands_autocomplete():
    """/plan /audit /research 此前被处理却不联想,现补进 COMMANDS(三元组 = 后缀,命令,描述)。"""
    for prefix, want in (("/pl", "/plan"), ("/au", "/audit"), ("/re", "/research")):
        disp = [d for _s, d, _m in _slash_completions(prefix, COMMANDS)]
        assert want in disp, f"{prefix} 应联想到 {want},实得 {disp}"


def test_agent_stays_hidden_but_suggestable():
    """既有 streamline 契约:/agent 不进主联想;但打错仍能被建议(不判「无效」)。"""
    disp = [d for _s, d, _m in _slash_completions("/ag", COMMANDS)]
    assert "/agent" not in disp                       # 契约:主联想不含 /agent
    assert _suggest_command("/agent", COMMANDS) == "/agent"   # 但识别有效


# ---- 打错命令 → 建议最接近的 -------------------------------------------------

def test_suggest_close_typo():
    assert _suggest_command("/agnet", COMMANDS) == "/agent"


def test_suggest_prefix():
    # /expo → /export
    assert _suggest_command("/expo", COMMANDS) == "/export"


def test_suggest_none_for_gibberish():
    assert _suggest_command("/xqzwptv", COMMANDS) is None


# ---- 未知命令回显里带建议 ----------------------------------------------------

class _StubSession:
    """只驱动 handle_command 的未知分支,避免起真 REPL。"""
    def __init__(self):
        self.plugins = None

    handle_command = None   # 占位,下面 monkeypatch 真方法


def test_unknown_command_output_has_suggestion(capsys):
    from psyclaw.repl import ReplSession
    rs = ReplSession.__new__(ReplSession)
    rs.plugins = None
    rs.handle_command("/agnet")
    out = capsys.readouterr().out
    assert "/agent" in out          # 未知命令时提示最接近的
