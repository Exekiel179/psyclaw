"""agent 模式流式输出(feat-188):边流边显示,但藏掉 ```tool 协议块。

此前 agent 模式把整段回复 `"".join` 完才处理,用户全程干等——而流本来就是逐块
消费的,只是被静默拼掉了。加 on_chunk 即可流出来;难点是别把工具调用的 JSON
喷给用户(协议噪声),且 chunk 可能在围栏中间断开。
"""
from __future__ import annotations

from psyclaw.toolloop import ToolBlockFilter, run_tool_loop


def _drain(chunks):
    f = ToolBlockFilter()
    out = "".join(f.feed(c) for c in chunks)
    return out + f.flush()


def test_plain_text_passes_through():
    assert _drain(["你好", "世界"]) == "你好世界"


def test_tool_block_is_hidden():
    got = _drain(['正在检索。', '```tool\n{"name":"lit_search"}\n```', '完成。'])
    assert got == "正在检索。完成。"
    assert "lit_search" not in got


def test_fence_split_across_chunks():
    """chunk 可能把 ```tool 从中间切开——半截围栏绝不能漏出去。"""
    got = _drain(["前文", "``", "`to", "ol\n{}\n", "```", "后文"])
    assert got == "前文后文"
    assert "`" not in got


def test_closing_fence_split_across_chunks():
    got = _drain(["a", "```tool\n{}\n`", "``", "b"])
    assert got == "ab"


def test_unclosed_tool_block_is_dropped_on_flush():
    """截断的 tool 块(provider 被 max_tokens 掐断)不该把半截 JSON 显示给用户。"""
    got = _drain(["正文", '```tool\n{"name":"lit_se'])
    assert got == "正文"


def test_multiple_tool_blocks():
    got = _drain(["A", "```tool\n{}\n```", "B", "```tool\n{}\n```", "C"])
    assert got == "ABC"


class _StubProvider:
    name = "stub"
    last_stop_reason = ""

    def __init__(self, script):
        self.script = list(script)

    def chat(self, messages, system=""):
        for c in self.script.pop(0):
            yield c


def test_run_tool_loop_streams_chunks_when_on_chunk_given():
    seen = []
    p = _StubProvider([["最", "终", "答案"]])
    res = run_tool_loop(p, "sys", [{"role": "user", "content": "hi"}],
                        tools={}, on_chunk=seen.append)
    assert "".join(seen) == "最终答案"
    assert res["final"] == "最终答案"


def test_run_tool_loop_hides_tool_json_from_stream():
    seen = []
    p = _StubProvider([['查一下', '```tool\n{"name":"nope","args":{}}\n```'],
                       ["查完了"]])
    res = run_tool_loop(p, "sys", [{"role": "user", "content": "hi"}],
                        tools={}, on_chunk=seen.append)
    shown = "".join(seen)
    assert "nope" not in shown           # 协议噪声不外泄
    assert "查一下" in shown and "查完了" in shown
    assert res["final"] == "查完了"


def test_run_tool_loop_without_on_chunk_still_works():
    """不传 on_chunk 时行为不变(向后兼容)。"""
    p = _StubProvider([["ok"]])
    res = run_tool_loop(p, "sys", [{"role": "user", "content": "hi"}], tools={})
    assert res["final"] == "ok"
