"""R-4 REPL Markdown 渲染测试 — psyclaw/md_render.py。

验收:
  - **bold** / *italic* / `code` / # H1–H3 / 有序+无序列表 各有用例
  - NO_COLOR / enabled=False 下输出无 ANSI 且无残留 ** / # / - / ` 标记符
  - 现有 ui / StreamBlock 测试不回归

自包含 runner:python tests/test_ui_markdown.py
"""
from __future__ import annotations

import re
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.md_render import _inline, _render, render_md  # noqa: E402


# ANSI 剥离工具
_ANSI = re.compile(r'\033\[[0-9;]*m')


def _strip(s: str) -> str:
    return _ANSI.sub('', s)


# ---------------------------------------------------------------------------
# Inline: **bold**
# ---------------------------------------------------------------------------

class TestInlineBold:
    def test_bold_colored_contains_ansi(self):
        result = _inline("**hello**", True)
        assert "hello" in _strip(result)
        assert "\033[" in result

    def test_bold_colored_no_raw_markers(self):
        assert "**" not in _strip(_inline("**hello**", True))

    def test_bold_plain_strips_markers(self):
        assert _inline("**hello**", False) == "hello"

    def test_bold_plain_no_ansi(self):
        assert "\033[" not in _inline("**world**", False)

    def test_bold_preserves_surrounding_text(self):
        assert _inline("before **bold** after", False) == "before bold after"

    def test_bold_multiple(self):
        result = _inline("**a** and **b**", False)
        assert result == "a and b"


# ---------------------------------------------------------------------------
# Inline: *italic*
# ---------------------------------------------------------------------------

class TestInlineItalic:
    def test_italic_colored_contains_ansi(self):
        result = _inline("*hello*", True)
        assert "hello" in _strip(result)
        assert "\033[" in result

    def test_italic_plain_strips_markers(self):
        result = _inline("*hello*", False)
        assert result == "hello"
        assert "*" not in result

    def test_italic_no_ansi_in_plain(self):
        assert "\033[" not in _inline("*world*", False)

    def test_bold_not_treated_as_two_italics(self):
        result = _inline("**bold**", False)
        assert result == "bold"
        assert "*" not in result

    def test_italic_preserves_surrounding(self):
        assert _inline("see *note* here", False) == "see note here"


# ---------------------------------------------------------------------------
# Inline: `code`
# ---------------------------------------------------------------------------

class TestInlineCode:
    def test_code_colored_contains_ansi(self):
        result = _inline("`code`", True)
        assert "code" in _strip(result)
        assert "\033[" in result

    def test_code_plain_strips_backticks(self):
        assert _inline("`code`", False) == "code"

    def test_code_plain_no_ansi(self):
        assert "\033[" not in _inline("`var = 42`", False)

    def test_code_plain_value_preserved(self):
        result = _inline("`p < .001`", False)
        assert result == "p < .001"
        assert "`" not in result


# ---------------------------------------------------------------------------
# Block: headings
# ---------------------------------------------------------------------------

class TestHeadings:
    def test_h1_plain_strips_hash(self):
        result = render_md("# Hello", enabled=False)
        assert result == "Hello"
        assert "#" not in result

    def test_h2_plain_strips_hashes(self):
        result = render_md("## World", enabled=False)
        assert result == "World"
        assert "#" not in result

    def test_h3_plain_strips_hashes(self):
        result = render_md("### Section", enabled=False)
        assert result == "Section"
        assert "#" not in result

    def test_h1_colored_has_ansi(self):
        result = render_md("# Title", enabled=True)
        assert "Title" in _strip(result)
        assert "\033[" in result

    def test_h1_colored_no_raw_hash(self):
        visible = _strip(render_md("# Title", enabled=True))
        assert "#" not in visible

    def test_h2_colored_no_raw_hash(self):
        visible = _strip(render_md("## Sub", enabled=True))
        assert "#" not in visible

    def test_h3_colored_no_raw_hash(self):
        visible = _strip(render_md("### Sub-sub", enabled=True))
        assert "#" not in visible


# ---------------------------------------------------------------------------
# Block: unordered list
# ---------------------------------------------------------------------------

class TestUnorderedList:
    def test_dash_item_plain_converts_bullet(self):
        result = render_md("- item one", enabled=False)
        assert "item one" in result
        assert "• " in result

    def test_dash_item_plain_no_raw_dash(self):
        # "- " (dash-space) should not appear; bullet "• " replaces it
        result = render_md("- item", enabled=False)
        assert "- " not in result

    def test_star_item_plain_converts_bullet(self):
        result = render_md("* item two", enabled=False)
        assert "• " in result
        assert "item two" in result

    def test_plus_item_plain_converts_bullet(self):
        result = render_md("+ item", enabled=False)
        assert "• " in result

    def test_multiple_items_plain(self):
        text = "- alpha\n- beta\n- gamma"
        lines = render_md(text, enabled=False).splitlines()
        assert all("• " in ln for ln in lines)

    def test_list_colored_has_ansi(self):
        result = render_md("- item", enabled=True)
        assert "\033[" in result
        assert "item" in _strip(result)

    def test_list_colored_no_raw_dash(self):
        visible = _strip(render_md("- item", enabled=True))
        assert "- " not in visible

    def test_list_inline_bold_in_item(self):
        result = render_md("- **key**: value", enabled=False)
        assert "key" in result
        assert "**" not in result
        assert "• " in result


# ---------------------------------------------------------------------------
# Block: ordered list
# ---------------------------------------------------------------------------

class TestOrderedList:
    def test_numbered_item_plain(self):
        result = render_md("1. first", enabled=False)
        assert "first" in result
        assert "1. " in result

    def test_multiple_numbered_plain_order(self):
        text = "1. one\n2. two\n3. three"
        lines = render_md(text, enabled=False).splitlines()
        assert "one" in lines[0]
        assert "two" in lines[1]
        assert "three" in lines[2]

    def test_numbered_colored_has_ansi(self):
        result = render_md("1. first", enabled=True)
        assert "\033[" in result
        assert "first" in _strip(result)

    def test_numbered_inline_italic(self):
        result = render_md("1. *note* here", enabled=False)
        assert "note" in result
        assert "*" not in result


# ---------------------------------------------------------------------------
# NO_COLOR / degraded mode
# ---------------------------------------------------------------------------

class TestNoColorMode:
    def test_no_ansi_in_plain_mixed(self):
        text = "**bold** *italic* `code`\n# Heading\n- list"
        assert "\033[" not in render_md(text, enabled=False)

    def test_no_raw_bold_markers(self):
        assert "**" not in render_md("**hello**", enabled=False)

    def test_no_raw_italic_markers(self):
        result = render_md("*hello*", enabled=False)
        assert result == "hello"
        assert "*" not in result

    def test_no_raw_code_markers(self):
        assert "`" not in render_md("`code`", enabled=False)

    def test_no_raw_heading_hash(self):
        assert "#" not in render_md("# Heading", enabled=False)

    def test_no_raw_list_dash(self):
        result = render_md("- item", enabled=False)
        assert "- " not in result

    def test_plain_text_content_all_readable(self):
        text = "**Research** shows *significant* results: `p < .001`"
        result = render_md(text, enabled=False)
        assert "Research" in result
        assert "significant" in result
        assert "p < .001" in result
        assert "\033[" not in result
        assert "**" not in result


# ---------------------------------------------------------------------------
# Block: horizontal rule
# ---------------------------------------------------------------------------

class TestHorizontalRule:
    def test_hr_plain_renders_unicode_line(self):
        result = render_md("---", enabled=False)
        assert "─" in result

    def test_hr_colored_not_raw_dashes(self):
        # In colored mode rule() returns a dim unicode line
        result = render_md("---", enabled=True)
        assert len(result) > 0

    def test_three_star_hr(self):
        result = render_md("***", enabled=False)
        assert "─" in result

    def test_three_underscore_hr(self):
        result = render_md("___", enabled=False)
        assert "─" in result


# ---------------------------------------------------------------------------
# Block: blockquote
# ---------------------------------------------------------------------------

class TestBlockquote:
    def test_blockquote_plain_strips_angle(self):
        result = render_md("> quoted text", enabled=False)
        assert "quoted text" in result
        assert not result.startswith(">")

    def test_blockquote_colored_no_raw_angle(self):
        visible = _strip(render_md("> important", enabled=True))
        assert "important" in visible
        assert visible.strip().startswith(">") is False

    def test_blockquote_inline_bold(self):
        result = render_md("> **note**: see below", enabled=False)
        assert "note" in result
        assert "**" not in result
        assert ">" not in result


# ---------------------------------------------------------------------------
# Block: code fence
# ---------------------------------------------------------------------------

class TestCodeFence:
    def test_fence_content_preserved_plain(self):
        text = "```python\nprint('hello')\n```"
        result = render_md(text, enabled=False)
        assert "print('hello')" in result

    def test_fence_content_preserved_colored(self):
        text = "```\ncode here\n```"
        result = render_md(text, enabled=True)
        assert "code here" in _strip(result)

    def test_fence_markers_hidden_plain(self):
        text = "```python\nx = 1\n```"
        result = render_md(text, enabled=False)
        # No raw ``` should appear in plain output
        assert "```" not in result

    def test_fence_multiple_lines(self):
        text = "```\nline1\nline2\nline3\n```"
        result = render_md(text, enabled=False)
        assert "line1" in result
        assert "line2" in result
        assert "line3" in result


# ---------------------------------------------------------------------------
# Mixed content / edge cases
# ---------------------------------------------------------------------------

class TestMixedAndEdgeCases:
    def test_full_response_plain_all_content_present(self):
        text = (
            "# Results\n\n"
            "**Key finding**: effect size *d* = 0.45.\n\n"
            "- Sample size: 100\n"
            "- Power: 80%\n\n"
            "`psyclaw stat --method ttest`"
        )
        result = render_md(text, enabled=False)
        assert "Results" in result
        assert "Key finding" in result
        assert "0.45" in result
        assert "Sample size" in result
        assert "psyclaw stat --method ttest" in result

    def test_full_response_plain_no_raw_markers(self):
        text = (
            "# Results\n\n"
            "**Key finding**: effect size *d* = 0.45.\n\n"
            "- Sample size: 100\n"
            "`psyclaw stat`"
        )
        result = render_md(text, enabled=False)
        assert "**" not in result
        assert "`" not in result
        assert "#" not in result
        assert "- " not in result  # raw dash-space

    def test_empty_string(self):
        assert render_md("", enabled=False) == ""
        assert render_md("", enabled=True) == ""

    def test_plain_text_unchanged(self):
        assert render_md("plain text", enabled=False) == "plain text"

    def test_multiline_no_markers(self):
        text = "line one\nline two\nline three"
        result = render_md(text, enabled=False)
        assert "line one" in result
        assert "line two" in result
        assert "line three" in result

    def test_inline_code_in_sentence(self):
        result = render_md("Use `python -m psyclaw` to start.", enabled=False)
        assert "python -m psyclaw" in result
        assert "`" not in result

    def test_mixed_bold_italic_inline(self):
        result = render_md("**bold** and *italic* together", enabled=False)
        assert result == "bold and italic together"

    def test_render_md_default_uses_ui_enabled(self):
        # render_md() with no enabled arg should not raise
        result = render_md("**test**")
        assert "test" in _strip(result)


# ---------------------------------------------------------------------------
# StreamBlock smoke test (no live TTY required)
# ---------------------------------------------------------------------------

class TestStreamBlockSmoke:
    def test_streamblock_buffers_and_renders(self):
        import io
        from psyclaw import ui as _ui
        _orig_enabled = _ui._ENABLED

        captured = io.StringIO()
        _ui._ENABLED = False
        try:
            blk = _ui.StreamBlock.__new__(_ui.StreamBlock)
            blk._out = captured
            blk.color = "brcyan"
            blk._buf = ""
            blk._indicator = False
            # Simulate streaming
            blk._buf += "**bold** result\n- item one\n"
            blk.close()
        finally:
            _ui._ENABLED = _orig_enabled

        out = captured.getvalue()
        assert "bold" in out
        assert "**" not in out
        assert "• " in out
        assert "- " not in out   # raw dash removed

    def test_streamblock_write_accumulates(self):
        import io
        from psyclaw import ui as _ui
        _orig_enabled = _ui._ENABLED
        _ui._ENABLED = False

        try:
            captured = io.StringIO()
            blk = _ui.StreamBlock.__new__(_ui.StreamBlock)
            blk._out = captured
            blk.color = "brcyan"
            blk._buf = ""
            blk._indicator = False
            blk.write("chunk1 ")
            blk.write("chunk2")
            assert blk._buf == "chunk1 chunk2"
        finally:
            _ui._ENABLED = _orig_enabled


# ---------------------------------------------------------------------------
# 自包含 runner (python tests/test_ui_markdown.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _SUITES = [
        TestInlineBold,
        TestInlineItalic,
        TestInlineCode,
        TestHeadings,
        TestUnorderedList,
        TestOrderedList,
        TestNoColorMode,
        TestHorizontalRule,
        TestBlockquote,
        TestCodeFence,
        TestMixedAndEdgeCases,
        TestStreamBlockSmoke,
    ]

    passed = failed = 0
    for suite_cls in _SUITES:
        suite = suite_cls()
        for name in sorted(m for m in dir(suite_cls) if m.startswith("test_")):
            fn = getattr(suite, name)
            try:
                fn()
                passed += 1
                print(f"  PASS  {suite_cls.__name__}.{name}")
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"  FAIL  {suite_cls.__name__}.{name}")
                traceback.print_exc()

    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)
