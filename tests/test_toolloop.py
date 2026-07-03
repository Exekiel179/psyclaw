"""纯工具层循环测试 —— parse(纯)+ build/catalog + run_tool_loop(fake provider 离线)。"""

from __future__ import annotations

from psyclaw import toolloop as TL


class FakeProvider:
    """按脚本逐轮返回回复(每次 chat 弹一条);模拟模型的工具调用与最终答案。"""
    name = "fake"

    def __init__(self, replies):
        self.replies = list(replies)
        self.chats = 0

    def chat(self, messages, system=""):
        self.chats += 1
        r = self.replies.pop(0) if self.replies else "最终答案"
        return iter([r])


def _tools():
    state = {"writes": 0}

    def echo(a):
        return f"echoed {a.get('x')}"

    def writer(a):
        state["writes"] += 1
        return "wrote"

    tools = {
        "echo": {"desc": "回声", "args": "x", "run": echo, "side_effect": False},
        "writer": {"desc": "写", "args": "x", "run": writer, "side_effect": True},
    }
    return tools, state


# --- parse_tool_calls ---------------------------------------------------------

def test_parse_single():
    r = '前言\n```tool\n{"name": "search", "args": {"query": "焦虑"}}\n```\n后语'
    calls = TL.parse_tool_calls(r)
    assert calls == [{"name": "search", "args": {"query": "焦虑"}}]


def test_parse_multiple():
    r = ('```tool\n{"name":"a","args":{}}\n```\n'
         '```tool\n{"name":"b","args":{"k":1}}\n```')
    names = [c["name"] for c in TL.parse_tool_calls(r)]
    assert names == ["a", "b"]


def test_parse_none():
    assert TL.parse_tool_calls("没有工具调用的普通回复") == []


def test_parse_malformed_json():
    calls = TL.parse_tool_calls("```tool\n{not json}\n```")
    assert calls[0]["name"] is None and "JSON" in calls[0]["error"]


def test_parse_missing_name():
    calls = TL.parse_tool_calls('```tool\n{"args": {}}\n```')
    assert calls[0]["name"] is None and "name" in calls[0]["error"]


# --- build_tools / catalog ----------------------------------------------------

def test_build_tools_shape():
    tools = TL.build_tools(".")
    assert {"search", "read_file", "save_file", "kg_query", "recall"} <= set(tools)
    assert tools["save_file"]["side_effect"] is True
    assert tools["search"]["side_effect"] is False


def test_catalog_lists_tools():
    cat = TL.render_tool_catalog(TL.build_tools("."))
    assert "```tool" in cat and "save_file" in cat and "[副作用" in cat


# --- run_tool_loop ------------------------------------------------------------

def test_loop_calls_tool_then_answers():
    prov = FakeProvider(['```tool\n{"name":"echo","args":{"x":1}}\n```', "最终答案"])
    tools, _ = _tools()
    res = TL.run_tool_loop(prov, "sys", [{"role": "user", "content": "q"}], tools=tools)
    assert res["stopped"] == "answered"
    assert res["final"] == "最终答案"
    assert res["iters"] == 2
    assert res["trace"][0]["output"] == "echoed 1"


def test_loop_max_iters():
    prov = FakeProvider(['```tool\n{"name":"echo","args":{}}\n```'] * 10)
    tools, _ = _tools()
    res = TL.run_tool_loop(prov, "s", [{"role": "user", "content": "q"}],
                           tools=tools, max_iters=3)
    assert res["stopped"] == "max_iters" and res["iters"] == 3


def test_side_effect_denied_without_approval():
    prov = FakeProvider(['```tool\n{"name":"writer","args":{}}\n```', "done"])
    tools, state = _tools()
    res = TL.run_tool_loop(prov, "s", [{"role": "user", "content": "q"}],
                           tools=tools, approve=lambda c: False)
    assert "未批准" in res["trace"][0]["output"]
    assert state["writes"] == 0


def test_side_effect_runs_with_approval():
    prov = FakeProvider(['```tool\n{"name":"writer","args":{}}\n```', "done"])
    tools, state = _tools()
    TL.run_tool_loop(prov, "s", [{"role": "user", "content": "q"}],
                     tools=tools, approve=lambda c: True)
    assert state["writes"] == 1


def test_unknown_tool_reported():
    prov = FakeProvider(['```tool\n{"name":"nope","args":{}}\n```', "done"])
    tools, _ = _tools()
    res = TL.run_tool_loop(prov, "s", [{"role": "user", "content": "q"}], tools=tools)
    assert "未知工具" in res["trace"][0]["output"]


def test_emit_called_per_tool():
    prov = FakeProvider(['```tool\n{"name":"echo","args":{}}\n```', "done"])
    tools, _ = _tools()
    events = []
    TL.run_tool_loop(prov, "s", [{"role": "user", "content": "q"}],
                     tools=tools, emit=events.append)
    assert events and "echo" in events[0]
