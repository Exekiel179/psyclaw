"""键级交互输入 — slash 命令实时联想(stdlib + prompt_toolkit optional)。

**优先路径**：若已安装 prompt_toolkit（`psyclaw[full]`），启用：
  - slash 命令实时补全（Tab/Enter 选择）
  - 会话内历史（↑/↓ 浏览，可跨 read_line 调用持久）
  - 多行编辑、标准键位（Ctrl+A/E/K/...）
  - ANSI 彩色 prompt 原样透传

**降级路径**：prompt_toolkit 未安装，或非 TTY（管道/重定向），或任何异常 →
  回落到原 stdlib msvcrt/termios 实现，保证脚本化调用永远可用。
"""

from __future__ import annotations

import os
import sys

from psyclaw import ui

MAX_SUGGEST = 6

# ---------------------------------------------------------------------------
# prompt_toolkit 可选导入（装了才用）
# ---------------------------------------------------------------------------

_PTK_AVAILABLE = False
_ptk_session = None           # PromptSession 单例，惰性创建

try:
    from prompt_toolkit import PromptSession as _PtkSession          # type: ignore[import-not-found]
    from prompt_toolkit.completion import (                           # type: ignore[import-not-found]
        Completer as _PtkCompleter,
        Completion as _PtkCompletion,
    )
    from prompt_toolkit.formatted_text import ANSI as _PtkANSI      # type: ignore[import-not-found]
    from prompt_toolkit.history import InMemoryHistory as _PtkHist  # type: ignore[import-not-found]

    class _SlashCompleter(_PtkCompleter):
        """prompt_toolkit Completer：仅对 / 开头输入触发命令补全。"""

        def __init__(self, commands: dict) -> None:
            self._commands = commands

        def get_completions(self, document, complete_event):
            for suffix, display, meta in _slash_completions(
                    document.text_before_cursor, self._commands):
                yield _PtkCompletion(suffix, display=display, display_meta=meta)

    _PTK_AVAILABLE = True
except ImportError:
    pass


def _slash_completions(text: str, commands: dict) -> list[tuple[str, str, str]]:
    """纯函数：给定缓冲文本与命令表，返回 (后缀, 显示命令, 描述) 三元组列表。

    触发条件：文本以 / 开头且不含空格（避免参数阶段干扰）。
    """
    if not text.startswith("/") or " " in text:
        return []
    return [
        (cmd[len(text):], cmd, desc[:50])
        for cmd, desc in commands.items()
        if cmd.startswith(text)
    ][:MAX_SUGGEST]


def _get_ptk_session(commands: dict):
    """获取或创建 PromptSession 单例（仅当 _PTK_AVAILABLE 时调用）。"""
    global _ptk_session
    if _ptk_session is None:
        _ptk_session = _PtkSession(
            completer=_SlashCompleter(commands),
            history=_PtkHist(),
            complete_while_typing=True,
            mouse_support=False,
        )
    else:
        _ptk_session.completer = _SlashCompleter(commands)
    return _ptk_session


def _ptk_read_line(prompt_str: str, commands: dict) -> str:
    """使用 prompt_toolkit 读取一行（含历史/补全/键位）。"""
    session = _get_ptk_session(commands)
    result = session.prompt(_PtkANSI(prompt_str))
    return (result or "").strip()


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

_readline_ready: bool | None = None     # None=未尝试 True=已挂接 False=不可用


def _fallback_input(prompt: str) -> str:
    """裸 input() 兜底：先尝试 import readline 启用行内编辑/↑↓ 历史。

    readline 是 stdlib（POSIX 自带 GNU/libedit readline；Windows 无该模块）。
    **导入一次即全局挂接 builtins.input** —— 之后方向键移动光标、↑↓ 翻会话历史、
    Ctrl-A/E/K 等键位均可用，否则 input() 下方向键会漏出裸 `^[[A`/`^[[B` 转义。
    缺失（Windows 等）或任何异常静默降级为纯 input()，绝不阻断脚本化调用。
    """
    global _readline_ready
    if _readline_ready is None:
        try:
            import readline  # noqa: F401 — 导入即挂接 input()，无需直接引用
            _readline_ready = True
        except Exception:  # noqa: BLE001 — 无 readline（Windows 等）静默降级
            _readline_ready = False
    return input(prompt).strip()


def read_line(prompt: str, commands: dict) -> str:
    """带 slash 联想的行输入。commands: {"/cmd": "描述"}。

    优先 prompt_toolkit（若已安装且 TTY）→ 降级 stdlib 交互输入 → 降级 input()。
    最末级 input() 兜底前会 import readline（见 `_fallback_input`），让方向键/
    历史在终端兼容降级时仍可用。
    """
    if _PTK_AVAILABLE and sys.stdin.isatty() and sys.stdout.isatty():
        try:
            return _ptk_read_line(prompt, commands)
        except (KeyboardInterrupt, EOFError):
            raise
        except Exception:  # noqa: BLE001 — ptk 失败时降级 stdlib
            pass
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return _fallback_input(prompt)
    try:
        return _read_line_interactive(prompt, commands)
    except (KeyboardInterrupt, EOFError):
        raise
    except Exception:  # noqa: BLE001 — 任何终端兼容问题都降级
        return _fallback_input(prompt)


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
