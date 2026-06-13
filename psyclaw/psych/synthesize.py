"""文献知识抽取 → 结构化综述合成(P0-3)。

把 ``litsearch.search`` 的检索结果(**真实命中**的论文:题录 + 摘要)抽取为一张
**可核验的证据图谱**(evidence map),再据此合成一段**有据可循**的相关工作综述
(related work)。两层产物各司其职:

  - 确定性骨架(纯函数,无网络 / 无 LLM,可单测):
      · ``citation_key`` / ``format_reference``  —— 题录 → APA 文内引用 / 参考文献
      · ``theme_keywords``                       —— 跨语料高频构念(知识抽取)
      · ``build_evidence_map``                   —— 构念 × 证据 的机器可读图谱
      · ``render_evidence_table``                —— 证据表 + 参考文献列表(markdown)
  - 叙事综述(``synthesize_review``,provider 合成):被严格约束**只能引用所给的
    真实题录键**,严禁编造文献 / 数值 / DOI;provider 缺失或无命中时回落到由证据
    图谱拼出的**确定性骨架**,保证处处可跑。

学术诚信(对应 gates/PSYCLAW.md):综述里每一条引用键都来自真实检索命中的论文
(DOI / 题录可回溯),provider 只能在 references 列表内引用,语料未提及的具体效应量 /
样本量不得杜撰。
"""

from __future__ import annotations

import re
from collections import Counter

# 学术摘要常见停用词(英文为主;OpenAlex/EuropePMC/arXiv 摘要多为英文)。
_STOP = {
    "the", "and", "for", "are", "was", "were", "this", "that", "with", "from",
    "have", "has", "had", "not", "but", "all", "can", "may", "more", "than",
    "such", "been", "between", "within", "into", "these", "those", "which",
    "their", "they", "them", "its", "our", "we", "i", "a", "an", "of", "to",
    "in", "on", "by", "as", "at", "or", "is", "be", "it", "also", "both",
    "study", "studies", "research", "results", "result", "using", "used",
    "based", "show", "shown", "found", "find", "among", "during", "however",
    "while", "across", "associated", "association", "effect", "effects",
    "significant", "significantly", "compared", "analysis", "data", "paper",
    "article", "present", "current", "examined", "examine", "investigate",
    "investigated", "suggest", "suggests", "report", "reported", "well",
    "high", "low", "different", "differences", "difference", "two", "three",
    "one", "group", "groups", "participants", "sample", "n", "p", "ci",
    "model", "models", "test", "tested", "measures", "measure", "measured",
    "role", "factors", "factor", "level", "levels", "increase", "increased",
    "decrease", "decreased", "positive", "negative", "relationship",
    "again", "often", "even", "much", "many", "less", "very", "thus",
    "hence", "therefore", "moreover", "furthermore", "whether", "toward",
    "towards", "via", "per", "due", "given", "via", "could", "would",
    "should", "rather", "still", "yet", "first", "second", "third",
}


# ---------------------------------------------------------------------------
# 题录 → 引用键 / 参考文献(纯函数)
# ---------------------------------------------------------------------------

def _surname(name: str) -> str:
    """从多种来源的作者串中尽力取姓氏。

    - "Smith, John"            → Smith(逗号分隔,姓在前)
    - "Smith J" / "Smith JA"   → Smith(EuropePMC 形式,末尾是首字母缩写)
    - "John Smith"             → Smith(OpenAlex/arXiv 全名,姓在后)
    """
    name = (name or "").strip()
    if not name:
        return ""
    if "," in name:
        return name.split(",", 1)[0].strip()
    toks = name.split()
    if len(toks) == 1:
        return toks[0]
    last = toks[-1].replace(".", "")
    if 1 <= len(last) <= 2 and last.isupper():   # 末尾是缩写 → 姓在最前
        return toks[0]
    return toks[-1]


def citation_key(paper: dict, year: object | None = None) -> str:
    """APA 文内引用键:``Smith (2020)`` / ``Smith & Doe (2020)`` / ``Smith et al. (2020)``。

    ``year`` 可传入消歧后的年份(如 ``"2020a"``);默认用题录年份。
    """
    authors = [a for a in (paper.get("authors") or []) if a and a.strip()]
    yr = year if year is not None else (paper.get("year") or "n.d.")
    if not authors:
        return f"佚名 ({yr})"
    s1 = _surname(authors[0]) or "佚名"
    if len(authors) == 1:
        return f"{s1} ({yr})"
    if len(authors) == 2:
        return f"{s1} & {_surname(authors[1])} ({yr})"
    return f"{s1} et al. ({yr})"


def _doi_url(paper: dict) -> str:
    doi = paper.get("doi")
    if doi:
        doi = doi.replace("https://doi.org/", "").strip()
        return f"https://doi.org/{doi}"
    if paper.get("arxiv_id"):
        return f"https://arxiv.org/abs/{paper['arxiv_id']}"
    return paper.get("oa_url") or ""


def format_reference(paper: dict, year: object | None = None) -> str:
    """APA 风格参考文献条目(作者名按来源原样,不杜撰首字母)。"""
    authors = [a for a in (paper.get("authors") or []) if a and a.strip()]
    if not authors:
        who = "佚名"
    elif len(authors) <= 6:
        who = ", ".join(authors[:-1]) + (" & " + authors[-1] if len(authors) > 1 else authors[0])
    else:
        who = ", ".join(authors[:6]) + ", et al."
    yr = year if year is not None else (paper.get("year") or "n.d.")
    title = (paper.get("title") or "[无题名]").strip().rstrip(".")
    url = _doi_url(paper)
    tail = f" {url}" if url else ""
    return f"{who} ({yr}). {title}.{tail}".strip()


# ---------------------------------------------------------------------------
# 知识抽取:跨语料高频构念(theme / 关键词)
# ---------------------------------------------------------------------------

def _keep_tokens(text: str) -> list[str]:
    toks = re.findall(r"[a-z][a-z\-]{2,}", (text or "").lower())
    return [t for t in toks if t not in _STOP and len(t) > 3]


def theme_keywords(papers: list[dict], top_k: int = 8, min_df: int = 2) -> list[tuple[str, int]]:
    """抽取跨语料反复出现的构念(按**文档频率** DF 排序,而非词频)。

    DF 衡量"多少篇文献提到该词",比原始词频更能反映共识构念(避免单篇摘要刷词)。
    同时纳入相邻保留词构成的二元组(bigram),以捕捉 "working memory" 这类复合构念。
    平局时偏好二元组与更长词(信息量更高)。``min_df`` 自适应:语料过小时降到 1。
    """
    if not papers:
        return []
    if len(papers) < min_df:
        min_df = 1
    df: Counter = Counter()
    for p in papers:
        toks = _keep_tokens(f"{p.get('title', '')} {p.get('abstract', '')}")
        terms = set(toks)
        terms.update(f"{a} {b}" for a, b in zip(toks, toks[1:]))
        df.update(terms)
    items = [(t, c) for t, c in df.items() if c >= min_df]
    items.sort(key=lambda kv: (kv[1], (" " in kv[0]), len(kv[0])), reverse=True)
    return items[:top_k]


# ---------------------------------------------------------------------------
# 证据图谱:构念 × 支持文献(机器可读)
# ---------------------------------------------------------------------------

def _assign_keys(papers: list[dict]) -> list[dict]:
    """给每篇论文挂上**唯一**的文内引用键;同姓同年用 a/b/c 消歧。"""
    base_counts: Counter = Counter()
    enriched: list[dict] = []
    for p in papers:
        base = citation_key(p)
        base_counts[base] += 1
    seen: Counter = Counter()
    for p in papers:
        base = citation_key(p)
        if base_counts[base] > 1:
            suffix = chr(ord("a") + seen[base])
            seen[base] += 1
            yr = f"{p.get('year') or 'n.d.'}{suffix}"
            key = citation_key(p, year=yr)
        else:
            yr = p.get("year")
            key = base
        enriched.append({**p, "_key": key, "_year_label": yr})
    return enriched


def build_evidence_map(goal: str, papers: list[dict],
                       top_k: int = 8, min_df: int = 2) -> dict:
    """把检索命中汇总为机器可读的证据图谱。

    返回 ``{goal, n_papers, year_range, n_oa, themes:[{term, df, cites:[key…]}],
    references:[{key, citation, doi, year, oa}]}``。每条都可回溯到真实题录。
    """
    papers = list(papers or [])
    enriched = _assign_keys(papers)

    references = []
    for p in enriched:
        oa = p.get("oa_status", "unknown")
        references.append({
            "key": p["_key"],
            "citation": format_reference(p, year=p.get("_year_label")),
            "doi": (p.get("doi") or "").replace("https://doi.org/", "") or None,
            "year": p.get("year"),
            "oa": oa in ("gold", "green", "hybrid", "bronze"),
        })

    themes = []
    for term, df in theme_keywords(enriched, top_k=top_k, min_df=min_df):
        cites = [p["_key"] for p in enriched
                 if term in f"{p.get('title', '')} {p.get('abstract', '')}".lower()]
        if cites:
            themes.append({"term": term, "df": df, "cites": cites[:8]})

    years = [p["year"] for p in enriched if isinstance(p.get("year"), int)]
    n_oa = sum(1 for r in references if r["oa"])
    return {
        "goal": goal,
        "n_papers": len(enriched),
        "year_range": [min(years), max(years)] if years else None,
        "n_oa": n_oa,
        "themes": themes,
        "references": references,
    }


def render_evidence_table(emap: dict) -> str:
    """证据图谱 → markdown(构念→证据 表 + 参考文献列表)。"""
    lines: list[str] = []
    if emap.get("themes"):
        lines.append("| 构念 / 主题 | 命中篇数 | 支持文献 |")
        lines.append("|---|---|---|")
        for t in emap["themes"]:
            lines.append(f"| {t['term']} | {t['df']} | "
                         f"{'; '.join(t['cites'])} |")
    else:
        lines.append("_(语料过小或无可抽取构念)_")
    lines.append("")
    lines.append(f"**参考文献(检索命中,共 {emap['n_papers']} 条;"
                 f"开放获取 {emap['n_oa']} 条)**")
    lines.append("")
    for i, r in enumerate(emap.get("references", []), 1):
        badge = " · OA" if r["oa"] else ""
        lines.append(f"{i}. {r['citation']}{badge}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 综述合成(provider 有据合成;缺失则确定性骨架)
# ---------------------------------------------------------------------------

def _grounding_task(goal: str, emap: dict) -> str:
    keys = "\n".join(f"- {r['key']}" for r in emap["references"])
    return (
        f"研究目标:{goal}\n\n"
        "下面是针对该目标**真实检索命中**的文献(可用引用键 + 摘要节选)。请据此写一段"
        "**相关工作 / 背景综述**(related work):梳理核心构念、主要发现、分歧与研究空白"
        "(gap),为后续假设铺垫。铁律(违反即学术不端):\n"
        "① **只能引用下列『可用引用键』中的键**,不得编造任何文献、数值、DOI;\n"
        "② 行文用 APA 文内引用(如:Smith et al. (2020) 发现…);\n"
        "③ 摘要未提及的具体效应量 / 样本量**不要杜撰**,可作概念性综述;\n"
        "④ 客观区分『已有证据』与『研究空白』,点明本研究的切入点。\n\n"
        f"可用引用键:\n{keys}")


def _grounding_context(emap_papers: list[dict]) -> str:
    chunks = []
    for p in emap_papers:
        ab = (p.get("abstract") or "").strip()
        ab = (ab[:500] + "…") if len(ab) > 500 else (ab or "(无摘要)")
        chunks.append(f"[{p['_key']}] {p.get('title', '')}\n  {ab}")
    return "# 文献摘要(只准引用上面列出的键)\n\n" + "\n\n".join(chunks)


def _skeleton_narrative(emap: dict) -> str:
    """无 provider / 无命中时的确定性综述骨架(仍 100% 可回溯)。"""
    if not emap.get("references"):
        return ("_未接入文献检索结果。先运行 `psyclaw lit <检索式>` 命中真实文献后,"
                "本段将据真实题录合成有据综述。_")
    parts = ["> 以下为据检索命中**确定性拼装**的综述骨架(未经 LLM 叙事润色);"
             "每个构念后括注支持文献键,均可回溯。\n"]
    if emap.get("themes"):
        parts.append("**核心构念与证据**:")
        for t in emap["themes"]:
            parts.append(f"- **{t['term']}**(见于 {t['df']} 篇):"
                         f"{'; '.join(t['cites'])}。")
    else:
        parts.append("_(语料过小,未抽取到反复出现的构念。)_")
    parts.append("\n**研究空白**:上述文献尚未直接回答本研究目标所指向的问题,"
                 "构成本研究的切入点(需人工据全文进一步核验)。")
    return "\n".join(parts)


def synthesize_review(goal: str, search_result, provider=None,
                      role: str = "executor", top_k: int = 8,
                      min_df: int = 2) -> dict:
    """检索结果 → 结构化综述。

    ``search_result`` 可为 ``litsearch.search`` 的返回 dict(含 ``results``)或
    论文列表。``provider`` 给定且有命中时用 LLM 合成**有据叙事**(只准引用真实键);
    否则回落到确定性骨架。返回 ``{markdown, evidence_map, grounded, n_papers}``。
    """
    if isinstance(search_result, dict):
        papers = search_result.get("results", [])
    else:
        papers = list(search_result or [])

    emap = build_evidence_map(goal, papers, top_k=top_k, min_df=min_df)
    enriched = _assign_keys(papers)   # 与 emap 键一致(同一确定性算法)

    grounded = bool(provider and papers)
    if grounded:
        from psyclaw.loop import _gen
        narrative = _gen(provider, role, _grounding_task(goal, emap),
                         _grounding_context(enriched)).strip()
        if not narrative or narrative.startswith(f"[{role} 生成失败]"):
            narrative = _skeleton_narrative(emap)
            grounded = False
    else:
        narrative = _skeleton_narrative(emap)

    yr = emap.get("year_range")
    span = f"{yr[0]}–{yr[1]}" if yr else "—"
    head = (f"# 文献综述:{goal}\n\n"
            f"> 自动合成 · 基于 **{emap['n_papers']}** 篇真实检索命中(去重后,"
            f"开放获取 {emap['n_oa']} 篇,年份 {span});下列引用键均可回溯至参考文献。"
            f"{'' if grounded else ' **(LLM 未接入,以下为确定性骨架)**'}\n")
    markdown = (f"{head}\n## 综述\n\n{narrative}\n\n"
                f"## 证据图谱(构念 → 支持文献)\n\n{render_evidence_table(emap)}\n")
    return {"markdown": markdown, "evidence_map": emap,
            "grounded": grounded, "n_papers": emap["n_papers"]}
