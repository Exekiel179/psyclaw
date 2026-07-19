"""所有 CLI 命令自动工具化(goal):用户以对话工作,每个子命令都当工具暴露给模型。

argparse 自省:排除交互/系统类,其余自动包成工具(构造 Namespace 调 cmd_* 捕获 stdout)。
新增 CLI 命令自动覆盖,不用逐个手写。已手工优化的 lit_* 保留、不被覆盖。
"""
from __future__ import annotations

from psyclaw.toolloop import build_tools


def test_cli_commands_auto_toolified():
    t = build_tools(".")
    for name in ("check", "export", "method", "cite", "review", "preregister",
                 "design", "assume", "jars", "provenance"):
        assert name in t, f"CLI 命令 {name} 未工具化"


def test_system_and_interactive_commands_skipped():
    t = build_tools(".")
    for name in ("setup", "doctor", "update", "eval", "config", "webbridge", "lit"):
        assert name not in t                      # 交互/系统类不工具化;lit 由手工 lit_* 取代


def test_side_effect_flags_reasonable():
    t = build_tools(".")
    assert t["export"]["side_effect"] is True      # 写 Word,需批准
    assert t["preregister"]["side_effect"] is True
    assert t["check"]["side_effect"] is False       # 质检只读,自动执行
    assert t["review"]["side_effect"] is False


def test_manual_lit_tools_preserved():
    t = build_tools(".")
    assert all(x in t for x in ("lit_search", "lit_snowball", "lit_download"))


def test_method_tool_runs_via_introspection():
    t = build_tools(".")
    out = t["method"]["run"]({})
    assert "sample-size" in out and "confound-control" in out


def test_cli_tool_has_args_and_desc():
    t = build_tools(".")
    assert "draft" in t["check"]["args"]           # 自省出 positional
    assert t["export"]["desc"] and "CLI 工具" in t["export"]["desc"]


def test_cli_run_failsafe_never_raises():
    t = build_tools(".")
    out = t["check"]["run"]({})                     # 无参:cmd_check 走缺省,不崩
    assert isinstance(out, str) and out
