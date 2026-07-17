"""feat-155:token 计量——CJK 感知估算 + 累计 + 详细页(诚实省量)。"""
from __future__ import annotations

from psyclaw.token_meter import (
    TokenMeter,
    estimate_tokens,
    naive_baseline_tokens,
    render_token_report,
)


# ---- CJK 感知估算(比字符/4 准) ----------------------------------------------

def test_estimate_ascii():
    # 纯 ASCII ~4 字符/token
    assert 20 <= estimate_tokens("a" * 100) <= 30


def test_estimate_cjk_heavier_than_ascii():
    """同字符数,中文 token 数应明显高于英文(字符/4 会严重低估中文)。"""
    cn = estimate_tokens("研究设计与统计分析方法" * 5)
    en = estimate_tokens("abcdefghij" * 5)
    assert cn > en


def test_estimate_empty():
    assert estimate_tokens("") == 0


# ---- TokenMeter 累计 ----------------------------------------------------------

def test_meter_accumulates_in_out():
    m = TokenMeter()
    m.record_turn(system="系统提示很长", user="问题", reply="回答内容")
    assert m.in_tokens > 0 and m.out_tokens > 0 and m.turns == 1
    m.record_turn(system="s", user="u", reply="r")
    assert m.turns == 2


def test_meter_tracks_real_compaction_saving():
    m = TokenMeter()
    m.record_compaction(dropped_chars=4000)     # 压缩真丢了 4000 字符历史
    assert m.saved_compaction_tokens > 0


def test_meter_total():
    m = TokenMeter()
    m.record_turn(system="aaaa", user="bb", reply="cccc")
    assert m.total_tokens == m.in_tokens + m.out_tokens


# ---- 朴素基线(诚实:完整知识库若每轮全塞) -----------------------------------

def test_naive_baseline_larger_than_lean():
    from psyclaw.context import lean_core
    naive = naive_baseline_tokens(".")
    assert naive > estimate_tokens(lean_core())    # 全量注入远大于瘦核心


# ---- 详细页渲染 ---------------------------------------------------------------

def test_report_shows_session_numbers():
    m = TokenMeter()
    m.record_turn(system="系统" * 100, user="用户问题", reply="模型回答" * 20)
    rep = render_token_report(m, project_dir=".")
    assert "token" in rep.lower()
    assert str(m.turns) in rep                     # 轮数
    assert "输入" in rep and "输出" in rep


def test_report_labels_baseline_honestly():
    """相较朴素全量注入必须明确标注是估算/基线口径,不假装跨产品实测。"""
    m = TokenMeter()
    m.record_turn(system="s" * 50, user="u", reply="r")
    rep = render_token_report(m, project_dir=".")
    assert "估算" in rep or "基线" in rep
    # 不得出现无依据的具体友商名对比
    for brand in ("GPT-4", "Claude 省", "比 ChatGPT"):
        assert brand not in rep


def test_report_fun_conversion():
    m = TokenMeter()
    for _ in range(5):
        m.record_turn(system="研究设计" * 50, user="问题内容", reply="详细回答" * 30)
    rep = render_token_report(m, project_dir=".")
    assert "页" in rep or "相当于" in rep           # 趣味换算(A4 页数等)


def test_report_empty_session_no_crash():
    rep = render_token_report(TokenMeter(), project_dir=".")
    assert isinstance(rep, str) and rep
