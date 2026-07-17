"""feat-151:跑脚本环境修复——生成的脚本能 import psyclaw + python→python3 归一。

真实事故(chat_20260717-003855):
- 模型按 feat-144 写 `from psyclaw.figures import apply_style`,但 python3 script.py
  跑时 psyclaw 不可导入(系统 python3 没装 + sys.path 是 scripts/ 不是项目根)→
  ModuleNotFoundError,模型折腾 8 轮才自己发现要设 PYTHONPATH;
- 系统提示示例写 `python ...`,模型照抄 `python` 在本机(只有 python3)command not found。
"""
from __future__ import annotations

import sys

from psyclaw.repl import _normalize_interpreter, _run_env, _run_shell_cmd


# ---- python→python3 归一(纯函数) --------------------------------------------

def test_normalize_python_to_python3(monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "which",
                        lambda b: None if b in ("python", "pip") else "/usr/bin/" + b)
    assert _normalize_interpreter("python scripts/x.py").startswith("python3 ")
    assert _normalize_interpreter("pip install foo").startswith("pip3 ")


def test_normalize_keeps_python3(monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "which", lambda b: None if b == "python" else "/x/" + b)
    assert _normalize_interpreter("python3 x.py") == "python3 x.py"


def test_normalize_noop_when_python_exists(monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "which", lambda b: "/usr/bin/" + b)   # python 存在
    assert _normalize_interpreter("python x.py") == "python x.py"     # 不改


def test_normalize_only_leading_token(monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "which", lambda b: None if b == "python" else "/x/" + b)
    # 中缝的 python 字样不动(例如路径/参数)
    out = _normalize_interpreter("python3 -c \"print('python is here')\"")
    assert "print('python is here')" in out


# ---- PYTHONPATH 注入 ----------------------------------------------------------

def test_run_env_has_psyclaw_root():
    env = _run_env()
    import psyclaw
    from pathlib import Path
    root = str(Path(psyclaw.__file__).resolve().parent.parent)
    assert root in env.get("PYTHONPATH", "")


def test_run_env_preserves_existing_pythonpath(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/my/existing")
    env = _run_env()
    assert "/my/existing" in env["PYTHONPATH"]


# ---- 端到端:生成脚本能 import psyclaw ----------------------------------------

def test_generated_script_can_import_psyclaw(tmp_path, monkeypatch):
    """从任意 cwd 跑 python3 script.py,脚本 import psyclaw 不再 ModuleNotFoundError。"""
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "sub" / "fig.py"
    script.parent.mkdir()
    script.write_text("import psyclaw.figures\nprint('PSYCLAW_OK')\n", encoding="utf-8")
    out = _run_shell_cmd(f"{sys.executable} sub/fig.py")
    assert "PSYCLAW_OK" in out
    assert "ModuleNotFoundError" not in out


def test_python_command_normalized_and_runs(tmp_path, monkeypatch):
    """模型写 `python ...`,本机只有 python3 时也能跑(归一后)。"""
    import shutil
    real_which = shutil.which
    monkeypatch.setattr(shutil, "which",
                        lambda b: None if b == "python" else real_which(b))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "s.py").write_text("print('RAN_VIA_PY3')\n", encoding="utf-8")
    out = _run_shell_cmd("python s.py")
    assert "RAN_VIA_PY3" in out
    assert "command not found" not in out
