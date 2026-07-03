"""来源路由树 —— 据任务类型把检索路由到最合适的**来源 + 模式**(主通道 + 兜底)。

任务类型 → (来源, 模式):
- factual    事实类 → academic + exact(关键词)      —— 谁/何时/定义/具体数字/首次
- conceptual 概念类 → academic + semantic            —— 为什么/机制/关系/综述(默认)
- trend      趋势类 → academic + temporal(按年份窗口)—— 趋势/近年/演变/历史发展
- local      回忆类 → local + exact(会话全文检索)    —— 我之前/上次/我们讨论过

设计要点(呼应「决策树选单一模式有误路由风险」):树只选**主通道**,但**永远带一个兜底通道**,
主通道零命中就走兜底,避免"概念问题被问得很事实"这类误路由把结果打空。
控制流纯确定性(classify_task/route 可单测);真正发检索的 execute_route 是薄分发,
复用既有能力:academic=litsearch(OpenAlex/EuropePMC/arXiv)、local=会话全文检索(feat-013 FTS)。
来源集可扩展(加 web/MCP 源只需在此登记 + execute 里加一条分发),core 不引入网络新依赖。
"""

from __future__ import annotations

VALID_TYPES = ("factual", "conceptual", "trend", "local")

_LOCAL = ("我之前", "我们之前", "上次", "刚才", "刚说", "讨论过", "聊过",
          "提到过", "说过的", "前面提到", "之前我们", "我们讨论", "我们聊",
          "earlier", "last time", "we discussed", "we talked", "previously")
_TREND = ("趋势", "近年", "这些年", "历年", "演变", "发展历程", "发展趋势",
          "增长", "最新进展", "近几年", "历史发展", "over time", "trend",
          "evolution", "recent years", "past decade")
_FACTUAL = ("是谁", "何人", "何时", "哪一年", "哪年", "多少", "几个", "定义",
            "首次", "最早", "发表于", "出自", "是不是", "有没有",
            "who ", "when ", "how many", "what year", "which year",
            "definition of")

# 每种任务类型的检索计划:主通道 + 兜底通道 + 一句理由。
_PLAN = {
    "factual": {
        "primary": {"source": "academic", "mode": "exact"},
        "fallback": {"source": "academic", "mode": "semantic"},
        "rationale": "事实类 → 学术库精确(关键词)检索;零命中回落语义。",
    },
    "conceptual": {
        "primary": {"source": "academic", "mode": "semantic"},
        "fallback": {"source": "local", "mode": "semantic"},
        "rationale": "概念类 → 学术库语义检索;回落本地会话语义召回。",
    },
    "trend": {
        "primary": {"source": "academic", "mode": "temporal"},
        "fallback": {"source": "academic", "mode": "semantic"},
        "rationale": "趋势类 → 学术库按年份窗口做时间序列;回落普通语义。",
    },
    "local": {
        "primary": {"source": "local", "mode": "exact"},
        "fallback": {"source": "academic", "mode": "semantic"},
        "rationale": "回忆类 → 本地会话全文检索;回落学术库语义。",
    },
}


def classify_task(query: str) -> str:
    """据关键词把查询归为 factual|conceptual|trend|local(纯函数)。

    优先级:local(显式回忆意图)> trend > factual > conceptual(默认)。
    """
    q = (query or "").lower()
    if any(k in q for k in _LOCAL):
        return "local"
    if any(k in q for k in _TREND):
        return "trend"
    if any(k in q for k in _FACTUAL):
        return "factual"
    return "conceptual"


def route(query: str, task_type: str | None = None) -> dict:
    """返回检索计划:{task_type, primary, fallback, rationale}。纯函数。

    ``task_type`` 显式给定则用之(不识别的值回落 conceptual);否则 classify_task 自动判。
    """
    t = task_type if task_type in _PLAN else classify_task(query)
    p = _PLAN[t]
    return {"task_type": t, "primary": dict(p["primary"]),
            "fallback": dict(p["fallback"]), "rationale": p["rationale"]}


# ---------------------------------------------------------------------------
# 执行(薄分发:按计划发检索,主通道空则走兜底)。网络/库调用集中在此。
# ---------------------------------------------------------------------------

def _run_channel(source: str, mode: str, query: str, project_dir: str,
                 limit: int) -> list[dict]:
    if source == "local":
        from psyclaw.recall import ContextArchive
        hits = ContextArchive(project_dir).search(query, limit=limit)
        return [{"title": h["user_text"][:120], "detail": h["reply_text"][:200],
                 "ref": f"session:{h['session']}", "source": "local"} for h in hits]
    # source == "academic"
    from psyclaw.psych import litsearch
    if mode == "temporal":
        return _temporal_search(query, limit)
    r = litsearch.search(query, sources=["openalex", "europepmc"], limit=limit)
    return [{"title": p.get("title", ""), "detail": (p.get("abstract") or "")[:200],
             "ref": p.get("doi") or p.get("title", "")[:60], "year": p.get("year"),
             "source": "academic"} for p in r.get("results", [])]


def _temporal_search(query: str, limit: int) -> list[dict]:
    """趋势:按最近若干年份窗口各查一次,汇报每窗命中数(时间序列信号)+ 最新命中。"""
    from psyclaw.psych import litsearch
    windows = ((2020, "2020+"), (2015, "2015+"), (2010, "2010+"))
    out: list[dict] = []
    for year_from, label in windows:
        try:
            r = litsearch.search(query, sources=["openalex"], limit=limit,
                                 year_from=year_from)
            out.append({"title": f"[趋势窗口 {label}] 命中 {r.get('n_deduped', 0)} 条",
                        "detail": "", "ref": f"window:{label}", "source": "academic-trend"})
        except Exception:  # noqa: BLE001
            pass
    return out


def execute_route(plan: dict, query: str, project_dir: str = ".",
                  limit: int = 10) -> dict:
    """按计划执行:主通道零命中 → 兜底通道。返回 {task_type, used, results, used_fallback}。"""
    prim = plan["primary"]
    results = _run_channel(prim["source"], prim["mode"], query, project_dir, limit)
    used, used_fallback = prim, False
    if not results:
        fb = plan["fallback"]
        results = _run_channel(fb["source"], fb["mode"], query, project_dir, limit)
        used, used_fallback = fb, True
    return {"task_type": plan["task_type"], "used": used,
            "results": results, "used_fallback": used_fallback}
