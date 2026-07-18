"""feat(scale/信效度):生成委托成熟库的信度脚本——统计外移,psyclaw 只生成不计算。

守铁律:psyclaw 不算 α,而是生成一个委托 pingouin 的可复现脚本,由用户(或 MCP)跑。
脚本须:读数据、按量表挑条目列、反向计分反向条目、调 pingouin.cronbach_alpha、语法合法。
"""
from __future__ import annotations

from psyclaw.psych.reliability_script import generate_reliability_script


def test_returns_script_text():
    s = generate_reliability_script("rses", "data/clean/x.csv")
    assert isinstance(s, str) and len(s) > 100


def test_delegates_to_pingouin_not_inline():
    s = generate_reliability_script("rses", "data/clean/x.csv")
    assert "pingouin" in s and "cronbach_alpha" in s
    # 生成的是脚本(供外部跑),psyclaw 自身不 import 统计库
    import psyclaw.psych.reliability_script as M
    import inspect
    src = inspect.getsource(M)
    for banned in ("import pingouin", "import scipy", "import numpy", "import pandas"):
        assert banned not in src, f"生成器本身不该 import 统计库:{banned}"


def test_script_references_data_and_items():
    s = generate_reliability_script("rses", "data/clean/mydata.csv")
    assert "data/clean/mydata.csv" in s
    assert "Q1" in s and "Q10" in s          # rses 10 条目,默认前缀 Q


def test_script_handles_reverse_items():
    s = generate_reliability_script("rses", "x.csv")
    # rses 反向条目 3,5,8,9,10 —— 脚本须提到反向计分
    assert "reverse" in s.lower() or "反向" in s
    assert "3" in s and "5" in s


def test_script_is_valid_python():
    s = generate_reliability_script("rses", "x.csv")
    compile(s, "<generated>", "exec")        # 语法必须合法


def test_custom_prefix():
    s = generate_reliability_script("phq-9", "x.csv", prefix="item")
    assert "item1" in s and "item9" in s


def test_unknown_scale():
    s = generate_reliability_script("no-such-scale", "x.csv")
    assert s == "" or "未知" in s


def test_cmd_score_reliability_writes_script(tmp_path, monkeypatch, capsys):
    """score --reliability 写出委托脚本到 scripts/,且脚本语法合法。"""
    import argparse
    monkeypatch.chdir(tmp_path)
    header = ",".join(f"Q{i}" for i in range(1, 11))
    data = tmp_path / "d.csv"
    data.write_text(header + "\n" + "3,2,4,1,3,2,4,1,3,2\n", encoding="utf-8")
    from psyclaw.cli import cmd_score
    rc = cmd_score(argparse.Namespace(data=str(data), scale="rses", prefix="Q",
                                      suffix="", method="sum", out=None, json=False,
                                      reliability=True))
    assert rc == 0
    script_p = tmp_path / "scripts" / "reliability_rses.py"
    assert script_p.is_file()
    compile(script_p.read_text(encoding="utf-8"), "<gen>", "exec")   # 合法
    assert "cronbach_alpha" in script_p.read_text(encoding="utf-8")
