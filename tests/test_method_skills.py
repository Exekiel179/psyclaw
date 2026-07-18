"""feat(method 重定位):method 从"方法词典"变成"方法学 skill 路由"。

用户判断:14 条方法词典对专家没用;改成路由到结构化 skill(样本量/无关变量控制…),
让模型按 skill 的既定流程做,比裸输出规范。样本量这类统计走外移脚本。
"""
from __future__ import annotations

from psyclaw.psych.method_skills import (
    list_method_skills,
    match_method_skill,
    skill_procedure,
)


def test_lists_the_two_method_skills():
    names = {s["name"] for s in list_method_skills(".")}
    assert {"sample-size", "confound-control"} <= names


def test_match_sample_size_by_intent():
    m = match_method_skill("帮我算一下样本量", ".")
    assert m and m["name"] == "sample-size"
    assert match_method_skill("power analysis", ".")["name"] == "sample-size"


def test_match_confound_by_intent():
    m = match_method_skill("怎么控制无关变量", ".")
    assert m and m["name"] == "confound-control"
    assert match_method_skill("混淆变量", ".")["name"] == "confound-control"


def test_match_none_for_unrelated():
    assert match_method_skill("今天天气", ".") is None


def test_ascii_alias_word_boundary_no_false_match():
    # feat-165 修:power 是 empower 的子串,不该误路由到 sample-size
    assert match_method_skill("empower the team", ".") is None
    # 但独立的 power 词仍命中
    assert match_method_skill("run a power analysis", ".")["name"] == "sample-size"


def test_skill_procedure_returns_body():
    body = skill_procedure("sample-size", ".")
    assert "功效分析" in body and "红线" in body
    assert "统计外移" in body or "外移" in body     # 守铁律的交代在里面


def test_skill_procedure_unknown():
    assert skill_procedure("no-such", ".") == ""


# ---- cmd_method 路由 ----------------------------------------------------------

def test_cmd_method_routes_to_skill(capsys):
    import argparse
    from psyclaw.cli import cmd_method
    rc = cmd_method(argparse.Namespace(method_id="样本量"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "sample-size" in out or "样本量" in out
    assert "功效分析" in out                        # 打印了 skill 流程


def test_cmd_method_lists_when_empty(capsys):
    import argparse
    from psyclaw.cli import cmd_method
    rc = cmd_method(argparse.Namespace(method_id=None))
    assert rc == 0
    out = capsys.readouterr().out
    assert "sample-size" in out and "confound-control" in out
