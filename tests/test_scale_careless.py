"""feat(scale/careless 接入):score_datafile 暴露**原始应答**,虚伪作答标记基于原始值。

关键正确性:careless 必须跑在**原始**应答上,不是反向计分后的值——否则含反向条目的
量表上,直入式作答(全填同一个数)会被反向翻转掩盖,漏检。用 rses(反向条目 3,5,8,9,10)
验证:全填 4 → 原始不变(invariant)、计分后会被翻成 [4,4,1,4,1,4,4,1,1,1](非 invariant)。
"""
from __future__ import annotations

from psyclaw.psych.careless import careless_report
from psyclaw.psych.scales import score_datafile


def _write_csv(tmp_path, rows):
    header = "," .join(f"Q{i}" for i in range(1, 11))
    lines = [header] + [",".join(str(v) for v in r) for r in rows]
    p = tmp_path / "resp.csv"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(p)


def test_score_datafile_exposes_raw_responses(tmp_path):
    csv = _write_csv(tmp_path, [
        [4, 4, 4, 4, 4, 4, 4, 4, 4, 4],          # 直入式:全 4
        [1, 2, 3, 4, 3, 2, 1, 2, 3, 4],          # 正常
    ])
    r = score_datafile(csv, "rses")
    assert "raw_responses" in r
    # 原始值原样(不含反向翻转)
    assert r["raw_responses"][0] == [4.0] * 10
    assert r["raw_responses"][1] == [1.0, 2, 3, 4, 3, 2, 1, 2, 3, 4]


def test_raw_responses_not_reverse_scored(tmp_path):
    """铁证:全 4 若被反向计分,条目 3/5/8/9/10 会变 1;原始必须仍是 4。"""
    csv = _write_csv(tmp_path, [[4] * 10])
    r = score_datafile(csv, "rses")
    assert r["raw_responses"][0] == [4.0] * 10       # 没被翻转


def test_careless_flags_straightliner_via_raw(tmp_path):
    csv = _write_csv(tmp_path, [
        [4, 4, 4, 4, 4, 4, 4, 4, 4, 4],
        [1, 2, 3, 4, 3, 2, 1, 2, 3, 4],
    ])
    r = score_datafile(csv, "rses")
    rep = careless_report(r["raw_responses"])
    assert rep["rows"][0]["invariant"] is True       # 全 4 = 直入式
    assert rep["rows"][0]["suspect"] is True
    assert rep["rows"][1]["suspect"] is False
    assert rep["n_suspect"] == 1


def test_raw_responses_missing_becomes_none(tmp_path):
    header = ",".join(f"Q{i}" for i in range(1, 11))
    p = tmp_path / "m.csv"
    # 第 3 列空
    p.write_text(header + "\n4,4,,4,4,4,4,4,4,4\n", encoding="utf-8")
    r = score_datafile(str(p), "rses")
    assert r["raw_responses"][0][2] is None
    assert r["raw_responses"][0][0] == 4.0


def test_cmd_score_prints_careless_section(tmp_path, capsys):
    """score 命令输出含虚伪作答体检,并标记直入式作答者。"""
    import argparse
    csv = _write_csv(tmp_path, [
        [4, 4, 4, 4, 4, 4, 4, 4, 4, 4],
        [1, 2, 3, 4, 3, 2, 1, 2, 3, 4],
    ])
    from psyclaw.cli import cmd_score
    rc = cmd_score(argparse.Namespace(data=csv, scale="rses", prefix="Q",
                                      suffix="", method="sum", out=None, json=False))
    assert rc == 0
    out = capsys.readouterr().out
    assert "虚伪作答体检" in out
    assert "直入式作答" in out and "1/2" in out
