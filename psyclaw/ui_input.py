"""键级交互输入 — slash 命令实时联想(stdlib only,仿 claude-code)。

输入 "/" 即时弹出命令联想列表(随输入过滤),
↑/↓ 或 Tab 选择,Enter 补全/提交,Esc 关闭联想,Ctrl+C 退出。

实现:Windows 用 msvcrt.getwch,Unix 用 termios+tty 原始模式;
非 TTY(管道/重定向)或任何异常 → 自动降级为内置 input(),
保证脚本化调用永远可用。
"""

from __future__ import annotations

import os
import sys

from psyclaw import ui

MAX_SUGGEST = 6


# ---------------------------------------------------------------------------
# 跨平台读键
# ---------------------------------------------------------------------------

if os.name == "nt":
    def _get_key() -> str:
        import msvcrt
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):           # 功能键前缀
            ch2 = msvcrt.getwch()
            return {"H": "UP", "P": "DOWN"}.get(ch2, "")
        if ch == "\r":
            return "ENTER"
        if ch == "\x08":
            return "BACKSPACE"
        if ch == "\x1b":
            return "ESC"
        if ch == "\x03":
            raise KeyboardInterrupt
        if ch == "\t":
            return "TAB"
        return ch
else:
    def _get_key() -> str:
        import termios
        import tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "\x1b":                  # ESC 或方向键序列
                import select
                if select.select([sys.stdin], [], [], 0.05)[0]:
                    seq = sys.stdin.read(2)
                    return {"[A": "UP", "[B": "DOWN"}.get(seq, "ESC")
                return "ESC"
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        if ch in ("\r", "\n"):
            return "ENTER"
        if ch in ("\x7f", "\x08"):
            return "BACKSPACE"
        if ch == "\x03":
            raise KeyboardInterrupt
        if ch == "\x04":                       # Ctrl+D
            return "EOF"
        if ch == "\t":
            return "TAB"
        return ch


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------

def _render(prompt: str, buf: str, suggestions: list, sel: int,
            prev_lines: int) -> int:
    out = sys.stdout
    # 从输入行开始整体重画(联想行画在下方,画完把光标拉回来)
    out.write("\r\033[K" + prompt + buf)
    n = len(suggestions)
    for i, (cmd, desc) in enumerate(suggestions):
        mark = ui.paint("▸ ", "brcyan") if i == sel else "  "
        cmd_txt = ui.paint(f"{cmd:<14}", "brcyan", "bold") if i == sel \
            else ui.accent(f"{cmd:<14}")
        out.write("\n\033[K" + mark + cmd_txt + ui.dim(desc[:56]))
    # 多余旧行清空
    for _ in range(prev_lines - n if prev_lines > n else 0):
        out.write("\n\033[K")
    extra = max(prev_lines, n)
    if extra:
        out.write(f"\033[{extra}A")               # 光标回输入行
    out.write("\r" + "\033[" + str(_visible_len(prompt) + len(buf)) + "C"
              if (_visible_len(prompt) + len(buf)) else "\r")
    out.flush()
    return n


def _visible_len(s: str) -> int:
    """去掉 ANSI 后的长度(粗略,中文按 1 算——光标定位足够用)。"""
    import re
    return len(re.sub(r"\033\[[0-9;]*m", "", s))


def _clear_suggestions(prev_lines: int) -> None:
    out = sys.stdout
    for _ in range(prev_lines):
        out.write("\n\033[K")
    if prev_lines:
        out.write(f"\033[{prev_lines}A")
    out.flush()


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def read_line(prompt: str, commands: dict) -> str:
    """带 slash 联想的行输入。commands: {"/cmd": "描述"}。

    非 TTY 或读键失败 → 降级 input()。
    """
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return input(prompt).strip()
    try:
        return _read_line_interactive(prompt, commands)
    except KeyboardInterrupt:
        raise
    except EOFError:
        raise
    except Exception:  # noqa: BLE001 — 任何终端兼容问题都降级
        return input(prompt).strip()


def _suggest(buf: str, commands: dict) -> list:
    if not buf.startswith("/") or " " in buf:
        return []
    return [(c, d) for c, d in commands.items() if c.startswith(buf)][:MAX_SUGGEST]


def _read_line_interactive(prompt: str, commands: dict) -> str:
    buf = ""
    sel = 0
    prev = 0
    sys.stdout.write(prompt)
    sys.stdout.flush()
    while True:
        key = _get_key()
        if key == "EOF" and not buf:
            raise EOFError
        suggestions = _suggest(buf, commands)
        if key == "ENTER":
            if suggestions and buf not in [c for c, _ in suggestions]:
                buf = suggestions[min(sel, len(suggestions) - 1)][0] + " "
                sel = 0
                prev = _render(prompt, buf, _suggest(buf, commands), sel, prev)
                continue
            _clear_suggestions(prev)
            sys.stdout.write("\n")
            sys.stdout.flush()
            return buf.strip()
        if key == "TAB":
            if suggestions:
                buf = suggestions[min(sel, len(suggestions) - 1)][0] + " "
                sel = 0
        elif key == "UP":
            sel = (sel - 1) % max(1, len(suggestions))
        elif key == "DOWN":
            sel = (sel + 1) % max(1, len(suggestions))
        elif key == "ESC":
            _clear_suggestions(prev)
            prev = 0
            sys.stdout.write("\r\033[K" + prompt + buf)
            sys.stdout.flush()
            continue
        elif key == "BACKSPACE":
            buf = buf[:-1]
            sel = 0
        elif key and len(key) == 1 and (key.isprintable()):
            buf += key
            sel = 0
        suggestions = _suggest(buf, commands)
        if sel >= len(suggestions):
            sel = 0
        prev = _render(prompt, buf, suggestions, sel, prev)
