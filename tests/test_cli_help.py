"""测试 CLI --help 不崩溃（BUG-1 防回归）。

历史 BUG：subparser 的 help= 文本里有未转义的 `%`（如 `95% CI` → `%C`），
argparse 用 `%` 做 help 插值时抛 `ValueError: unsupported format character`。
本测试遍历主解析器及每个子解析器调用 format_help()，确保全部不抛错。
"""

import argparse
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.cli import build_parser  # noqa: E402


def _iter_subparsers(parser):
    """产出 (name, subparser) 对，遍历所有 _SubParsersAction 的 choices。"""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                yield name, sub


def test_build_parser_returns_argument_parser():
    p = build_parser()
    assert isinstance(p, argparse.ArgumentParser)


def test_top_level_format_help_does_not_raise():
    # 顶层 help 会展开所有 subparser 的短 help= 字符串——BUG-1 的崩溃点。
    p = build_parser()
    text = p.format_help()
    assert "psyclaw" in text
    assert len(text) > 0


def test_top_level_format_usage_does_not_raise():
    p = build_parser()
    assert p.format_usage()


def test_has_subparsers():
    p = build_parser()
    names = [name for name, _ in _iter_subparsers(p)]
    # 至少应包含若干核心命令（统计命令已外移到成熟库/MCP）
    assert "repl" in names
    assert "research" in names
    assert "clarify" in names
    assert len(names) > 20


def test_every_subparser_format_help_does_not_raise():
    p = build_parser()
    failures = []
    for name, sub in _iter_subparsers(p):
        try:
            sub.format_help()
        except Exception as exc:  # noqa: BLE001 — 记录所有失败命令名
            failures.append((name, repr(exc)))
    assert not failures, f"以下子命令 format_help() 抛错：{failures}"


def test_every_subparser_format_usage_does_not_raise():
    p = build_parser()
    failures = []
    for name, sub in _iter_subparsers(p):
        try:
            sub.format_usage()
        except Exception as exc:  # noqa: BLE001
            failures.append((name, repr(exc)))
    assert not failures, f"以下子命令 format_usage() 抛错：{failures}"


def test_no_bare_percent_in_subparser_help():
    """直接断言无裸 `%`：所有 subparser 短 help= 里 `%` 必须成对转义（%%）。

    这是 BUG-1 的根因检查——比 format_help() 更早、更精准地定位问题命令。
    """
    p = build_parser()
    offenders = []
    for action in p._actions:
        if isinstance(action, argparse._SubParsersAction):
            for choice_action in action._choices_actions:
                h = choice_action.help or ""
                # 去掉合法的 %% 后若仍有单独的 %，即为裸百分号
                if h.replace("%%", "").count("%"):
                    offenders.append((choice_action.dest, h))
    assert not offenders, f"subparser help 含未转义 %：{offenders}"


def test_all_top_level_commands_exposed_in_help():
    """`--help` 暴露全部顶层命令(不再隐藏);CORE_COMMANDS 仅用于 ★ 标注。"""
    p = build_parser()
    shown, callable_all = set(), set()
    for action in p._actions:
        if isinstance(action, argparse._SubParsersAction):
            shown = {pa.dest for pa in action._choices_actions}
            callable_all = set(action.choices.keys())
    assert shown == callable_all          # 顶层帮助列出的 == 可调用的(全部暴露)
    assert {"serve", "figures", "loop", "guide"} <= shown


# --- 编排命令:loop(通用)+ <type>-loop(研究流程)+ research(固定全流程)----------

def test_loop_is_generic_orchestrator():
    """`loop` = 通用编排回路(run_loop);research 只做固定全流程,不再有 --freeform。"""
    p = build_parser()
    names = [name for name, _ in _iter_subparsers(p)]
    assert "loop" in names
    assert p.parse_args(["loop", "任意任务"]).func.__name__ == "cmd_loop"
    # research 保留为固定全流程;--freeform 已移除(通用回路统一走 loop)
    assert "research" in names
    with pytest.raises(SystemExit):
        p.parse_args(["research", "主题", "--freeform"])


def test_typed_loop_commands_registered():
    """四条研究流程的顶层命令均为 <type>-loop。"""
    p = build_parser()
    names = {name for name, _ in _iter_subparsers(p)}
    assert {"lit-loop", "meta-loop", "analysis-loop", "qual-loop"} <= names
    assert {"review-lit", "meta", "analysis", "qualitative"}.isdisjoint(names)


def test_guide_command_registered():
    """`guide` 首次使用上手介绍命令已注册并可分发。"""
    p = build_parser()
    names = {name for name, _ in _iter_subparsers(p)}
    assert "guide" in names
    assert p.parse_args(["guide"]).func.__name__ == "cmd_guide"


def test_commands_catalog_registered_and_covers_all():
    """`commands` 命令已注册；分类清单覆盖除 stub 外的全部命令。"""
    from psyclaw.cli import COMMAND_CATEGORIES
    p = build_parser()
    names = {name for name, _ in _iter_subparsers(p)}
    assert "commands" in names
    catalogued = {c for _title, cmds in COMMAND_CATEGORIES for c in cmds}
    # 分类清单不重复
    flat = [c for _t, cmds in COMMAND_CATEGORIES for c in cmds]
    assert len(flat) == len(set(flat)), "COMMAND_CATEGORIES 有重复命令"
    # 所有注册命令都被归类（统计命令已删，无 stub 例外）
    assert names == catalogued
