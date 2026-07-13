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
            # TCSADRAIN:切 raw 时不丢弃已到达的 type-ahead 输入(setraw 默认
            # TCSAFLUSH 会把两次按键读取间隙里敲的键静默冲掉;feat-080)。
            tty.setraw(fd, termios.TCSADRAIN)
            # feat-080:fd 级读取(os.read),不走 sys.stdin 的 TextIOWrapper——
            # 此前 sys.stdin.read(1) 一次把 \x1b[A 三字节吸进 Python 缓冲,
            # select 看内核队列为空 → 方向键被误判成 ESC 整题取消,且 '[A' 泄漏
            # 为后续假按键(macOS/Linux 真终端可复现;测试注入 get_key 测不到)。
            data = os.read(fd, 1)
            if not data:                       # 真 EOF(pty 关闭/流结束)
                return "EOF"
            if data == b"\x1b":                # ESC 或方向键序列
                import select
                seq = b""
                while len(seq) < 2 and select.select([fd], [], [], 0.05)[0]:
                    chunk = os.read(fd, 2 - len(seq))
                    if not chunk:
                        break
                    seq += chunk
                return {b"[A": "UP", b"[B": "DOWN"}.get(seq, "ESC")
            if data[0] >= 0x80:                # UTF-8 多字节(中文作答首字符)读满
                need = 2 if data[0] < 0xE0 else (3 if data[0] < 0xF0 else 4)
                while len(data) < need:
                    chunk = os.read(fd, need - len(data))
                    if not chunk:
                        break
                    data += chunk
            ch = data.decode("utf-8", errors="replace")
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


# ---------------------------------------------------------------------------
# readline 后端(v0.7 feat-047):非 ptk TTY 的主路径。
# stdlib readline 一经 import 即给 input() 挂上方向键/↑↓历史/←→光标/Ctrl-A/E/K;
# 再挂一个整行 slash 补全器(Tab 触发)。修「REPL 方向键漏出 ^[[A、无历史」。
# ---------------------------------------------------------------------------

def _rl_wrap_prompt(prompt: str) -> str:
    """用 \\001..\\002 包裹 ANSI SGR 序列,让 readline 正确计算提示可见宽度。

    否则彩色提示会让 readline 高估宽度,编辑时光标错位(gnu/libedit 都认这对标记)。
    """
    import re
    return re.sub(r"(\033\[[0-9;]*m)", "\001\\1\002", prompt)


def safe_prompt(prompt: str) -> str:
    """把彩色提示变成 input() 下 readline 安全的形式。

    REPL 一旦 import 过 readline(主输入路径就会),裸 input() 也归 readline 管;
    此时**未包裹的 ANSI 颜色码会被算进可见宽度**,回显光标错位——用户实测的确认框
    「[Y/n]: y」与命令回显串在一起。用 \\001..\\002 包住 SGR 序列让 readline 正确算宽;
    readline 未加载时原样返回(那些控制字符届时不该出现在提示里)。
    """
    if "readline" in sys.modules:
        return _rl_wrap_prompt(prompt)
    return prompt


def _readline_input(prompt: str, commands: dict) -> str:
    """readline 支持的行输入:方向键/历史/光标全可用 + slash 命令 Tab 补全。

    readline 缺失(Windows 等)或任何异常 → 抛出,由 read_line 降级到 raw reader / input()。
    """
    import readline

    def _completer(text: str, state: int):
        buf = readline.get_line_buffer()
        if not buf.startswith("/") or " " in buf:
            return None
        matches = [c for c in commands if c.startswith(buf)]
        return (matches[state] + " ") if state < len(matches) else None

    prev_completer = readline.get_completer()
    prev_delims = readline.get_completer_delims()
    readline.set_completer(_completer)
    readline.set_completer_delims("")          # 整行补全,不按词边界拆
    if "libedit" in (readline.__doc__ or ""):  # macOS 默认 libedit,绑定语法不同
        readline.parse_and_bind("bind ^I rl_complete")
    else:
        readline.parse_and_bind("tab: complete")
    try:
        return input(_rl_wrap_prompt(prompt)).strip()
    finally:                                    # 复原,避免污染其他 input()(确认框等)
        readline.set_completer(prev_completer)
        readline.set_completer_delims(prev_delims)


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

    路径优先级(v0.7 feat-047 起):
      prompt_toolkit(若装了 [full] 且 TTY,实时联想下拉)
      → **readline 后端**(非 ptk TTY 主路径:方向键/↑↓历史/←→光标/Ctrl-A-E-K + Tab 补全)
      → 自研 raw reader(readline 缺失如 Windows,保留 slash 联想菜单)
      → 裸 input()(非 TTY / 一切降级)。
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
    # 非 ptk TTY:优先 readline(修方向键/历史);readline 不可用再退 raw reader
    try:
        return _readline_input(prompt, commands)
    except (KeyboardInterrupt, EOFError):
        raise
    except Exception:  # noqa: BLE001 — readline 缺失(Windows 等)/异常 → raw reader
        pass
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
