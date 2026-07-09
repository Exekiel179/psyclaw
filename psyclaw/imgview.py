"""终端内联渲染图片 —— 纯 stdlib(终端负责解码,我们只 base64 原始字节)。

心理学分析常出图(matplotlib savefig 的散点/森林图…),但 REPL 只打印路径,用户得自己去开。
支持内联渲染的终端(iTerm2 / WezTerm / VSCode / Warp / kitty)可直接把图显示在对话里。

两种协议,都不需要第三方库(不违反「纯 stdlib 核」):
- iTerm2 内联图片协议:一条 OSC 1337 转义,携带 base64(原始文件字节)——**无需解码**,任意格式。
- kitty 图形协议:_G 转义 + base64 分块;f=100 仅 PNG(其它格式本核不解码,交回退)。

终端能力按环境变量探测;config `image_protocol` 可强制 iterm2|kitty|none|auto(探测错时的安全阀)。
非 TTY / tmux/screen(转义会串)/ 不认识的终端 → 不渲染,交调用方回退打印路径。
"""

from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
MAX_IMG_BYTES = 8 * 1024 * 1024      # 超过不内联(base64 会撑爆终端,也没意义)

# TERM_PROGRAM 值 → 走 iTerm2 内联图片协议的终端
_ITERM2_PROGRAMS = {"iTerm.app", "WezTerm", "vscode", "WarpTerminal", "mintty"}

# 图片路径提取:命令输出里「…saved as behavior_brain_corr.png」这类,抓出来自动渲染
import re as _re
_IMG_PATH_RE = _re.compile(r"[\w./\\~\-]+\.(?:png|jpe?g|gif|webp|bmp)", _re.I)


def is_image(path) -> bool:
    return Path(path).suffix.lower() in IMG_EXT


def find_image_paths(text: str) -> list[str]:
    """从文本(命令输出等)抓出图片路径 token(去重保序)。纯函数。"""
    out: list[str] = []
    for m in _IMG_PATH_RE.findall(text or ""):
        if m not in out:
            out.append(m)
    return out


def _proto_from_env(env: dict) -> str | None:
    """按环境变量判定内联图片协议(kitty|iterm2|None)。纯函数,可单测。"""
    term = env.get("TERM", "")
    if term.startswith(("screen", "tmux")):
        return None                  # 复用会话里裸转义会串,先不支持
    if env.get("KITTY_WINDOW_ID") or term == "xterm-kitty":
        return "kitty"
    if env.get("TERM_PROGRAM") in _ITERM2_PROGRAMS or env.get("LC_TERMINAL") == "iTerm2":
        return "iterm2"
    return None


def supports_inline(force: str | None = None) -> str | None:
    """当前终端支持的内联协议;force(config)可覆盖探测。非 TTY 一律 None。"""
    if force:
        low = force.lower()
        if low == "none":
            return None
        if low in ("iterm2", "kitty"):
            return low
        # "auto" 或未知 → 落到探测
    if not sys.stdout.isatty():
        return None
    return _proto_from_env(os.environ)


def render_iterm2(name: str, data: bytes) -> str:
    """iTerm2 内联图片转义(一条 OSC 1337,携带 base64 原始字节)。纯函数。"""
    b64 = base64.b64encode(data).decode("ascii")
    b64name = base64.b64encode(name.encode("utf-8")).decode("ascii")
    return (f"\033]1337;File=inline=1;size={len(data)};name={b64name};"
            f"width=auto;height=auto;preserveAspectRatio=1:{b64}\a\n")


def render_kitty(data: bytes) -> str:
    """kitty 图形协议转义(base64 分 4096 块;f=100=PNG,a=T 传输并显示)。纯函数。"""
    b64 = base64.b64encode(data).decode("ascii")
    chunks = [b64[i:i + 4096] for i in range(0, len(b64), 4096)] or [""]
    parts: list[str] = []
    for i, ch in enumerate(chunks):
        ctrl = "a=T,f=100," if i == 0 else ""
        more = 0 if i == len(chunks) - 1 else 1
        parts.append(f"\033_G{ctrl}m={more};{ch}\033\\")
    return "".join(parts) + "\n"


def render_escape(path, force: str | None = None) -> str | None:
    """把图片文件渲染成终端转义串;不可渲染(非图/超限/终端不支持)返回 None。"""
    p = Path(path).expanduser()
    if not p.is_file() or not is_image(p):
        return None
    proto = supports_inline(force)
    if not proto:
        return None
    try:
        data = p.read_bytes()
    except OSError:
        return None
    if not data or len(data) > MAX_IMG_BYTES:
        return None
    if proto == "kitty":
        if p.suffix.lower() != ".png":      # kitty f=100 仅 PNG,其它交回退
            return None
        return render_kitty(data)
    return render_iterm2(p.name, data)
