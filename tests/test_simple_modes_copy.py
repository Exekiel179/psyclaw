from __future__ import annotations

from psyclaw import ui
from psyclaw.cli import _print_help


def _plain(text: str) -> str:
    import re
    return re.sub(r"\033\[[0-9;]*m", "", text)


def test_startup_uses_two_short_mode_phrases():
    text = _plain(ui.startup("0.22.0"))
    assert "chat 一起做" in text
    assert "run 按步骤" in text
    assert "auto 自己推进" not in text


def test_guide_uses_same_two_short_mode_phrases(capsys):
    assert _print_help() == 0
    text = _plain(capsys.readouterr().out)
    assert "chat: 一起做" in text
    assert "run: 按步骤做" in text
    assert "run: 自己推进下一步" in text
