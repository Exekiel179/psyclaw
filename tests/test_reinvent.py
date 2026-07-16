"""feat-150:结构化软拦截——检测模型手搓轮子(python-docx / 裸 matplotlib),
落盘后当场纠偏(软提示 + 喂回模型),不阻断落盘。

feat-144 提示层引导对弱指令模型(deepseek)不够硬:真实事故里模型仍手搓
md_to_docx.py、裸 matplotlib 出豆腐块。这层在它真手搓时当场检测并纠偏。
"""
from __future__ import annotations

from psyclaw.context import detect_reinvention


# ---- 纯函数检测 ---------------------------------------------------------------

def test_detect_python_docx_from_import():
    r = detect_reinvention("scripts/md_to_docx.py", "from docx import Document\n")
    assert r is not None
    key, msg = r
    assert key == "docx"
    assert "export" in msg and "docx" in msg


def test_detect_python_docx_plain_import():
    r = detect_reinvention("x.py", "import docx\nd = docx.Document()\n")
    assert r and r[0] == "docx"


def test_detect_bare_matplotlib_without_style():
    code = "import matplotlib.pyplot as plt\nplt.plot([1,2])\nplt.savefig('f.png')\n"
    r = detect_reinvention("scripts/viz.py", code)
    assert r is not None
    key, msg = r
    assert key == "figstyle"
    assert "apply_style" in msg


def test_matplotlib_with_apply_style_is_ok():
    code = ("from psyclaw.figures import apply_style\n"
            "import matplotlib.pyplot as plt\n"
            "with apply_style('apa7'):\n    plt.plot([1,2])\n")
    assert detect_reinvention("scripts/viz.py", code) is None


def test_docx_takes_priority_over_figure():
    code = "import docx\nimport matplotlib.pyplot as plt\n"
    r = detect_reinvention("x.py", code)
    assert r and r[0] == "docx"


def test_non_python_file_not_flagged():
    # 稿件正文里提到 docx/matplotlib 不算手搓
    md = "本报告导出为 docx,用 matplotlib 画的图。import docx 只是文中字样。"
    assert detect_reinvention("outputs/report.md", md) is None


def test_plain_python_not_flagged():
    code = "import pandas as pd\ndf = pd.read_csv('x.csv')\nprint(df.describe())\n"
    assert detect_reinvention("scripts/analyze.py", code) is None


def test_empty_inputs():
    assert detect_reinvention("", "") is None
    assert detect_reinvention("x.py", "") is None


# ---- _capture_saves 集成:检测 + 去重 + 返回纠偏 -------------------------------

def _session(tmp_path, monkeypatch):
    import psyclaw.repl as repl
    monkeypatch.chdir(tmp_path)
    s = repl.ReplSession.__new__(repl.ReplSession)
    s.yolo = True                      # 自动覆盖,免交互确认
    s._reinvent_nudged = set()
    return s


def test_capture_saves_returns_nudge_on_reinvention(tmp_path, monkeypatch):
    s = _session(tmp_path, monkeypatch)
    reply = "好的,我来生成转换脚本:\n```save path=scripts/md_to_docx.py\nimport docx\n```\n"
    nudges = s._capture_saves(reply)
    assert nudges and any("export" in n for n in nudges)
    assert (tmp_path / "scripts" / "md_to_docx.py").exists()   # 仍落盘(不阻断)


def test_capture_saves_dedups_same_pattern(tmp_path, monkeypatch):
    s = _session(tmp_path, monkeypatch)
    reply = "```save path=a.py\nimport docx\n```\n"
    first = s._capture_saves(reply)
    reply2 = "```save path=b.py\nfrom docx import Document\n```\n"
    second = s._capture_saves(reply2)
    assert first and not second        # 同类只纠偏一次,不啰嗦


def test_capture_saves_no_nudge_for_clean_script(tmp_path, monkeypatch):
    s = _session(tmp_path, monkeypatch)
    reply = "```save path=ok.py\nimport pandas as pd\n```\n"
    assert s._capture_saves(reply) == []
