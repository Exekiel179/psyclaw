"""测试 CLI --help 不崩溃（BUG-1 防回归）。

历史 BUG：subparser 的 help= 文本里有未转义的 `%`（如 `95% CI` → `%C`），
argparse 用 `%` 做 help 插值时抛 `ValueError: unsupported format character`。
本测试遍历主解析器及每个子解析器调用 format_help()，确保全部不抛错。
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.cli import build_parser


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
    # 至少应包含若干核心命令
    assert "repl" in names
    assert "partial-corr" in names  # 含 95%% CI 的命令
    assert "roc" in names           # 含 95%% CI 的命令
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


def test_partial_corr_help_renders_percent_literally():
    """%% 应在渲染后还原为单个 %（95% CI 文本正确显示）。"""
    p = build_parser()
    text = p.format_help()
    # 顶层列出 partial-corr / roc 的短 help，% 应正常出现
    assert "partial-corr" in text
    assert "roc" in text
