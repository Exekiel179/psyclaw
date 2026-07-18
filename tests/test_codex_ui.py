"""Codex 风界面:极简 › 提示符 + prompt_toolkit 底部固定状态行(模型 · 模式 · 目录)。"""
from __future__ import annotations

import re
from types import SimpleNamespace

import psyclaw.ui_input as uin
from psyclaw.repl import ReplSession


def _plain(s: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", s)


def test_statusline_shows_model_mode_cwd():
    fake = SimpleNamespace(
        provider=SimpleNamespace(describe_short=lambda: "deepseek · deepseek-v4"),
        session_name=None, yolo=False, plan_mode=False, agent_mode=False, file_access="safe")
    line = _plain(ReplSession._statusline(fake))
    assert "deepseek" in line and "chat" in line and "access:safe" in line
    assert "~" in line or "/" in line               # 当前目录


def test_statusline_failsafe_and_flags():
    def _boom():
        raise RuntimeError("no provider")
    fake = SimpleNamespace(
        provider=SimpleNamespace(describe_short=_boom),
        session_name="正念研究", yolo=True, plan_mode=False, agent_mode=True, file_access="full")
    line = _plain(ReplSession._statusline(fake))
    assert "psyclaw" in line                          # provider 失败兜底
    assert "auto" in line and "advanced" in line and "正念研究" in line


def test_read_line_passes_bottom_toolbar_to_ptk(monkeypatch):
    captured = {}

    def _fake(p, c, bt=None):
        captured["bt"] = bt
        return "x"
    monkeypatch.setattr(uin, "_PTK_AVAILABLE", True)
    monkeypatch.setattr(uin, "_ptk_read_line", _fake)
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("sys.stdout", SimpleNamespace(isatty=lambda: True))
    uin.read_line("› ", {}, bottom_toolbar=lambda: "状态栏")
    assert captured["bt"] is not None and captured["bt"]() == "状态栏"
