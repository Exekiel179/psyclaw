"""feat-153:命令联想诚实化——提示随实际输入 backend 自适应 + 引导装 ptk。

真实事故:用户 uv 环境没 prompt_toolkit,实际走 readline(只 Tab 补全、无 ↑↓
实时下拉),但启动提示写死「输入 / 弹出命令联想(↑↓选择)」——过度承诺,用户以为
坏了。提示应随 backend 说实话,并告诉用户装 ptk 能得实时下拉。
"""
from __future__ import annotations

import psyclaw.ui_input as ui_input


def test_backend_plain_when_not_tty():
    assert ui_input.input_backend(is_tty=False) == "plain"


def test_backend_ptk_when_available(monkeypatch):
    monkeypatch.setattr(ui_input, "_PTK_AVAILABLE", True)
    assert ui_input.input_backend(is_tty=True) == "ptk"


def test_backend_readline_when_no_ptk(monkeypatch):
    monkeypatch.setattr(ui_input, "_PTK_AVAILABLE", False)
    # readline 在本机可用 → 走 readline(非 raw)
    assert ui_input.input_backend(is_tty=True) in ("readline", "raw")


# ---- 提示随 backend 说实话 ----------------------------------------------------

def test_hint_ptk_promises_dropdown():
    h = ui_input.input_hint("ptk")
    assert "↑↓" in h and ("下拉" in h or "联想" in h)


def test_hint_readline_says_tab_not_dropdown():
    """readline 只有 Tab 补全,不该承诺 ↑↓ 选择下拉。"""
    h = ui_input.input_hint("readline")
    assert "Tab" in h
    assert "弹出" not in h and "下拉" not in h    # 不过度承诺实时下拉


def test_hint_raw_has_dropdown():
    h = ui_input.input_hint("raw")
    assert "↑↓" in h


def test_hint_plain_minimal():
    h = ui_input.input_hint("plain")
    assert "/exit" in h


# ---- 装 ptk 引导:仅在 TTY 且无 ptk 时提示 -----------------------------------

def test_ptk_nudge_when_readline():
    n = ui_input.ptk_install_nudge("readline")
    assert n and "prompt_toolkit" in n


def test_no_ptk_nudge_when_ptk_active():
    assert ui_input.ptk_install_nudge("ptk") == ""


def test_no_ptk_nudge_when_plain():
    assert ui_input.ptk_install_nudge("plain") == ""
