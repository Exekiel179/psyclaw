"""来源路由树测试 —— classify_task / route(纯) + execute_route 主通道→兜底分发。"""

from __future__ import annotations

from psyclaw import search_router as SR


def test_classify_local():
    assert SR.classify_task("我们之前讨论过的那个效应量") == "local"
    assert SR.classify_task("上次你说的方法叫什么") == "local"


def test_classify_trend():
    assert SR.classify_task("焦虑研究近年的趋势如何") == "trend"
    assert SR.classify_task("this field's evolution over time") == "trend"


def test_classify_factual():
    assert SR.classify_task("谁最早提出这个理论") == "factual"
    assert SR.classify_task("Cronbach's alpha 的定义是什么") == "factual"


def test_classify_conceptual_default():
    assert SR.classify_task("正念如何影响情绪调节的机制") == "conceptual"
    assert SR.classify_task("随便一句没有明显信号的话") == "conceptual"


def test_route_has_primary_and_fallback():
    for t in SR.VALID_TYPES:
        plan = SR.route("q", t)
        assert plan["task_type"] == t
        assert plan["primary"]["source"] and plan["primary"]["mode"]
        assert plan["fallback"]["source"] and plan["fallback"]["mode"]
        assert plan["primary"] != plan["fallback"]  # 兜底必与主通道不同


def test_route_unknown_type_falls_to_classify():
    plan = SR.route("焦虑近年趋势", task_type="bogus")
    assert plan["task_type"] == "trend"


def test_route_trend_is_temporal_academic():
    p = SR.route("q", "trend")["primary"]
    assert p == {"source": "academic", "mode": "temporal"}


def test_route_local_primary_is_local_exact():
    p = SR.route("q", "local")["primary"]
    assert p == {"source": "local", "mode": "exact"}


def test_execute_uses_primary_when_hits(monkeypatch):
    def fake(source, mode, query, project_dir, limit):
        return [{"title": f"hit via {source}/{mode}"}]
    monkeypatch.setattr(SR, "_run_channel", fake)
    plan = SR.route("q", "conceptual")
    res = SR.execute_route(plan, "q")
    assert res["used_fallback"] is False
    assert res["used"] == plan["primary"]
    assert res["results"]


def test_execute_falls_back_when_primary_empty(monkeypatch):
    def fake(source, mode, query, project_dir, limit):
        # 主通道(academic/semantic)空,兜底(local/semantic)有货
        if source == "academic":
            return []
        return [{"title": "from fallback"}]
    monkeypatch.setattr(SR, "_run_channel", fake)
    plan = SR.route("q", "conceptual")
    res = SR.execute_route(plan, "q")
    assert res["used_fallback"] is True
    assert res["used"] == plan["fallback"]
    assert res["results"][0]["title"] == "from fallback"
