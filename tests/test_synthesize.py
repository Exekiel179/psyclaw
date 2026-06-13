"""文献知识抽取 → 综述合成测试(P0-3)。

规格:
  - 知识抽取与证据图谱是**纯函数**:相同题录 → 相同引用键 / 参考文献 / 构念。
  - 学术诚信:综述里的引用键全部来自真实题录;不引入语料外的文献。
  - provider 缺失 / 无命中 → 回落确定性骨架(仍 100% 可回溯),不崩。
  - provider 给定且有命中 → 走有据叙事(grounded=True)。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.psych import synthesize  # noqa: E402
from psyclaw.psych.synthesize import (  # noqa: E402
    build_evidence_map, citation_key, format_reference, synthesize_review,
    theme_keywords,
)

# 三篇手造题录(覆盖三种作者名形式 + 主题复现 working memory)。
PAPERS = [
    {"title": "Working memory training improves fluid intelligence",
     "authors": ["John Smith", "Alice Doe"], "year": 2018,
     "doi": "10.1037/aaa", "abstract": "Working memory training and cognitive "
     "control in adults. Working memory gains transfer to attention.",
     "oa_status": "gold"},
    {"title": "Working memory capacity and attention control",
     "authors": ["Brown JA", "Lee K", "Park S"], "year": 2020,
     "doi": "10.1016/bbb", "abstract": "Working memory capacity predicts "
     "attention control across tasks.", "oa_status": "closed"},
    {"title": "A longitudinal view of cognitive control",
     "authors": ["Wang, Wei"], "year": 2020, "doi": None,
     "abstract": "Cognitive control develops over childhood; attention matters.",
     "oa_status": "green", "arxiv_id": "2001.00001"},
]


class _EchoProvider:
    """把固定叙事一次性 yield 的桩 provider。"""

    name = "echo"

    def __init__(self, text="Smith & Doe (2018) 发现工作记忆训练有迁移效应。"):
        self._text = text

    def chat(self, messages, system=""):
        yield self._text


# ---------------------------------------------------------------------------
# 引用键 / 参考文献(纯函数,跨作者名形式稳健)
# ---------------------------------------------------------------------------

def test_citation_key_handles_name_forms():
    assert citation_key(PAPERS[0]) == "Smith & Doe (2018)"       # 全名:姓在后
    assert citation_key(PAPERS[1]) == "Brown et al. (2020)"      # EuropePMC 缩写
    assert citation_key(PAPERS[2]) == "Wang (2020)"              # 逗号:姓在前


def test_citation_key_no_author():
    assert citation_key({"authors": [], "year": 2021}).startswith("佚名")


def test_format_reference_has_year_title_link():
    ref = format_reference(PAPERS[0])
    assert "(2018)" in ref and "Working memory training" in ref
    assert "doi.org/10.1037/aaa" in ref


def test_format_reference_arxiv_fallback_link():
    ref = format_reference(PAPERS[2])
    assert "arxiv.org/abs/2001.00001" in ref


# ---------------------------------------------------------------------------
# 知识抽取:跨语料高频构念
# ---------------------------------------------------------------------------

def test_theme_keywords_surfaces_recurring_construct():
    themes = dict(theme_keywords(PAPERS, top_k=10, min_df=2))
    # "working memory" 在 2 篇出现;"attention"/"cognitive control" 反复出现。
    keys = " ".join(themes)
    assert "working memory" in themes or "working" in themes
    assert any(t in keys for t in ("attention", "control", "cognitive"))


def test_theme_keywords_empty_corpus():
    assert theme_keywords([]) == []


# ---------------------------------------------------------------------------
# 证据图谱:构念 × 证据,引用键全部可回溯
# ---------------------------------------------------------------------------

def test_evidence_map_structure_and_traceability():
    emap = build_evidence_map("工作记忆训练能否迁移", PAPERS)
    assert emap["n_papers"] == 3
    assert emap["n_oa"] == 2                      # gold + green
    assert emap["year_range"] == [2018, 2020]
    ref_keys = {r["key"] for r in emap["references"]}
    # 每个构念的支持文献键必须都在参考文献里(不得引入语料外文献)。
    for t in emap["themes"]:
        for c in t["cites"]:
            assert c in ref_keys


def test_evidence_map_disambiguates_same_surname_year():
    dup = [
        {"title": "First", "authors": ["Li Ming"], "year": 2020, "abstract": "a"},
        {"title": "Second", "authors": ["Li Ming"], "year": 2020, "abstract": "b"},
    ]
    emap = build_evidence_map("x", dup)
    keys = [r["key"] for r in emap["references"]]
    assert keys[0] != keys[1]                     # 2020a / 2020b 消歧
    assert any("2020a" in k for k in keys) and any("2020b" in k for k in keys)


# ---------------------------------------------------------------------------
# 综述合成:有据叙事 vs 确定性骨架
# ---------------------------------------------------------------------------

def test_synthesize_grounded_with_provider():
    syn = synthesize_review("工作记忆训练能否迁移", {"results": PAPERS},
                            provider=_EchoProvider())
    assert syn["grounded"] is True
    assert syn["n_papers"] == 3
    md = syn["markdown"]
    assert "## 综述" in md and "## 证据图谱" in md
    assert "工作记忆训练有迁移效应" in md          # provider 叙事被纳入
    assert "参考文献" in md


def test_synthesize_skeleton_without_provider():
    syn = synthesize_review("x", {"results": PAPERS}, provider=None)
    assert syn["grounded"] is False
    assert "确定性骨架" in syn["markdown"]
    # 骨架里的构念后括注支持文献键,仍可回溯。
    assert syn["evidence_map"]["n_papers"] == 3


def test_synthesize_empty_results_does_not_crash():
    syn = synthesize_review("x", {"results": []}, provider=_EchoProvider())
    assert syn["grounded"] is False               # 无命中 → 不调用 LLM
    assert syn["n_papers"] == 0
    assert "先运行" in syn["markdown"] or "未接入" in syn["markdown"]


def test_synthesize_accepts_bare_list():
    syn = synthesize_review("x", PAPERS, provider=None)
    assert syn["n_papers"] == 3


def test_synthesize_provider_failure_falls_back_to_skeleton():
    class _Boom:
        name = "boom"

        def chat(self, messages, system=""):
            raise RuntimeError("provider down")

    syn = synthesize_review("x", {"results": PAPERS}, provider=_Boom())
    assert syn["grounded"] is False               # 失败 → 回落骨架,不崩
    assert "## 综述" in syn["markdown"]


# ---------------------------------------------------------------------------
# 自包含 runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print(f"  ✓ {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  ✗ {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ✗ {name}: [ERROR] {type(exc).__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
