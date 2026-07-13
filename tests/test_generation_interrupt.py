"""feat-090:生成期可中断(EscapeWatch)+ 裸 quit/exit 退出词。

用户实测反馈:LLM 流式阻塞期 ESC/Ctrl+C 无响应(Ctrl+C 只在输入态有捕获),
裸 quit/exit 不认。pty 端到端验证真监听器;单元验证 no-op 降级与 toolloop 上抛。
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parents[1])

_POSIX = os.name != "nt"

_WATCH_CHILD = (
    "import time\n"
    "from psyclaw.ui_input import EscapeWatch\n"
    "with EscapeWatch() as esc:\n"
    "    hit = False\n"
    "    t0 = time.time()\n"
    "    while time.time() - t0 < {secs}:\n"
    "        if esc.pressed():\n"
    "            hit = True\n"
    "            break\n"
    "        time.sleep(0.05)\n"
    "print('INT' if hit else 'NOINT', flush=True)\n"
    "{tail}"
)


def _run_watch(payloads: list[bytes], secs: float = 3.0, tail: str = "",
               late_payloads: list[bytes] | None = None) -> str:
    import pty
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        [sys.executable, "-c", _WATCH_CHILD.format(secs=secs, tail=tail)],
        stdin=slave, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, cwd=_ROOT)
    os.close(slave)
    time.sleep(0.8)                 # 等子进程进入 cbreak 轮询
    for p in payloads:
        os.write(master, p)
        time.sleep(0.15)
    if late_payloads:               # 监听窗口结束、终端恢复后再发(如新输入行)
        time.sleep(secs + 0.5)
        for p in late_payloads:
            os.write(master, p)
    try:
        out, _ = proc.communicate(timeout=15)
    finally:
        os.close(master)
        if proc.poll() is None:
            proc.kill()
    return out.decode("utf-8", errors="replace").strip()


@pytest.mark.skipif(not _POSIX, reason="pty 专属")
def test_lone_esc_interrupts():
    """孤立 ESC → pressed() 报中断(此前生成期无人监听按键)。"""
    assert "INT" in _run_watch([b"\x1b"])


@pytest.mark.skipif(not _POSIX, reason="pty 专属")
def test_arrow_sequence_not_interrupt():
    """方向键 \\x1b[A 是序列不是中断——30ms 后续字节窗口区分。"""
    out = _run_watch([b"\x1b[A"], secs=1.2)
    assert "NOINT" in out


@pytest.mark.skipif(not _POSIX, reason="pty 专属")
def test_typeahead_discard_is_noisy_and_terminal_recovers():
    """生成期键入无法回注(现代内核禁 TIOCSTI)→ 必须**明示丢弃**,不静默吞键;
    且监听退出后终端恢复 canonical,新输入行照常可读。"""
    tail = ("try:\n"
            "    print('GOT:' + input(), flush=True)\n"
            "except EOFError:\n"
            "    print('GOT:EOF', flush=True)\n")
    out = _run_watch([b"hola\n"], secs=1.2, tail=tail,
                     late_payloads=[b"despues\n"])
    assert "已丢弃" in out            # 诚实提示,不静默
    assert "GOT:despues" in out       # 终端恢复,后续输入正常


def test_noop_without_tty(monkeypatch):
    """非 TTY(管道/CI)全程 no-op:enter/exit 安全,pressed 恒 False。"""
    from psyclaw.ui_input import EscapeWatch
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    with EscapeWatch() as esc:
        assert esc.pressed() is False


def test_tool_loop_esc_raises_keyboard_interrupt(monkeypatch):
    """toolloop 流式消费期 ESC → KeyboardInterrupt 上抛,由 REPL 取消本轮。"""
    import psyclaw.ui_input as UI
    from psyclaw import toolloop as TL

    class _EscStub:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def pressed(self):
            return True

    monkeypatch.setattr(UI, "EscapeWatch", _EscStub)

    class _P:
        name = "fake"
        api_key = "k"
        def chat(self, msgs, system=""):
            yield "片"
            yield "段"

    with pytest.raises(KeyboardInterrupt):
        TL.run_tool_loop(_P(), "sys", [{"role": "user", "content": "你好"}], tools={})


class _EscOn:
    def pressed(self):
        return True


class _EscOff:
    def pressed(self):
        return False


def test_stream_interruptible_passthrough():
    from psyclaw.ui_input import stream_interruptible
    assert list(stream_interruptible(iter(["a", "b", "c"]), _EscOff())) == ["a", "b", "c"]


def test_stream_interruptible_cancels_while_waiting_first_token():
    """首 token 未到也能取消——逐 chunk 查 pressed 时 ESC 石沉大海(活体实测)。"""
    from psyclaw.ui_input import stream_interruptible

    def _slow():
        time.sleep(5)
        yield "太迟了"

    t0 = time.time()
    with pytest.raises(KeyboardInterrupt):
        list(stream_interruptible(_slow(), _EscOn()))
    assert time.time() - t0 < 2.0     # 无需等生成器出首 chunk


def test_stream_interruptible_propagates_provider_error():
    from psyclaw.ui_input import stream_interruptible

    def _boom():
        yield "x"
        raise RuntimeError("provider 炸了")

    with pytest.raises(RuntimeError, match="provider 炸了"):
        list(stream_interruptible(_boom(), _EscOff()))


def test_bare_exit_words():
    """裸 quit/exit(任意大小写、含空白)认作退出;正常提问不误伤。"""
    from psyclaw.repl import _is_exit_word
    assert _is_exit_word("quit") and _is_exit_word(" EXIT ") and _is_exit_word("Quit")
    assert not _is_exit_word("exit code 怎么看")
    assert not _is_exit_word("")
    assert not _is_exit_word("/exit")   # slash 命令走命令分发,不归这里
