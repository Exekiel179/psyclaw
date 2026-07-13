"""feat-080:真实 POSIX 按键读取器的 pty 端到端测试。

v0.12 code-review 确认:方向键 \\x1b[A 三字节一包到达,旧实现经 sys.stdin
缓冲读后 select 看 fd 为空 → 方向键被误判成 ESC 整题取消,且 '[A' 泄漏为后续
假按键;而测试套件全部注入 get_key,真实读取器零覆盖。本文件补上:起真子进程
挂 pty,喂原始字节,断言解码结果——不再有"测试全绿但方向键不可用"的盲区。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX 读取器专属")

_ROOT = str(Path(__file__).resolve().parents[1])
_CHILD = ("from psyclaw.ui_input import _get_key\n"
          "ks = []\n"
          "for _ in range({n}):\n"
          "    try:\n"
          "        ks.append(_get_key())\n"
          "    except OSError:\n"
          "        ks.append('OSERR')\n"
          "        break\n"
          "print('|'.join(ks), flush=True)\n")


def _run_keys(payloads: list[bytes], n: int, close_after: bool = False) -> str:
    import pty
    master, slave = pty.openpty()
    proc = subprocess.Popen([sys.executable, "-c", _CHILD.format(n=n)],
                            stdin=slave, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, cwd=_ROOT)
    os.close(slave)
    time.sleep(0.8)                 # 等子进程 setraw 进入 read
    for p in payloads:              # 每键一包、留间隙:贴近真实敲键节奏
        os.write(master, p)
        time.sleep(0.15)
    if close_after:
        time.sleep(0.2)
        os.close(master)
    try:
        out, _ = proc.communicate(timeout=10)
    finally:
        if not close_after:
            os.close(master)
        if proc.poll() is None:
            proc.kill()
    return out.decode("utf-8", errors="replace").strip()


def test_arrow_keys_decoded_not_esc():
    """↓↑ 必须解码为 DOWN/UP——旧实现读成 ESC 并泄漏 '[B'(评审实证)。"""
    assert _run_keys([b"\x1b[B", b"\x1b[A", b"\r"], 3) == "DOWN|UP|ENTER"


def test_bare_esc_still_esc():
    assert _run_keys([b"\x1b"], 1) == "ESC"


def test_unknown_escape_sequence_is_esc_not_leak():
    """未知转义序列(如 Shift-Tab \\x1b[Z)整体消费为 ESC,不泄漏残字节。"""
    assert _run_keys([b"\x1b[Z", b"x", b"\r"], 3) == "ESC|x|ENTER"


def test_cjk_char_read_whole():
    """UTF-8 多字节字符一次读满(中文自由作答首字符不再变乱码)。"""
    assert _run_keys(["中".encode(), b"\r"], 2) == "中|ENTER"


def test_eof_returns_eof_not_empty_spin():
    """pty 关闭 → EOF/OSERR,绝不返回 '' 让上层忙等(评审实证 100% CPU)。"""
    out = _run_keys([], 1, close_after=True)
    assert out in ("EOF", "OSERR")
