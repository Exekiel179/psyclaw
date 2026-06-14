"""tests/test_ui.py — ui.py 终端 UI 函数单元测试 (P5-E4)。

pytest 运行于非 TTY 环境（_ENABLED=False），所有 paint/ok/warn/err/accent/dim
均返回纯文本（无 ANSI）。通过 monkeypatch 测试 ANSI 启用路径。
"""
from __future__ import annotations

import re

import pytest

import psyclaw.ui as ui

_ANSI = re.compile(r'\033\[[0-9;]*m')


def _has_ansi(s: str) -> bool:
    return bool(_ANSI.search(s))


def _strip(s: str) -> str:
    return _ANSI.sub("", s)


# ---------------------------------------------------------------------------
# paint — 非 TTY（_ENABLED=False）
# ---------------------------------------------------------------------------

class TestPaintDisabled:
    def test_returns_plain_text(self, monkeypatch):
        monkeypatch.setattr(ui, "_ENABLED", False)
        assert ui.paint("hello", "bold") == "hello"

    def test_no_styles_returns_text(self, monkeypatch):
        monkeypatch.setattr(ui, "_ENABLED", False)
        assert ui.paint("abc") == "abc"

    def test_multiple_styles_plain(self, monkeypatch):
        monkeypatch.setattr(ui, "_ENABLED", False)
        assert ui.paint("abc", "bold", "red") == "abc"


# ---------------------------------------------------------------------------
# paint — TTY 模式（强制 _ENABLED=True）
# ---------------------------------------------------------------------------

class TestPaintEnabled:
    def test_bold_has_ansi(self, monkeypatch):
        monkeypatch.setattr(ui, "_ENABLED", True)
        result = ui.paint("hello", "bold")
        assert _has_ansi(result)
        assert "hello" in _strip(result)

    def test_reset_appended(self, monkeypatch):
        monkeypatch.setattr(ui, "_ENABLED", True)
        result = ui.paint("x", "red")
        assert ui.RESET in result

    def test_multiple_styles(self, monkeypatch):
        monkeypatch.setattr(ui, "_ENABLED", True)
        result = ui.paint("x", "bold", "brgreen")
        # 两种样式用 ; 连接
        assert ";" in result
        assert "x" in _strip(result)

    def test_unknown_style_ignored(self, monkeypatch):
        monkeypatch.setattr(ui, "_ENABLED", True)
        result = ui.paint("x", "nosuchstyle")
        # 无有效样式 → 不加 ANSI
        assert result == "x"


# ---------------------------------------------------------------------------
# 语义快捷函数（测试非 TTY 纯文本通路）
# ---------------------------------------------------------------------------

class TestSemanticFunctions:
    @pytest.fixture(autouse=True)
    def disable(self, monkeypatch):
        monkeypatch.setattr(ui, "_ENABLED", False)

    def test_ok_returns_text(self):
        assert ui.ok("成功") == "成功"

    def test_warn_returns_text(self):
        assert ui.warn("警告") == "警告"

    def test_err_returns_text(self):
        assert ui.err("错误") == "错误"

    def test_accent_returns_text(self):
        assert ui.accent("强调") == "强调"

    def test_title_returns_text(self):
        assert ui.title("标题") == "标题"

    def test_dim_returns_text(self):
        assert ui.dim("次要") == "次要"

    def test_rule_contains_char(self):
        r = ui.rule()
        assert "─" in _strip(r)

    def test_rule_custom_char(self):
        r = ui.rule(width=10, char="=")
        assert "=" in _strip(r)


# ---------------------------------------------------------------------------
# 语义快捷函数 — ANSI 启用路径
# ---------------------------------------------------------------------------

class TestSemanticFunctionsEnabled:
    @pytest.fixture(autouse=True)
    def enable(self, monkeypatch):
        monkeypatch.setattr(ui, "_ENABLED", True)

    def test_ok_has_ansi(self):
        assert _has_ansi(ui.ok("好"))

    def test_warn_has_ansi(self):
        assert _has_ansi(ui.warn("注意"))

    def test_err_has_ansi(self):
        assert _has_ansi(ui.err("错误"))


# ---------------------------------------------------------------------------
# panel
# ---------------------------------------------------------------------------

class TestPanel:
    def test_contains_title(self):
        result = ui.panel("研究报告", "内容")
        assert "研究报告" in _strip(result)

    def test_contains_content(self):
        result = ui.panel("标题", "这是内容行")
        assert "这是内容行" in _strip(result)

    def test_multi_line_content(self):
        result = ui.panel("标题", "第一行\n第二行")
        assert "第一行" in _strip(result)
        assert "第二行" in _strip(result)

    def test_panel_structure(self):
        result = ui.panel("标题", "内容")
        lines = result.split("\n")
        # 至少有：头行 + 内容行(s) + 尾行
        assert len(lines) >= 3

    def test_returns_str(self):
        assert isinstance(ui.panel("x", "y"), str)


# ---------------------------------------------------------------------------
# term_width
# ---------------------------------------------------------------------------

class TestTermWidth:
    def test_returns_int(self):
        w = ui.term_width()
        assert isinstance(w, int)

    def test_positive(self):
        assert ui.term_width() > 0

    def test_default_fallback(self):
        w = ui.term_width(default=42)
        assert w >= 1

    def test_max_is_100(self):
        # 代码: min(shutil.get_terminal_size().columns, 100)
        assert ui.term_width() <= 100


# ---------------------------------------------------------------------------
# banner
# ---------------------------------------------------------------------------

class TestBanner:
    def test_contains_version(self):
        result = ui.banner("1.2.3")
        assert "1.2.3" in _strip(result)

    def test_contains_psyclaw(self):
        result = ui.banner("0.0.1")
        assert "PsyClaw" in _strip(result)

    def test_returns_str(self):
        assert isinstance(ui.banner("0.1"), str)
