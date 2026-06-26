"""可复用 Step 与门禁 — 文献综述流程用。

每个 step.run(ctx) 干活并把产物路径写进 ctx.artifacts[step.id];
每个 gate(ctx) 返回 (ok, reason)。这些都是薄壳——复用既有命令/模块
(litsearch / synthesize / review / clarify),不含重复实现。

新增子功能 `screen_papers` 做成独立纯函数(可单测、可被任何流程或命令直接调用),
体现"子功能可单用、可拼装"。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 门禁(harness 前置约束)
# ---------------------------------------------------------------------------


def gate_clarify_complete(ctx) -> tuple[bool, str]:
    """澄清门禁:澄清卡未全部 resolved → fail-closed(不澄清完不开工)。"""
    from psyclaw.psych.clarify import check_card
    card = check_card(str(ctx.project))
    if card["unresolved"]:
        return False, (f"澄清卡 {card['resolved']}/{card['total']},"
                       f"未解决 {len(card['unresolved'])} 项 —— 先跑 `psyclaw clarify`。")
    return True, "澄清完成"


# ---------------------------------------------------------------------------
# 子功能:PRISMA 相关性初筛(独立纯函数,可单测/可单用)
# ---------------------------------------------------------------------------

_STOP = {
    "the", "and", "for", "with", "from", "that", "this", "are", "was", "were",
    "study", "studies", "research", "effect", "effects", "analysis", "among",
    "between", "based", "using", "their", "have", "has", "not", "but",
    "影响", "研究", "分析", "效应", "关系", "作用", "基于", "探讨", "之间",
}


def _tokens(text: str) -> set[str]:
    """提取内容词:拉丁词(len≥3)+ 中文字符二元组。"""
    low = (text or "").lower()
    latin = {w for w in re.findall(r"[a-z][a-z\-]{2,}", low) if w not in _STOP}
    cjk = re.findall(r"[一-鿿]", low)
    bigrams = {cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1)}
    bigrams -= _STOP
    return latin | bigrams


def screen_papers(papers: list[dict], topic: str,
                  threshold: float = 0.12) -> dict:
    """对题录做确定性相关性初筛(标题+摘要 与 主题 的内容词重叠)。

    返回 {included, excluded, counts, method}。counts 给 PRISMA 筛选数。
    跨语言等导致重叠普遍为 0 时(可能误排全部)→ 诚实降级:全部纳入并标注"待人工复核",
    绝不假装做了筛选(学术诚信)。LLM/人工精筛是后续增强。
    """
    topic_tok = _tokens(topic)
    scored = []
    for p in papers:
        text = f"{p.get('title', '')} {p.get('abstract', '')}"
        ptok = _tokens(text)
        overlap = (len(topic_tok & ptok) / len(topic_tok)) if topic_tok else 0.0
        scored.append((p, overlap))

    kept = [(p, s) for p, s in scored if s >= threshold]
    # 降级:几乎全被排除(很可能跨语言/题录无摘要)→ 不做自动排除,转人工
    degraded = len(kept) <= max(1, len(scored) // 10) and len(scored) > 3
    if degraded:
        included = [p for p, _ in scored]
        excluded: list[dict] = []
        method = "自动初筛不适用(相关性重叠普遍过低,可能跨语言或缺摘要);全部纳入待人工复核"
    else:
        included = [p for p, _ in kept]
        excluded = [{"title": p.get("title", "")[:120], "overlap": round(s, 3),
                     "reason": "低相关(内容词重叠 < 阈值)"}
                    for p, s in scored if s < threshold]
        method = f"自动相关性初筛(内容词重叠 ≥ {threshold});建议人工复核"

    return {
        "included": included,
        "excluded": excluded,
        "counts": {"screened": len(scored), "included": len(included),
                   "excluded": len(excluded)},
        "method": method,
    }


# ---------------------------------------------------------------------------
# Step:文献检索 → screen → synthesize → review
# ---------------------------------------------------------------------------


def step_lit_search(ctx) -> dict:
    """检索 + 去重 + PRISMA 识别计数,缓存题录。复用 litsearch.search。"""
    from psyclaw import ui
    from psyclaw.psych import litsearch
    notes = ctx.project / "notes"
    limit = ctx.data.get("lit_limit", 20)
    r = litsearch.search(ctx.topic, sources=["openalex", "europepmc"], limit=limit)
    (notes / "lit_search.json").write_text(
        json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    (notes / "prisma_search.md").write_text(
        f"# PRISMA — 检索(identification)\n\n- 检索式: {ctx.topic.splitlines()[0][:120]}\n"
        f"- 来源: {r['per_source']}\n- 识别: {r['n_raw']} 条\n"
        f"- 去重后: {r['n_deduped']} 条(去除 {r['n_duplicates']} 重复)\n",
        encoding="utf-8")
    ctx.data["search"] = r
    ctx.artifacts["lit_search"] = "notes/lit_search.json"
    print(ui.dim(f"  识别 {r['n_raw']} · 去重后 {r['n_deduped']}"))
    return {"n_raw": r["n_raw"], "n_deduped": r["n_deduped"]}


def step_screen(ctx) -> dict:
    """PRISMA 筛选:对去重题录做相关性初筛,落 prisma_flow.md + 纳入集。"""
    from psyclaw import ui
    notes = ctx.project / "notes"
    search = ctx.data.get("search") or {}
    papers = search.get("results", [])
    res = screen_papers(papers, ctx.topic)
    ctx.data["included"] = res["included"]
    c = res["counts"]
    (notes / "prisma_flow.md").write_text(
        f"# PRISMA 流程\n\n- 识别(identification): {search.get('n_raw', '?')} 条\n"
        f"- 去重后(records screened): {c['screened']} 条\n"
        f"- 排除(excluded): {c['excluded']} 条\n"
        f"- 纳入(included): {c['included']} 条\n\n"
        f"筛选方法: {res['method']}\n",
        encoding="utf-8")
    ctx.artifacts["screen"] = "notes/prisma_flow.md"
    print(ui.dim(f"  筛选 {c['screened']} → 纳入 {c['included']}(排除 {c['excluded']})"))
    return c


def step_synthesize(ctx) -> dict:
    """据纳入题录合成结构化综述 + 证据图谱。复用 synthesize.synthesize_review。"""
    from psyclaw import ui
    from psyclaw.psych import synthesize
    notes = ctx.project / "notes"
    included = ctx.data.get("included", [])
    syn = synthesize.synthesize_review(
        ctx.topic, {"results": included}, provider=ctx.provider)
    (notes / "lit_review.md").write_text(syn["markdown"], encoding="utf-8")
    (notes / "evidence_map.json").write_text(
        json.dumps(syn["evidence_map"], ensure_ascii=False, indent=2),
        encoding="utf-8")
    ctx.artifacts["synthesize"] = "notes/lit_review.md"
    ctx.data["draft_path"] = str(notes / "lit_review.md")
    tag = "有据叙事" if syn["grounded"] else "确定性骨架(LLM 未接入)"
    print(ui.dim(f"  综述 {syn['n_papers']} 篇 · {tag}"))
    return {"n_papers": syn["n_papers"], "grounded": syn["grounded"]}


def step_review(ctx) -> dict:
    """同行评审产出稿(EIC + 审稿人 + Devil's Advocate)。复用 review.run_review。

    评审对象 = ctx.data['draft_path'](各流程在写作步设置);缺省取 notes/lit_review.md。
    """
    from psyclaw.review import run_review
    draft = ctx.data.get("draft_path") or str(ctx.project / "notes" / "lit_review.md")
    run_review(draft=draft, project_dir=str(ctx.project), auto=ctx.auto)
    if (ctx.project / "notes" / "review_panel.md").exists():
        ctx.artifacts["review"] = "notes/review_panel.md"
    return {}
