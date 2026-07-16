"""feat-145:命令实时输出——长脚本边跑边显示,消灭空屏焦虑。

真实事故:模型建议「每请求间隔 30 秒,预计 40 分钟」的抓取脚本,
_run_shell_cmd 用 capture_output=True 全吞输出,用户 40 分钟盯空屏不知死活。
改流式:边跑边打印到终端,完整输出仍回传模型(契约不变)。
"""
from __future__ import annotations

import sys

from psyclaw.repl import _run_shell_cmd


def test_returns_full_output_for_model():
    """回传给模型的字符串仍含 $ cmd / rc / 全部输出(契约不回归)。"""
    out = _run_shell_cmd(f'{sys.executable} -c "print(\'hello\'); print(\'world\')"')
    assert "$ " in out
    assert "(rc=0)" in out
    assert "hello" in out and "world" in out


def test_prints_output_live_to_terminal(capsys):
    """关键:输出被实时打印到终端(不是只 return),用户能看到进度。"""
    _run_shell_cmd(f'{sys.executable} -c "print(\'LIVE_LINE_XYZ\')"')
    printed = capsys.readouterr().out
    assert "LIVE_LINE_XYZ" in printed        # 打到了屏幕,不止 return


def test_captures_nonzero_exit():
    out = _run_shell_cmd(f'{sys.executable} -c "import sys; sys.exit(3)"')
    assert "(rc=3)" in out


def test_captures_stderr():
    out = _run_shell_cmd(
        f'{sys.executable} -c "import sys; sys.stderr.write(\'ERRTOKEN\\n\')"')
    assert "ERRTOKEN" in out


def test_streams_lines_progressively(capsys):
    """多行输出逐行到屏幕(顺序保留)。"""
    code = "for i in range(3): print('step', i)"
    out = _run_shell_cmd(f'{sys.executable} -c "{code}"')
    printed = capsys.readouterr().out
    assert "step 0" in printed and "step 2" in printed
    assert out.index("step 0") < out.index("step 2")   # 回传里顺序也对


def test_timeout_still_enforced(monkeypatch):
    import psyclaw.repl as R
    monkeypatch.setattr(R, "_RUN_TIMEOUT", 1)
    out = _run_shell_cmd(f'{sys.executable} -c "import time; time.sleep(30)"')
    assert "超时" in out


def test_bad_command_no_raise():
    out = _run_shell_cmd("nonexistent_binary_xyz_123 --go")
    assert "$ " in out                       # 不抛,回传可读串
