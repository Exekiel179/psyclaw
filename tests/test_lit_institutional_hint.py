"""bug 修:lit 只打公开 API,机构库补全不自动启动浏览器连接。

lit(OpenAlex/EuropePMC)与机构库检索是两条独立通道。检索后指向浏览器 MCP 或手动导入,
中文主题尤其(公开 API 检不到知网/万方)。
"""
from __future__ import annotations

from psyclaw.psych.lit_cli import institutional_hint, _has_cjk


def test_cjk_query_points_to_browser_mcp_and_cnki():
    h = institutional_hint("公正世界信念")
    assert "浏览器 MCP" in h
    assert "知网" in h or "万方" in h
    assert "--plan" in h


def test_english_query_points_to_browser_mcp():
    h = institutional_hint("belief in a just world")
    assert "浏览器 MCP" in h and "--plan" in h


def test_has_cjk():
    assert _has_cjk("公正世界信念")
    assert not _has_cjk("belief in a just world")
