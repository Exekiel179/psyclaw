"""按研究类型给已发现的技能包(AcademicForge/AJS 等)做推荐路由。

`list_skills` 只是「发现 + 呈现」;本模块补「**路由指引**」:据研究类型(文献综述/元分析/实证/质性)
用关键词打分,从发现到的外部技能包里挑出最相关的几个,供研究者在对应 loop 里挑用。

纯确定性打分(关键词命中计数),可单测;不执行任何 skill(执行属宿主 Agent)。关键词特意选**具体**词
(meta-analysis / thematic / 计量 …)避免 metadata 之类误命中;中英双语兼顾(AcademicForge 英文、AJS 中文)。
"""

from __future__ import annotations

from psyclaw.skills.loader import list_skills

# loop 命令名 / workflow id / 中文名 → 规范研究类型
# (v0.3 feat-034:补中文别名——REPL/CLI 高频入口,此前『元分析』→None 直接查不到)
_TYPE_ALIASES = {
    "lit-loop": "lit-review", "review-lit": "lit-review", "lit": "lit-review",
    "meta-loop": "meta",
    "analysis-loop": "analysis",
    "qual-loop": "qualitative", "qual": "qualitative",
    # 中文别名(normalize 已 strip+lower,中文不受 lower 影响,直接映射)
    "文献综述": "lit-review", "文献回顾": "lit-review", "综述": "lit-review",
    "系统综述": "lit-review", "文献": "lit-review",
    "元分析": "meta", "荟萃分析": "meta", "荟萃": "meta", "meta分析": "meta",
    "实证": "analysis", "实证分析": "analysis", "实证研究": "analysis",
    "数据分析": "analysis", "统计分析": "analysis", "定量": "analysis",
    "定量研究": "analysis", "量化研究": "analysis",
    "质性": "qualitative", "质性研究": "qualitative", "定性": "qualitative",
    "定性研究": "qualitative", "访谈研究": "qualitative", "主题分析": "qualitative",
}

RESEARCH_TYPE_KEYWORDS: dict[str, list[str]] = {
    "lit-review": [
        "literature", "systematic review", "scoping review", "prisma", "screening",
        "bibliograph", "citation", "synthesis", "narrative review", "search strateg",
        "文献", "综述", "检索", "筛选",
    ],
    "meta": [
        "meta-analysis", "meta analysis", "effect size", "forest plot", "funnel plot",
        "heterogeneity", "random-effects", "random effects", "fixed-effect", "pooled",
        "publication bias", "mars", "元分析", "效应量", "异质", "漏斗图",
    ],
    "analysis": [
        "regression", "anova", "t-test", "ttest", "mixed model", "multilevel",
        "structural equation", " sem ", "factor analysis", "mediation", "moderation",
        "econometric", "causal", "statistic", "pandas", "spss", "stata", "dataframe",
        "machine learning", "回归", "统计", "计量", "因子", "中介", "调节", "机器学习",
    ],
    "qualitative": [
        "qualitative", "thematic", "grounded theory", "interview", "coding scheme",
        "nvivo", "atlas.ti", "coreq", "ethnograph", "phenomenolog", "transcript",
        "content analysis", "discourse", "质性", "访谈", "编码", "主题分析", "扎根",
    ],
}

VALID_TYPES = tuple(RESEARCH_TYPE_KEYWORDS)


def normalize_type(research_type: str) -> str | None:
    """把 loop 名 / workflow id / 类型名统一到规范研究类型;无法识别返回 None。"""
    rt = (research_type or "").strip().lower()
    rt = _TYPE_ALIASES.get(rt, rt)
    return rt if rt in RESEARCH_TYPE_KEYWORDS else None


def score_skill(skill: dict, keywords: list[str]) -> dict:
    """给单个 skill 打分:命中的关键词数(去重)。返回 {score, matched}。"""
    text = f" {skill.get('name', '')} {skill.get('category', '')} " \
           f"{skill.get('description', '')} ".lower()
    matched = [k.strip() for k in keywords if k in text]
    return {"score": len(matched), "matched": matched}


def recommend_skills(research_type: str, skills: list[dict] | None = None,
                     project_dir: str = ".", top_k: int = 8,
                     external_only: bool = True) -> list[dict]:
    """据研究类型从(默认外部)技能包里推荐最相关的 top_k 个。

    返回按分数降序的 [{...skill, score, matched}](score>0 才入选)。
    ``research_type`` 无法识别 → 返回 []。``external_only`` 只推第三方技能包(内置本就在流程里)。
    """
    rt = normalize_type(research_type)
    if rt is None:
        return []
    pool = skills if skills is not None else list_skills(project_dir)
    if external_only:
        pool = [s for s in pool if s.get("source") != "bundled"]
    kws = RESEARCH_TYPE_KEYWORDS[rt]
    scored = []
    for s in pool:
        sc = score_skill(s, kws)
        if sc["score"] > 0:
            scored.append({**s, "score": sc["score"], "matched": sc["matched"][:4]})
    scored.sort(key=lambda x: (-x["score"], x["name"]))
    return scored[:top_k]
