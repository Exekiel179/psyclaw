"""「近三年却拿回 1980 年文献」这条链上的三个 bug(feat-188)。

真实事故(用户实测):
1. 模型写 `--year-from 2021 --year-to 2024` 问「近三年」——2024 是它的训练截止年,
   系统提示从未告诉它今天几号,于是「最新研究」实际停在两年前;
2. 更糟:`--year-from` 传了也没用——lit_search 工具只读 query/sources/limit,
   年份参数被**静默丢掉**,返回 1980/1982 年的经典文献。用户看到的现象是
   「这些研究都太老了」,并会合理地以为该领域没有新研究;
3. 副作用工具在普通对话模式下无法调用,模型只能让用户「切到 agent 模式」——
   而 agent 模式竟然默认关闭,83 个工具默认够不着。
"""
from __future__ import annotations

from datetime import date

from psyclaw.repl import _today_note, _undeclared_args
from psyclaw.toolloop import build_tools


def test_system_prompt_states_current_date():
    note = _today_note()
    assert date.today().isoformat() in note
    assert "训练截止" in note                      # 明令不许拿训练边界当今年


def test_today_note_computes_recent_three_years():
    note = _today_note()
    y = date.today().year
    assert f"{y - 2}–{y}" in note


def test_lit_search_declares_year_params():
    """参数没在规格里声明,桥接层就会把它当未知参数——规格必须跟上实现。"""
    spec = build_tools(".")["lit_search"]["args"]
    assert "year_from" in spec and "year_to" in spec


def test_lit_search_applies_year_filter(monkeypatch):
    from psyclaw.psych import litsearch

    def _fake(query, sources=None, limit=10, year_from=None):
        papers = [litsearch._paper(title=f"P{y}", authors=["A"], year=y,
                                   doi=f"10.1/{y}", abstract="", source="x")
                  for y in (1980, 2019, 2024, 2026)]
        return {"query": query, "per_source": {"x": len(papers)},
                "n_raw": len(papers), "n_deduped": len(papers),
                "n_duplicates": 0, "results": papers}
    monkeypatch.setattr(litsearch, "search", _fake)
    out = build_tools(".")["lit_search"]["run"](
        {"query": "x", "year_from": 2024, "year_to": 2026})
    assert "P2024" in out and "P2026" in out
    assert "P1980" not in out and "P2019" not in out      # 老文献必须被滤掉


def test_lit_search_empty_after_year_filter_says_so(monkeypatch):
    """区间内无命中要说清,别让模型据此断定「该领域没有新研究」。"""
    from psyclaw.psych import litsearch

    def _fake(query, sources=None, limit=10, year_from=None):
        p = [litsearch._paper(title="old", authors=["A"], year=1980, doi="10.1/a",
                              abstract="", source="x")]
        return {"query": query, "per_source": {"x": 1}, "n_raw": 1,
                "n_deduped": 1, "n_duplicates": 0, "results": p}
    monkeypatch.setattr(litsearch, "search", _fake)
    out = build_tools(".")["lit_search"]["run"]({"query": "x", "year_from": 2024})
    assert "无命中" in out and "不要据此断定" in out


def test_undeclared_args_are_detected():
    """工具不认识的参数要能识别出来,以便如实报「该约束未生效」。"""
    assert _undeclared_args({"query": "a", "year_to": 2024},
                            "query:str, limit?:int") == {"year_to"}
    assert _undeclared_args({"query": "a"}, "query:str, limit?:int") == set()


def test_agent_mode_defaults_on():
    """83 个工具默认够不着是死胡同——agent 模式必须默认开(源码级守卫)。"""
    import inspect

    from psyclaw import repl as R
    src = inspect.getsource(R.ReplSession.__init__)
    assert 'self.conf.get("agent_mode", True)' in src, "agent_mode 默认值必须是 True"


def test_agent_mode_can_be_disabled_by_config():
    """留一个关掉的口子:要流式打字机效果的人 config agent_mode=false。"""
    for off in ("false", "0", "off", "no"):
        assert str({"agent_mode": off}.get("agent_mode", True)).lower() in (
            "false", "0", "off", "no")
