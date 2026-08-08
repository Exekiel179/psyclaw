"""后台工作状态指示器回归测试。"""
from __future__ import annotations

import io

from psyclaw import ui


def test_activity_indicator_non_tty_shows_started_and_finished(monkeypatch):
    out = io.StringIO()
    monkeypatch.setattr(ui, "_ENABLED", False)
    indicator = ui.ActivityIndicator("MCP 初始化")
    indicator._out = out
    indicator.start()
    indicator.stop("MCP 已完成")
    text = out.getvalue()
    assert "MCP 初始化" in text
    assert "MCP 已完成" in text
    assert "✓ MCP 已完成" in text
    assert not indicator.active


def test_activity_indicator_marks_network_failure(monkeypatch):
    out = io.StringIO()
    monkeypatch.setattr(ui, "_ENABLED", False)
    indicator = ui.ActivityIndicator("正在连接")
    indicator._out = out
    indicator.start()
    indicator.stop("网络连接失败：DNS 解析失败")
    text = out.getvalue()
    assert "✗ 网络连接失败" in text and "DNS" in text


def test_activity_indicator_stop_is_idempotent(monkeypatch):
    monkeypatch.setattr(ui, "_ENABLED", False)
    indicator = ui.ActivityIndicator()
    indicator._out = io.StringIO()
    indicator.stop()
    indicator.start()
    indicator.stop()
    indicator.stop()
    assert not indicator.active


def test_stream_block_hides_choices_protocol_but_keeps_question_context(monkeypatch):
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    block = ui.StreamBlock("PsyClaw")
    block.write('还缺一个关键信息。\n```choices\n'
                '{"question":"选哪个?","options":["甲","乙"]}\n```')
    block.close()
    text = out.getvalue()
    assert "还缺一个关键信息" in text
    assert '"options"' not in text and "```choices" not in text
