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


def _char_width(ch: str) -> int:
    """单字符显示列宽：组合符 0，东亚宽/全角 2，其余 1。"""
    import unicodedata
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


_ANSI_RE = None


def display_width(s: str) -> int:
    """字符串显示列宽（剥离 ANSI、中日韩按 2 列）。"""
    import re
    global _ANSI_RE
    if _ANSI_RE is None:
        _ANSI_RE = re.compile(r"\033\[[0-9;]*m")
    return sum(_char_width(c) for c in _ANSI_RE.sub("", s))


def wrap_display(line: str, width: int) -> list:
    """按显示宽度折行：跳过 ANSI 转义（不计宽、不切断），中日韩按 2 列。"""
    if width <= 0:
        return [line]
    import re
    global _ANSI_RE
    if _ANSI_RE is None:
        _ANSI_RE = re.compile(r"\033\[[0-9;]*m")
    out, cur, cw, i = [], "", 0, 0
    n = len(line)
    while i < n:
        m = _ANSI_RE.match(line, i)
        if m:                       # ANSI 序列：原样保留，不计入宽度
            cur += m.group(0)
            i = m.end()
            continue
        ch = line[i]
        w = _char_width(ch)
        if cw + w > width and cur:  # 放不下了，断行
            out.append(cur)
            cur, cw = "", 0
        cur += ch
        cw += w
        i += 1
    if cur or not out:
        out.append(cur)
    return out


# ---------------------------------------------------------------------------
# 渲染块(claude-code 风格圆角面板)
# ---------------------------------------------------------------------------

def panel(title: str, content: str, color: str = "brcyan") -> str:
    """静态面板:一次性渲染整块内容。"""
    w = term_width() - 2
    head = paint("╭─ ", color) + paint(title, color, "bold") + " " \
        + paint("─" * max(0, w - len(title) - 4), color)
    lines = [head]
    inner = max(1, w - 2)            # 减去 "│ " 前缀两列
    for ln in content.splitlines() or [""]:
        for seg in wrap_display(ln, inner) or [""]:
            lines.append(paint("│ ", color) + seg)
    lines.append(paint("╰" + "─" * max(0, w - 1), color))
    return "\n".join(lines)


class StreamBlock:
    """流式渲染块:LLM 回复边缓冲、关闭时整块 Markdown 渲染后输出。

    用法:
        blk = StreamBlock("PsyClaw"); blk.write(chunk)...; blk.close()

    设计原则:按整块渲染(非逐 token)避免 Markdown 标记截断。
    TTY 模式:打印生成指示符,close() 时上移覆盖 → ANSI 渲染版。
    非 TTY / NO_COLOR:直接输出去标记纯文本,无 ANSI。
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
        if _ENABLED:
            # 生成期间显示进度指示符;close() 时用 ANSI 光标上移覆盖
            self._out.write(paint("│ ", color) + dim("▪ 正在生成…") + "\n")
        self._indicator = _ENABLED
        self._out.flush()

    def write(self, chunk: str) -> None:
        """缓冲流式 chunk;不直接输出,避免 Markdown 标记被截断。"""
        self._buf += chunk

    def close(self) -> None:
        """渲染缓冲内容并关闭面板。"""
        from psyclaw.md_render import render_md
        if self._indicator:
            # 光标上移一行 + 清屏到末尾(覆盖「▪ 正在生成…」行)
            self._out.write("\033[1A\033[J")
        rendered = render_md(self._buf)
        prefix = paint("│ ", self.color)
        inner = max(1, term_width() - 4)   # "│ " 前缀 2 列 + 右侧留白
        for ln in (rendered.splitlines() if rendered else [""]):
            for seg in wrap_display(ln, inner) or [""]:
                self._out.write(prefix + seg + "\n")
        w = term_width() - 2
        self._out.write(paint("╰" + "─" * max(0, w - 1), self.color) + "\n")
        self._out.flush()


def banner(version: str) -> str:
    lines = [paint(BANNER_ART, "brcyan")]
    lines.append("  " + title("PsyClaw") + dim(" · ")
                 + paint(f"v{version}", "bryellow")
                 + dim("  心理学研究全流程 Agent CLI"))
    lines.append("  " + dim("文献调研 · 实验设计 · 统计分析 · 论文写作 — 规范门禁内置"))
    lines.append("  " + rule())
    return "\n".join(lines)
