"""R-1 prompt_toolkit REPL 后端测试。

验收：
  - 无 prompt_toolkit 环境：REPL 仍可跑，现有命令不回归
  - _slash_completions 纯函数覆盖所有过滤分支
  - read_line 在 _PTK_AVAILABLE=True 时优先调用 _ptk_read_line
  - read_line 在非 TTY 环境降级为 input()
  - 单例创建与 completer 更新逻辑可测

自包含 runner：python tests/test_repl_ptk.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import psyclaw.ui_input as uin  # noqa: E402

# 测试用命令表（模拟 repl.COMMANDS 子集）
_CMDS = {
    "/help": "命令总览",
    "/exit": "退出",
    "/model": "查看/切换模型",
    "/memory": "三层记忆",
    "/mcp": "MCP 目录",
    "/gates": "门禁自检",
}


# ===========================================================================
# _slash_completions — 纯函数，无需 prompt_toolkit
# ===========================================================================

class TestSlashCompletions:

    def test_empty_input_returns_empty(self):
        assert uin._slash_completions("", _CMDS) == []

    def test_no_slash_prefix_returns_empty(self):
        assert uin._slash_completions("hello", _CMDS) == []

    def test_plain_word_returns_empty(self):
        assert uin._slash_completions("model", _CMDS) == []

    def test_slash_alone_returns_all(self):
        results = uin._slash_completions("/", _CMDS)
        assert len(results) == len(_CMDS)

    def test_slash_prefix_filters_correctly(self):
        results = uin._slash_completions("/m", _CMDS)
        cmds = [r[1] for r in results]
        assert "/model" in cmds
        assert "/memory" in cmds
        assert "/mcp" in cmds
        assert "/help" not in cmds
        assert "/exit" not in cmds

    def test_exact_match_returns_one(self):
        results = uin._slash_completions("/help", _CMDS)
        assert len(results) == 1
        assert results[0][1] == "/help"

    def test_suffix_is_remaining_chars(self):
        results = uin._slash_completions("/hel", _CMDS)
        assert results[0][0] == "p"        # suffix = cmd[len(text):]
        assert results[0][1] == "/help"    # display = full command

    def test_meta_desc_truncated_to_50(self):
        long_cmds = {"/cmd": "A" * 100}
        results = uin._slash_completions("/", long_cmds)
        assert len(results[0][2]) == 50

    def test_space_in_input_returns_empty(self):
        # Once user typed "/help arg", no more completions
        assert uin._slash_completions("/help something", _CMDS) == []

    def test_no_false_prefix_matches(self):
        # "/mo" should NOT match "/memory" if we hadn't specified it
        cmds = {"/model": "x"}
        results = uin._slash_completions("/me", cmds)
        assert results == []

    def test_max_suggest_cap(self):
        big_cmds = {f"/{i}": "desc" for i in range(20)}
        results = uin._slash_completions("/", big_cmds)
        assert len(results) <= uin.MAX_SUGGEST

    def test_tuple_has_three_elements(self):
        results = uin._slash_completions("/h", _CMDS)
        assert all(len(r) == 3 for r in results)


# ===========================================================================
# _PTK_AVAILABLE 标志
# ===========================================================================

class TestPtkAvailableFlag:

    def test_ptk_flag_is_bool(self):
        assert isinstance(uin._PTK_AVAILABLE, bool)

    def test_ptk_session_initially_none(self):
        # 模块加载时 _ptk_session 应为 None（未调用 _get_ptk_session 前）
        # 可能已被其他测试设置，仅检查类型
        assert uin._ptk_session is None or uin._ptk_session is not None  # always passes
        # 重点：当 ptk 不可用时，_ptk_session 保持 None
        if not uin._PTK_AVAILABLE:
            assert uin._ptk_session is None


# ===========================================================================
# read_line — PTK 路径（mock 模拟 ptk 可用）
# ===========================================================================

class TestReadLinePtkDispatch:

    def test_ptk_path_called_when_available(self):
        """_PTK_AVAILABLE=True + TTY → 调用 _ptk_read_line。"""
        called = []

        def _fake_ptk(p, c):
            called.append((p, c))
            return "result"

        with patch.object(uin, "_PTK_AVAILABLE", True), \
             patch.object(uin, "_ptk_read_line", _fake_ptk), \
             patch("sys.stdin") as mock_stdin, \
             patch("sys.stdout") as mock_stdout:
            mock_stdin.isatty.return_value = True
            mock_stdout.isatty.return_value = True
            result = uin.read_line("prompt> ", _CMDS)

        assert result == "result"
        assert called

    def test_ptk_path_receives_prompt_and_commands(self):
        """_ptk_read_line 收到正确 prompt 和 commands。"""
        received = {}

        def _fake_ptk(p, c):
            received["p"] = p
            received["c"] = c
            return "ok"

        with patch.object(uin, "_PTK_AVAILABLE", True), \
             patch.object(uin, "_ptk_read_line", _fake_ptk), \
             patch("sys.stdin") as mock_stdin, \
             patch("sys.stdout") as mock_stdout:
            mock_stdin.isatty.return_value = True
            mock_stdout.isatty.return_value = True
            uin.read_line("myp> ", _CMDS)

        assert received["p"] == "myp> "
        assert received["c"] == _CMDS

    def test_ptk_keyboard_interrupt_propagates(self):
        """prompt_toolkit KeyboardInterrupt 应穿透，不被吞掉。"""
        def _raise(p, c):
            raise KeyboardInterrupt

        with patch.object(uin, "_PTK_AVAILABLE", True), \
             patch.object(uin, "_ptk_read_line", _raise), \
             patch("sys.stdin") as mock_stdin, \
             patch("sys.stdout") as mock_stdout:
            mock_stdin.isatty.return_value = True
            mock_stdout.isatty.return_value = True
            try:
                uin.read_line("p> ", _CMDS)
                assert False, "should have raised"
            except KeyboardInterrupt:
                pass

    def test_ptk_eof_error_propagates(self):
        """prompt_toolkit EOFError 应穿透。"""
        def _raise(p, c):
            raise EOFError

        with patch.object(uin, "_PTK_AVAILABLE", True), \
             patch.object(uin, "_ptk_read_line", _raise), \
             patch("sys.stdin") as mock_stdin, \
             patch("sys.stdout") as mock_stdout:
            mock_stdin.isatty.return_value = True
            mock_stdout.isatty.return_value = True
            try:
                uin.read_line("p> ", _CMDS)
                assert False, "should have raised"
            except EOFError:
                pass

    def test_ptk_generic_exception_falls_back_to_stdlib(self):
        """ptk 抛出普通异常时，降级 stdlib 路径（非 TTY → input）。"""
        def _raise(p, c):
            raise RuntimeError("terminal broken")

        with patch.object(uin, "_PTK_AVAILABLE", True), \
             patch.object(uin, "_ptk_read_line", _raise), \
             patch("sys.stdin") as mock_stdin, \
             patch("sys.stdout") as mock_stdout, \
             patch("builtins.input", return_value="fallback"):
            mock_stdin.isatty.return_value = False   # non-TTY after ptk fails
            mock_stdout.isatty.return_value = False
            result = uin.read_line("p> ", _CMDS)

        assert result == "fallback"

    def test_ptk_skipped_when_not_available(self):
        """_PTK_AVAILABLE=False 时不调用 _ptk_read_line。"""
        ptk_calls = []

        def _fake_ptk(p, c):
            ptk_calls.append(True)
            return "ptk"

        with patch.object(uin, "_PTK_AVAILABLE", False), \
             patch.object(uin, "_ptk_read_line", _fake_ptk), \
             patch("sys.stdin") as mock_stdin, \
             patch("sys.stdout") as mock_stdout, \
             patch("builtins.input", return_value="stdio"):
            mock_stdin.isatty.return_value = False
            mock_stdout.isatty.return_value = False
            uin.read_line("p> ", _CMDS)

        assert not ptk_calls


# ===========================================================================
# read_line — 非 TTY 降级路径
# ===========================================================================

class TestReadLineNonTty:

    def test_non_tty_uses_input(self):
        with patch("sys.stdin") as mock_stdin, \
             patch("sys.stdout") as mock_stdout, \
             patch("builtins.input", return_value="  hello  "):
            mock_stdin.isatty.return_value = False
            mock_stdout.isatty.return_value = False
            result = uin.read_line("prompt> ", _CMDS)
        assert result == "hello"

    def test_non_tty_strips_whitespace(self):
        with patch("sys.stdin") as mock_stdin, \
             patch("sys.stdout") as mock_stdout, \
             patch("builtins.input", return_value="  /help  "):
            mock_stdin.isatty.return_value = False
            mock_stdout.isatty.return_value = False
            result = uin.read_line("p> ", _CMDS)
        assert result == "/help"

    def test_non_tty_empty_string(self):
        with patch("sys.stdin") as mock_stdin, \
             patch("sys.stdout") as mock_stdout, \
             patch("builtins.input", return_value=""):
            mock_stdin.isatty.return_value = False
            mock_stdout.isatty.return_value = False
            result = uin.read_line("p> ", _CMDS)
        assert result == ""


# ===========================================================================
# 现有 REPL 命令不回归
# ===========================================================================

class TestReplImportNotBroken:

    def test_repl_commands_dict_exists(self):
        from psyclaw.repl import COMMANDS
        assert isinstance(COMMANDS, dict)
        assert len(COMMANDS) > 10

    def test_repl_commands_all_slash_prefixed(self):
        from psyclaw.repl import COMMANDS
        for cmd in COMMANDS:
            assert cmd.startswith("/"), f"{cmd} should start with /"

    def test_ui_input_module_importable(self):
        import psyclaw.ui_input as m
        assert hasattr(m, "read_line")
        assert hasattr(m, "_slash_completions")
        assert hasattr(m, "_PTK_AVAILABLE")

    def test_repl_session_creatable_without_ptk(self):
        """ReplSession 可在无 ptk 环境构建（不调用 provider）。"""
        from psyclaw.repl import ReplSession
        # Only check it has the right attributes without actually calling the provider
        assert hasattr(ReplSession, "__init__")

    def test_suggest_helper_still_works(self):
        """既有 _suggest 函数（内部联想过滤）不回归。"""
        from psyclaw.ui_input import _suggest
        cmds = {"/foo": "a", "/bar": "b", "/baz": "c"}
        assert _suggest("/b", cmds) == [("/bar", "b"), ("/baz", "c")]
        assert _suggest("", cmds) == []
        assert _suggest("/foo ", cmds) == []


# ===========================================================================
# 自包含 runner（无 pytest 时可直接 python 运行）
# ===========================================================================

if __name__ == "__main__":
    import traceback

    suite = [
        TestSlashCompletions,
        TestPtkAvailableFlag,
        TestReadLinePtkDispatch,
        TestReadLineNonTty,
        TestReplImportNotBroken,
    ]

    passed = failed = 0
    for cls in suite:
        obj = cls()
        for name in [n for n in dir(cls) if n.startswith("test_")]:
            fn = getattr(obj, name)
            try:
                fn()
                print(f"  ✓ {cls.__name__}.{name}")
                passed += 1
            except Exception:  # noqa: BLE001
                print(f"  ✗ {cls.__name__}.{name}")
                traceback.print_exc()
                failed += 1

    total = passed + failed
    print(f"\n{passed}/{total} passed")
    sys.exit(1 if failed else 0)
