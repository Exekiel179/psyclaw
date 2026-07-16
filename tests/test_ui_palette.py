"""feat-147:输出配色美化——引入精炼 256 色调 + 语义色 info/label,
命令实时输出单独着色(区别于模型正文)。用户反馈:输出框色彩单调不美观。
"""
from __future__ import annotations

import re

from psyclaw import ui

_ANSI = re.compile(r"\033\[[0-9;]*m")


def _strip(s: str) -> str:
    return _ANSI.sub("", s)


# ---- 256 色调可用且 paint 逻辑不破 --------------------------------------------

def test_256_color_codes_registered():
    for name in ("teal", "violet", "slate"):
        assert name in ui._CODES
        assert ui._CODES[name].startswith("38;5;")   # 256 前景色格式


def test_paint_256_produces_ansi(monkeypatch):
    monkeypatch.setattr(ui, "_ENABLED", True)
    out = ui.paint("x", "teal")
    assert "\033[38;5;" in out and ui.RESET in out
    assert _strip(out) == "x"


def test_paint_bold_plus_256_combines(monkeypatch):
    monkeypatch.setattr(ui, "_ENABLED", True)
    out = ui.paint("x", "bold", "violet")
    assert out.startswith("\033[1;38;5;")            # bold;256 合法组合
    assert _strip(out) == "x"


# ---- 新语义色 -----------------------------------------------------------------

def test_info_and_label_helpers(monkeypatch):
    monkeypatch.setattr(ui, "_ENABLED", True)
    assert "\033[" in ui.info("提示")
    assert "\033[" in ui.label("字段")
    assert _strip(ui.info("提示")) == "提示"


def test_helpers_plain_when_disabled(monkeypatch):
    monkeypatch.setattr(ui, "_ENABLED", False)
    assert ui.info("x") == "x"
    assert ui.label("x") == "x"


# ---- 命令实时输出单独着色(feat-145 的 │ 行) --------------------------------

def test_run_output_has_distinct_color(monkeypatch):
    """命令输出行不再是灰 dim,而是可辨识的独立色调。"""
    monkeypatch.setattr(ui, "_ENABLED", True)
    line = ui.run_output("抓取第 1/4…")
    assert "\033[" in line
    assert "抓取第 1/4" in _strip(line)


def test_run_output_plain_when_disabled(monkeypatch):
    monkeypatch.setattr(ui, "_ENABLED", False)
    assert ui.run_output("x") == "  │ x"            # 结构仍在,无色码
