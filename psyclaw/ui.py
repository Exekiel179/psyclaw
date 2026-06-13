"""终端 UI — ANSI 配色(stdlib only)。

- Windows:os.system("") 激活 VT 处理(Win10+ 终端原生支持)
- 自动降级:非 TTY(管道/重定向)或设置 NO_COLOR 时输出纯文本
"""

from __future__ import annotations

import os
import sys

_ENABLED = (
    sys.stdout.isatty()
    and os.environ.get("NO_COLOR") is None
    and os.environ.get("TERM") != "dumb"
)
if _ENABLED and os.name == "nt":
    os.system("")  # 激活 Windows VT 模式

RESET = "\033[0m"
_CODES = {
    "bold": "1", "dim": "2", "italic": "3",
    "red": "31", "green": "32", "yellow": "33", "blue": "34",
    "magenta": "35", "cyan": "36", "white": "37",
    "brred": "91", "brgreen": "92", "bryellow": "93",
    "brblue": "94", "brmagenta": "95", "brcyan": "96",
}


def paint(text: str, *styles: str) -> str:
    if not _ENABLED or not styles:
        return text
    seq = ";".join(_CODES[s] for s in styles if s in _CODES)
    return f"\033[{seq}m{text}{RESET}" if seq else text


# 语义快捷
def ok(text: str) -> str:
    return paint(text, "brgreen")


def warn(text: str) -> str:
    return paint(text, "bryellow")


def err(text: str) -> str:
    return paint(text, "brred")


def accent(text: str) -> str:
    return paint(text, "brcyan")


def title(text: str) -> str:
    return paint(text, "bold", "brmagenta")


def dim(text: str) -> str:
    return paint(text, "dim")


def rule(width: int = 56, char: str = "─") -> str:
    return dim(char * width)


BANNER_ART = r"""
   ____             ____ _
  |  _ \ ___ _   _ / ___| | __ ___      __
  | |_) / __| | | | |   | |/ _` \ \ /\ / /
  |  __/\__ \ |_| | |___| | (_| |\ V  V /
  |_|   |___/\__, |\____|_|\__,_| \_/\_/
             |___/
"""


def term_width(default: int = 80) -> int:
    import shutil
    try:
        return min(shutil.get_terminal_size().columns, 100)
    except Exception:  # noqa: BLE001
        return default


# ---------------------------------------------------------------------------
# 渲染块(claude-code 风格圆角面板)
# ---------------------------------------------------------------------------

def panel(title: str, content: str, color: str = "brcyan") -> str:
    """静态面板:一次性渲染整块内容。"""
    w = term_width() - 2
    head = paint("╭─ ", color) + paint(title, color, "bold") + " " \
        + paint("─" * max(0, w - len(title) - 4), color)
    lines = [head]
    for ln in content.splitlines() or [""]:
        lines.append(paint("│ ", color) + ln)
    lines.append(paint("╰" + "─" * max(0, w - 1), color))
    return "\n".join(lines)


class StreamBlock:
    """流式渲染块:LLM 回复边流边进边框。

    用法:
        blk = StreamBlock("PsyClaw"); blk.write(chunk)...; blk.close()
    """

    def __init__(self, title: str = "PsyClaw", color: str = "brcyan") -> None:
        import sys as _sys
        self._out = _sys.stdout
        self.color = color
        self._buf = ""
        w = term_width() - 2
        head = paint("╭─ ", color) + paint(title, color, "bold") + " " \
            + paint("─" * max(0, w - len(title) - 4), color)
        self._out.write(head + "\n")
        self._out.write(paint("│ ", color))
        self._out.flush()

    def write(self, chunk: str) -> None:
        prefix = paint("│ ", self.color)
        # 行缓冲:遇换行补左边框
        text = chunk.replace("\n", "\n" + prefix)
        self._out.write(text)
        self._out.flush()

    def close(self) -> None:
        w = term_width() - 2
        self._out.write("\n" + paint("╰" + "─" * max(0, w - 1), self.color) + "\n")
        self._out.flush()


def banner(version: str) -> str:
    lines = [paint(BANNER_ART, "brcyan")]
    lines.append("  " + title("PsyClaw") + dim(" · ")
                 + paint(f"v{version}", "bryellow")
                 + dim("  心理学研究全流程 Agent CLI"))
    lines.append("  " + dim("文献调研 · 实验设计 · 统计分析 · 论文写作 — 规范门禁内置"))
    lines.append("  " + rule())
    return "\n".join(lines)
