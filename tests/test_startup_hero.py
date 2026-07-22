"""启动界面品牌 hero:巨型英文识别图形 + 中文品牌锁定 + 状态卡。

守护:wordmark block art 必须矩形对齐；宽终端保留巨型识别图形，中文品牌锁定
紧随其后，窄终端降级为单行。
"""
from __future__ import annotations

from psyclaw import ui


def test_banner_art_is_rectangular():
    lines = ui.BANNER_ART.split("\n")
    widths = {len(ln) for ln in lines}
    assert len(widths) == 1, f"wordmark 各行不等宽会错位:{widths}"
    assert len(lines) == 6


def test_wide_terminal_shows_giant_wordmark_and_cn_lockup(monkeypatch):
    monkeypatch.setattr(ui, "term_width", lambda default=80: 90)
    out = ui.startup("0.16.0")
    assert "█" in out
    assert out.index("█") < out.index("灵智龙虾 · 用心分析")
    assert "灵智龙虾" in out
    assert "用心分析" in out
    assert "兼顾其他人文社科" in out
    assert "研究编排" in out                       # eyebrow 一行说清定位
    # 开屏克制:wordmark 已喊过品牌,不再堆中英同义反复 + 功能清单 + 口号
    assert "RESEARCH ORCHESTRATION" not in out
    assert "统计外移" not in out
    assert "psychology workflow harness" not in out


def test_narrow_terminal_falls_back_to_compact_brand_lockup(monkeypatch):
    monkeypatch.setattr(ui, "term_width", lambda default=80: 50)
    out = ui.startup("0.16.0")
    assert "█" not in out
    assert "灵智龙虾 · 用心分析" in out
    assert "灵智龙虾" in out


def test_wordmark_helper_indents_and_colors_each_line():
    wm = ui.wordmark("teal")
    for ln in wm.split("\n"):
        assert ln.startswith("  ")               # 每行左缩进 2
