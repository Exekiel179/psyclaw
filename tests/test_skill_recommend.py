"""按研究类型推荐外部技能包 —— normalize_type / score_skill / recommend_skills。"""

from __future__ import annotations

from psyclaw.skills import recommend as R


def _sk(name, desc, category="domain", source="/ext"):
    return {"name": name, "description": desc, "category": category, "source": source}


def test_normalize_type_aliases():
    assert R.normalize_type("meta-loop") == "meta"
    assert R.normalize_type("lit-loop") == "lit-review"
    assert R.normalize_type("qual-loop") == "qualitative"
    assert R.normalize_type("analysis") == "analysis"
    assert R.normalize_type("nonsense") is None


def test_score_skill_counts_keyword_hits():
    s = _sk("meta-tool", "random-effects meta-analysis with forest plot")
    sc = R.score_skill(s, R.RESEARCH_TYPE_KEYWORDS["meta"])
    assert sc["score"] >= 2
    assert "meta-analysis" in sc["matched"]


def test_recommend_matches_research_type():
    skills = [
        _sk("forge-meta", "random-effects meta-analysis, heterogeneity, forest plot"),
        _sk("forge-qual", "thematic analysis of interview transcripts (COREQ)"),
        _sk("forge-lit", "systematic review + PRISMA screening"),
        _sk("unrelated", "make slides and posters"),
    ]
    meta = R.recommend_skills("meta-loop", skills=skills)
    assert meta and meta[0]["name"] == "forge-meta"
    assert all(s["name"] != "unrelated" for s in meta)

    qual = {s["name"] for s in R.recommend_skills("qualitative", skills=skills)}
    assert "forge-qual" in qual and "forge-meta" not in qual


def test_recommend_unknown_type_returns_empty():
    assert R.recommend_skills("bogus", skills=[_sk("x", "meta-analysis")]) == []


def test_recommend_external_only_excludes_bundled():
    skills = [
        _sk("bundled-meta", "meta-analysis toolkit", source="bundled"),
        _sk("ext-meta", "meta-analysis toolkit", source="/ext"),
    ]
    names = {s["name"] for s in R.recommend_skills("meta", skills=skills)}
    assert names == {"ext-meta"}


def test_recommend_respects_top_k():
    skills = [_sk(f"m{i}", "regression anova statistic") for i in range(20)]
    assert len(R.recommend_skills("analysis", skills=skills, top_k=5)) == 5
