"""feat-149:空回复——不再渲染丑陋空框 + deepseek reasoning_content 兜底。

用户反馈:回复为空时终端显示一个空白边框方框 + 「自动恢复 1/2」,confusing。
根因二:①StreamBlock 在 __init__ 就打表头,空回复→留下空框;②openai_compat
只 yield delta.content,deepseek 把内容放 reasoning_content 时整条丢失=空回复。
"""
from __future__ import annotations

import io

from psyclaw import ui


def _make_block(title="PsyClaw"):
    blk = ui.StreamBlock(title)
    buf = io.StringIO()
    blk._out = buf
    return blk, buf


# ---- StreamBlock:空内容不渲染框 -----------------------------------------------

def test_empty_block_renders_nothing(monkeypatch):
    """从不 write 就 close(空回复)→ 不打表头/边框,零噪音。"""
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    blk = ui.StreamBlock("PsyClaw · deepseek")
    blk.close()                         # 没有任何 write
    printed = out.getvalue()
    assert "╭" not in printed and "╰" not in printed   # 无空框
    assert "deepseek" not in printed                    # 连表头都不打


def test_nonempty_block_still_has_border(monkeypatch):
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    blk = ui.StreamBlock("PsyClaw")
    blk.write("有内容")
    blk.close()
    printed = out.getvalue()
    assert "╭" in printed and "╰" in printed            # 有内容照常成框
    assert "有内容" in printed


def test_header_deferred_until_first_write(monkeypatch):
    """表头延迟到首个 chunk——未写入前不占屏。"""
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    blk = ui.StreamBlock("PsyClaw")
    assert out.getvalue() == ""         # 构造时不打任何东西
    blk.write("x")
    assert "╭" in out.getvalue()        # 首次 write 才打表头


# ---- openai_compat:reasoning_content 兜底 -------------------------------------

def _fake_sse(chunks):
    import json
    return [json.dumps(c) for c in chunks]


def test_reasoning_content_used_when_content_empty(monkeypatch):
    from psyclaw.providers.openai_compat import OpenAICompatProvider
    p = OpenAICompatProvider.__new__(OpenAICompatProvider)
    p.model = "deepseek-v4-flash"
    p.base_url = "https://api.deepseek.com"
    p.api_key = "x"
    p.last_stop_reason = ""
    # 全在 reasoning_content,content 始终空
    events = _fake_sse([
        {"choices": [{"delta": {"reasoning_content": "结论是 42"}}]},
        {"choices": [{"delta": {"content": ""}, "finish_reason": "stop"}]},
    ])
    monkeypatch.setattr(p, "_post_sse", lambda *a, **k: iter(events))
    out = "".join(p.chat([{"role": "user", "content": "q"}]))
    assert "42" in out                   # reasoning 兜底,不再整条空


def test_content_preferred_over_reasoning(monkeypatch):
    from psyclaw.providers.openai_compat import OpenAICompatProvider
    p = OpenAICompatProvider.__new__(OpenAICompatProvider)
    p.model = "deepseek-v4-flash"
    p.base_url = "https://api.deepseek.com"
    p.api_key = "x"
    p.last_stop_reason = ""
    events = _fake_sse([
        {"choices": [{"delta": {"reasoning_content": "想:", "content": "正文答案"}}]},
    ])
    monkeypatch.setattr(p, "_post_sse", lambda *a, **k: iter(events))
    out = "".join(p.chat([{"role": "user", "content": "q"}]))
    assert "正文答案" in out
    assert "想:" not in out              # 有正文时不掺 reasoning
