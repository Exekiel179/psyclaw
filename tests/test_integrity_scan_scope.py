"""诚信启发式只扫正文,不扫参考文献表(feat-193)。

真实事故(用户实测):稿件参考文献里有
「Michaels & Spector (1982). Causes of employee turnover...」——
这是一篇**真实且贴切**的文献,但标题里的 "Causes" 被因果越界检查命中并判为 block。
更糟的是模型为了过检,打算**换掉这篇真实文献**改用标题不含 causes 的另一篇。

检查器倒逼学术失真,比不检查更糟。作者对文献标题没有改写权,
标题里的词不构成作者本人的因果主张,故扫描范围必须排除参考文献区。
"""
from __future__ import annotations

from psyclaw.output.jars import integrity_flags

BODY_CLEAN = ("# 结果\n\n本研究为横断面设计。工作满意度与离职意向呈显著负相关"
              "(r = -.42)。横断面数据不支持因果推断。\n")
REFS = ("\n## 参考文献\n\nMichaels, C. E., & Spector, P. E. (1982). "
        "Causes of employee turnover: A test of the Mobley model. "
        "Journal of Applied Psychology, 67(1), 53-59.\n")


def _ids(text):
    return [f["id"] for f in integrity_flags(text)]


def test_reference_title_does_not_trigger_causal_flag():
    """真实文献标题里的 Causes 不该被判成作者的因果越界。"""
    assert "I.causal_language_design" not in _ids(BODY_CLEAN + REFS)


def test_english_references_section_also_excluded():
    refs_en = ("\n## References\n\nSmith, J. (2020). What causes burnout: "
               "A longitudinal study. Journal of X.\n")
    assert "I.causal_language_design" not in _ids(BODY_CLEAN + refs_en)


def test_real_causal_overreach_in_body_still_blocked():
    """正文里真的越界必须照拦——修的是扫描范围,不是放宽判据。"""
    bad = ("# 结果\n\n本横断面研究证明该干预导致抑郁水平显著降低。\n")
    assert "I.causal_language_design" in _ids(bad)


def test_body_overreach_still_caught_even_with_references_present():
    bad = ("# 结果\n\n本横断面研究证明该干预导致抑郁水平显著降低。\n")
    assert "I.causal_language_design" in _ids(bad + REFS)


def test_manuscript_without_reference_section_unchanged():
    """没有参考文献区的草稿:行为与此前一致,不因截断逻辑误伤正文。"""
    bad = "本相关研究证明干预导致焦虑显著减少。"
    assert "I.causal_language_design" in _ids(bad)
