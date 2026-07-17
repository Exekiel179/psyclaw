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
    "bold": "1", "dim": "2", "italic": "3", "reverse": "7",
    "red": "31", "green": "32", "yellow": "33", "blue": "34",
    "magenta": "35", "cyan": "36", "white": "37",
    "brred": "91", "brgreen": "92", "bryellow": "93",
    "brblue": "94", "brmagenta": "95", "brcyan": "96",
    "bgblue": "44", "bgmagenta": "45", "bgcyan": "46",
    # feat-147:精炼 256 色调(比 16 色 br* 柔和)——只在支持 256 色的终端出彩,
    # 不支持的终端 SGR 会忽略未知参数,退化为普通色/无色,不会乱码。单个 38;5;N
    # 可与 bold 组合(1;38;5;N),但两个 256 前景色不要叠加(会拼出非法序列)。
    "teal": "38;5;80", "violet": "38;5;141", "slate": "38;5;103",
    "peach": "38;5;216", "mint": "38;5;114", "gold": "38;5;179",
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


# feat-147:精炼语义色——比全 br* 单调的旧配色柔和、可分辨用途。
def info(text: str) -> str:
    """信息/召回/提示类(柔和青)。"""
    return paint(text, "teal")


def label(text: str) -> str:
    """字段名/小标签(柔和紫,加粗)。"""
    return paint(text, "bold", "violet")


def run_output(text: str) -> str:
    """命令实时输出行(feat-145):独立柔灰蓝,与模型正文一眼可分。"""
    return "  " + paint("│ ", "slate") + paint(text, "slate")


def rule(width: int = 56, char: str = "─") -> str:
    return dim(char * width)


BANNER_ART = r"""
  PsyClaw
  research orchestration workbench
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
        _ANSI_RE = re.compile(r"\033\[[0-9;]*[A-Za-z]")  # 全部 CSI(SGR/清行/移动),不只 m
    return sum(_char_width(c) for c in _ANSI_RE.sub("", s))


def wrap_display(line: str, width: int) -> list:
    """按显示宽度折行：跳过 ANSI 转义（不计宽、不切断），中日韩按 2 列。"""
    if width <= 0:
        return [line]
    import re
    global _ANSI_RE
    if _ANSI_RE is None:
        _ANSI_RE = re.compile(r"\033\[[0-9;]*[A-Za-z]")  # 全部 CSI(SGR/清行/移动),不只 m
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


def _clip(text: str, width: int) -> str:
    """Clip by terminal display width."""
    if display_width(text) <= width:
        return text
    out, used = "", 0
    for ch in text:
        w = _char_width(ch)
        if used + w > max(0, width - 1):
            break
        out += ch
        used += w
    return out + "…"


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - display_width(text))


def _button(label: str, hint: str, color: str) -> str:
    return paint(f" {label} ", color, "bold", "reverse") + " " + dim(hint)


def _agent_row(key: str, value: str, width: int) -> str:
    body = paint("│", "brcyan") + " " + dim(f"{key:<8}") + value
    return body + " " * max(0, width - display_width(body) - 1) + paint("│", "brcyan")


def kv(label: str, value: str, width: int = 10) -> str:
    """Compact aligned label/value row."""
    return dim(f"{label:<{width}}") + value


def _startup_status_lines(status: dict | None, provider: str | None = None,
                          approval: str | None = None) -> list[str]:
    lines: list[str] = []
    if provider:
        lines.append(kv("Provider", _clip(provider, 48)))
    if approval:                     # feat-091:审批模式常显——用户须知道自己在哪种模式
        if approval == "auto":
            lines.append(kv("Approval", err("auto")
                            + dim("  非危险副作用自动放行 · /approval 切换")))
        else:
            lines.append(kv("Approval", ok("default")
                            + dim("  副作用逐条确认 · /approval 切换")))
    if not status:
        return lines

    project = status.get("project", "")
    if project:
        lines.append(kv("Project", _clip(project, 54)))

    goal = (status.get("goal") or "").strip()
    goal_text = _clip(goal.splitlines()[0], 54) if goal else dim("not set · psyclaw goal <目标>")
    lines.append(kv("Goal", goal_text))

    c = status.get("clarify", {})
    if c.get("exists"):
        if c.get("unresolved", 0) == 0:
            clarify = ok("ready")
        else:
            clarify = warn(f"{c.get('resolved', 0)}/{c.get('total', 0)} resolved")
    else:
        clarify = dim("not started · psyclaw prepare")
    lines.append(kv("Preparation", clarify))

    nxt = status.get("next")
    if nxt:
        tag = warn("blocked") if nxt.get("blocker") else accent("next")
        lines.append(kv("Next", f"{tag} {nxt.get('title', '')}"))
    else:
        lines.append(kv("Next", dim("psyclaw guide · psyclaw status")))
    return lines


def startup(version: str, status: dict | None = None, provider: str | None = None,
            approval: str | None = None) -> str:
    """Startup workbench screen for CLI/REPL entry."""
    w = max(68, min(term_width(), 92))
    inner = w - 4
    brand = paint(">_", "brgreen", "bold") + " " \
        + paint("PsyClaw", "bold", "brcyan") + dim(f" v{version}")
    mode = paint("chat · run · auto", "bold", "white") + dim("  psychology workflow harness")
    status_lines = _startup_status_lines(status, provider, approval)
    title = "─ " + brand + " "

    lines = [
        paint("╭" + title, "brcyan") +
        paint("─" * max(0, w - display_width(title) - 2) + "╮", "brcyan"),
        _agent_row("mode", mode, w),
    ]

    if status_lines:
        for raw in status_lines:
            lines.append(_agent_row("", raw, w))
    lines.append(paint("├" + "─" * max(0, w - 2) + "┤", "brcyan"))

    launch = [
        _button("/goal", "current", "brcyan"),
        _button("/run", "workflow", "brmagenta"),
        _button("/auto", "next", "bryellow"),
        _button("/help", "map", "brgreen"),
    ]
    lines.append(_agent_row("try", "   ".join(launch[:2]), w))
    lines.append(_agent_row("", "   ".join(launch[2:]), w))

    lines.append(_agent_row("input", dim("/ for commands  @file for context  Ctrl+C to exit"), w))
    lines.append(paint("╰" + "─" * max(0, w - 2) + "╯", "brcyan"))
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
        self.title = title
        self._buf = ""
        # feat-149:表头延迟到首个 chunk 才打——空回复(deepseek 常见)不再留下
        # 丑陋空框「╭─ …─╮ │ (空) ╰──╯」+「自动恢复」的迷惑组合。
        self._header_shown = False
        self._indicator = False

    def _show_header(self) -> None:
        if self._header_shown:
            return
        self._header_shown = True
        w = term_width() - 2
        # feat-157:闭合右上角 ╮——此前只有 ╭ 左角、右侧开口,看着像半个框。
        dashes = max(0, w - 5 - display_width(self.title))
        head = paint("╭─ ", self.color) + paint(self.title, self.color, "bold") + " " \
            + paint("─" * dashes + "╮", self.color)
        self._out.write(head + "\n")
        if _ENABLED:
            # 生成期间显示进度指示符;close() 时用 ANSI 光标上移覆盖
            self._out.write(paint("│ ", self.color) + dim("▪ 正在生成…") + "\n")
        self._indicator = _ENABLED
        self._out.flush()

    def write(self, chunk: str) -> None:
        """缓冲流式 chunk;不直接输出,避免 Markdown 标记被截断。首个 chunk 才打表头。"""
        if chunk:
            self._show_header()
        self._buf += chunk

    def close(self) -> None:
        """渲染缓冲内容并关闭面板。空缓冲(从未 write)→ 不打任何框,零噪音。"""
        from psyclaw.md_render import render_md
        if not self._buf.strip():
            return                              # feat-149:空回复不渲染空框
        self._show_header()                     # 兜底:有内容但还没打过表头
        if self._indicator:
            # 光标上移一行 + 清屏到末尾(覆盖「▪ 正在生成…」行)
            self._out.write("\033[1A\033[J")
        rendered = render_md(self._buf)
        w = term_width() - 2
        prefix = paint("│ ", self.color)
        rborder = paint("│", self.color)        # feat-157:右边框收口
        inner = max(1, w - 4)                    # "│ " 左(2)+ 内容 + " │" 右(2)
        for ln in (rendered.splitlines() if rendered else [""]):
            for seg in wrap_display(ln, inner) or [""]:
                pad = " " * max(0, inner - display_width(seg))
                reset = RESET if _ENABLED else ""   # 防内容尾色染到填充/右框
                self._out.write(prefix + seg + reset + pad + " " + rborder + "\n")
        self._out.write(paint("╰" + "─" * max(0, w - 2) + "╯", self.color) + "\n")
        self._out.flush()


def banner(version: str) -> str:
    return startup(version)
