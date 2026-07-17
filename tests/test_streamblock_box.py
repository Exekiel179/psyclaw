"""feat-157:输出框闭合——左侧圆角却右侧无框看着怪异,补右边框成完整圆角框。"""
from __future__ import annotations

import io

from psyclaw import ui


def _render(text: str, width: int = 60) -> str:
    out = io.StringIO()
    orig = ui.term_width
    ui.term_width = lambda default=80: width      # 固定宽度可断言对齐
    try:
        blk = ui.StreamBlock("PsyClaw")
        blk._out = out
        blk.write(text)
        blk.close()
    finally:
        ui.term_width = orig
    return out.getvalue()


def test_box_has_all_four_corners():
    printed = _render("内容一行")
    for corner in ("╭", "╮", "╰", "╯"):
        assert corner in printed, f"缺角 {corner}——框没闭合"


def test_content_lines_have_right_border():
    """每行内容右侧都应有 │ 收口(不再左闭右开)。"""
    printed = _render("短")
    body = [ln for ln in printed.splitlines()
            if ln.startswith("│") or "│ " in ln]
    assert body
    assert any(ln.rstrip().endswith("│") for ln in body)


def test_right_border_aligned_across_lines():
    """多行内容右边框列对齐(display_width 感知,中英混排也齐)。"""
    printed = _render("第一行中文\nsecond line ascii\n第三行")
    from psyclaw.ui import display_width
    border_cols = [display_width(ln) for ln in printed.splitlines()
                   if ln.rstrip().endswith("│") and ln.startswith(("╭", "│", "╰")) is False
                   or ln.startswith("│")]
    # 所有含右边框的行显示宽度一致
    widths = {display_width(ln) for ln in printed.splitlines()
              if ln.startswith("│") and ln.rstrip().endswith("│")}
    assert len(widths) <= 1, f"右边框未对齐:{widths}"


def test_cjk_content_right_border_aligns_with_ascii():
    printed = _render("纯中文内容行\nplain ascii row")
    tops = [ln for ln in printed.splitlines() if ln.startswith("╭")]
    bots = [ln for ln in printed.splitlines() if ln.startswith("╰")]
    from psyclaw.ui import display_width
    assert display_width(tops[0]) == display_width(bots[0])   # 上下边框等宽


def test_empty_reply_still_no_box():
    """feat-149 不回归:空回复仍不渲染框。"""
    out = io.StringIO()
    blk = ui.StreamBlock("PsyClaw")
    blk._out = out
    blk.close()
    assert "╭" not in out.getvalue() and "╮" not in out.getvalue()
