"""bug 修:自研 raw reader 的光标定位对中文按 1 列算 → 中文输入后重画乱码。

_visible_len 改用东亚宽度感知(中日韩按 2 列),与输出框(feat-157)同口径,
中文输入后 `\\033[nC` 右移列数才对得上,提示符不再被覆盖成「公yclaw ❯」。
"""
from __future__ import annotations

from psyclaw.ui_input import _visible_len


def test_ascii_width():
    assert _visible_len("psyclaw ❯ ") >= len("psyclaw ")   # ❯ 也计入


def test_cjk_counts_two_columns():
    assert _visible_len("公正世界信念") == 12               # 6 汉字 × 2


def test_strips_ansi():
    # 带 ANSI 颜色码的提示,宽度只算可见部分
    assert _visible_len("\033[36m公正\033[0m") == 4         # 2 汉字 × 2


def test_mixed():
    assert _visible_len("ab中c") == 2 + 2 + 1                # a b (中×2) c
