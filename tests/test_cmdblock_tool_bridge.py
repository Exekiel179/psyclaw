"""命令块 ↔ 对话工具的桥接:模型写哪套语法都得跑通(feat-187)。

真实死胡同(用户实测,deepseek):
系统提示每轮都在教「直接调 lit_search / lit_snowball / lit_download 工具」,
但那句只在 agent 模式(```tool JSON 协议)成立;默认 chat 模式只执行 ```psyclaw
命令块。于是模型写出 ```psyclaw + `lit_search --query "..." --max 20 --source pubmed`
——工具名配 CLI 语法的四不像。argparse 报 invalid choice,模型据此断定
「PsyClaw 缺少联网检索工具」,放弃检索(而 lit_search 明明可用且能出真结果)。

结论:与其规定模型只能用哪套语法(混用不可避免),不如让两套都通。
"""
from __future__ import annotations

from psyclaw.repl import parse_tool_flags, run_tool_from_cmdline


def test_parse_flags_space_and_equals():
    assert parse_tool_flags(["--query", "burnout", "--limit=5"]) == {
        "query": "burnout", "limit": "5"}


def test_parse_bare_flag_is_true():
    assert parse_tool_flags(["--verify"])["verify"] is True


def test_parse_positional_becomes_query():
    """模型常写 `lit_search "关键词"`,不带 --query。"""
    assert parse_tool_flags(["工作", "倦怠"])["query"] == "工作 倦怠"


def test_parse_dash_to_underscore():
    assert "year_from" in parse_tool_flags(["--year-from", "2020"])


def test_non_tool_returns_none_so_argparse_handles_it():
    """不是工具名 → 返回 None,交回原来的 psyclaw 子命令路径,别抢。"""
    assert run_tool_from_cmdline("gates") is None
    assert run_tool_from_cmdline("export a.md --docx b.docx") is None


def test_tool_name_is_dispatched(monkeypatch):
    from psyclaw import repl as R

    def _fake_build(_p):
        return {"lit_search": {"desc": "", "args": "", "side_effect": False,
                               "run": lambda a: f"OK:{a.get('query')}/{a.get('limit')}"}}
    monkeypatch.setattr("psyclaw.toolloop.build_tools", _fake_build)
    out = R.run_tool_from_cmdline('lit_search --query "burnout" --limit 3')
    assert "OK:burnout/3" in out


def test_common_alias_flags_normalized(monkeypatch):
    """模型爱写 --max/--source/--topic,别因为参数名不同就空手而归。"""
    seen = {}

    def _fake_build(_p):
        return {"lit_search": {"desc": "", "args": "", "side_effect": False,
                               "run": lambda a: seen.update(a) or "ok"}}
    monkeypatch.setattr("psyclaw.toolloop.build_tools", _fake_build)
    run_tool_from_cmdline('lit_search --topic "x" --max 5 --source pubmed')
    assert seen["query"] == "x" and seen["limit"] == "5"
    assert seen["sources"] == "pubmed"


def test_side_effect_tool_refused_without_approval(monkeypatch):
    """命令块路径没有审批环节,写盘/写用户文库的工具不许在此静默执行。"""
    def _fake_build(_p):
        return {"zotero_add": {"desc": "", "args": "", "side_effect": True,
                               "run": lambda a: "WROTE"}}
    monkeypatch.setattr("psyclaw.toolloop.build_tools", _fake_build)
    out = run_tool_from_cmdline("zotero_add --doi 10.1/x")
    assert "未执行" in out and "WROTE" not in out


def test_tool_exception_is_reported_not_swallowed(monkeypatch):
    """工具报错要如实回传——静默失败会让模型误判成「没有这个能力」。"""
    def _boom(a):
        raise RuntimeError("network down")

    def _fake_build(_p):
        return {"lit_search": {"desc": "", "args": "", "side_effect": False,
                               "run": _boom}}
    monkeypatch.setattr("psyclaw.toolloop.build_tools", _fake_build)
    out = run_tool_from_cmdline("lit_search --query x")
    assert "执行出错" in out and "network down" in out
