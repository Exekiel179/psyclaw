"""feat-144:能力自知——模型必须知道 psyclaw 自带哪些能力,不许重造轮子。

真实事故(profile/outputs/chat_20260716-013723.md):用户说「word 格式,发表水平」,
模型自己手搓 md_to_docx.py(python-docx),无视 psyclaw export --docx(APA7+中文字体
+图片嵌入);画图自己 import matplotlib → 满图豆腐块,无视 figures.apply_style('apa7')
(中文字体前置早已修好);统计手写 pandas,无视 pystat MCP;全程没跑过 check。
"""
from __future__ import annotations

from psyclaw.context import capability_map


def test_capability_map_covers_docx_export():
    cap = capability_map()
    assert "export" in cap
    assert "docx" in cap.lower()


def test_capability_map_covers_figure_style():
    cap = capability_map()
    assert "apply_style" in cap or "figures" in cap
    assert "apa7" in cap.lower()


def test_capability_map_covers_quality_check():
    cap = capability_map()
    assert "check" in cap


def test_capability_map_forbids_reinventing():
    """必须明确禁止重造——不是「你可以用」,而是「不要自己手搓」。"""
    cap = capability_map()
    assert "不要" in cap or "禁止" in cap or "别" in cap


def test_capability_map_mentions_stats_external():
    cap = capability_map()
    assert "pystat" in cap or "统计" in cap


def test_capability_map_nonempty_and_bounded():
    cap = capability_map()
    assert cap.strip()
    assert len(cap) <= 700           # 每轮必注入,有预算


def test_system_prompt_includes_capability_map(monkeypatch):
    monkeypatch.setattr("psyclaw.config.load_config",
                        lambda: {"assist_level": "standard", "provider": "mock"})
    from psyclaw.repl import _build_system_prompt
    sp = _build_system_prompt()
    assert "export" in sp and "apply_style" in sp
