"""bug 修:lit 只打公开 API,用户以为会自动调 Kimi WebBridge(机构库)。

lit(OpenAlex/EuropePMC)与 webbridge 是两条独立通道。检索后主动指路机构库桥接,
中文主题尤其(公开 API 检不到知网/万方)。
"""
from __future__ import annotations

from psyclaw.psych.lit_cli import institutional_hint, _has_cjk


def test_cjk_query_points_to_webbridge_and_cnki():
    h = institutional_hint("公正世界信念")
    assert "webbridge" in h
    assert "知网" in h or "万方" in h
    assert "--plan" in h


def test_english_query_points_to_webbridge():
    h = institutional_hint("belief in a just world")
    assert "webbridge" in h and "--plan" in h


def test_has_cjk():
    assert _has_cjk("公正世界信念")
    assert not _has_cjk("belief in a just world")
