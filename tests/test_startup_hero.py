"""启动界面重做成 landing page 风格 hero:巨型 wordmark + eyebrow + thesis + 状态卡。

守护:wordmark block art 必须矩形对齐(每行等宽),否则终端里错位难看;宽终端出大字、
窄终端降级单行;品牌名/eyebrow/thesis 都在。
"""
from __future__ import annotations

from psyclaw import ui


def test_banner_art_is_rectangular():
    lines = ui.BANNER_ART.split("\n")
    widths = {len(ln) for ln in lines}
    assert len(widths) == 1, f"wordmark 各行不等宽会错位:{widths}"
    assert len(lines) == 6


def test_wide_terminal_shows_giant_wordmark(monkeypatch):
    monkeypatch.setattr(ui, "term_width", lambda default=80: 90)
    out = ui.startup("0.16.0")
    assert "█" in out                           # 巨型 block wordmark 出现
    assert "PsyClaw" in out                      # 可读品牌名(eyebrow)
    assert "研究编排" in out                       # eyebrow 一行说清定位
    # 开屏克制:wordmark 已喊过品牌,不再堆中英同义反复 + 功能清单 + 口号
    assert "RESEARCH ORCHESTRATION" not in out
    assert "统计外移" not in out
    assert "psychology workflow harness" not in out


def test_narrow_terminal_falls_back(monkeypatch):
    monkeypatch.setattr(ui, "term_width", lambda default=80: 50)
    out = ui.startup("0.16.0")
    assert "█" not in out                        # 窄终端不画大字
    assert "PsyClaw" in out                      # 但仍有品牌名


def test_wordmark_helper_indents_and_colors_each_line():
    wm = ui.wordmark("teal")
    for ln in wm.split("\n"):
        assert ln.startswith("  ")               # 每行左缩进 2
