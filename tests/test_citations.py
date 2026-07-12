"""引用保真核查测试 — extract / audit 纯函数 + load_allowed + run + 质量检查对接。"""

from __future__ import annotations

import json

from psyclaw.psych import citations as C


# ---------------------------------------------------------------------------
# extract_intext_citations
# ---------------------------------------------------------------------------

def test_extract_narrative_forms():
    text = ("Smith (2020) found X. Doe & Roe (2019) showed Y. "
            "Lee et al. (2018) argued Z.")
    canons = {c["canon"] for c in C.extract_intext_citations(text)}
    assert ("smith", "2020") in canons
    assert ("doe", "2019") in canons
    assert ("lee", "2018") in canons


def test_extract_parenthetical_and_semicolon_split():
    text = "Prior work (Doe & Roe, 2019; Lee et al., 2018) established the effect."
    canons = {c["canon"] for c in C.extract_intext_citations(text)}
    assert ("doe", "2019") in canons
    assert ("lee", "2018") in canons


def test_extract_chinese_author():
    canons = {c["canon"] for c in C.extract_intext_citations("张伟 (2021) 讨论了该问题。")}
    assert ("张伟", "2021") in canons


def test_extract_ignores_non_citation_parens():
    # 表格插注 / 统计量 / 样本量 都不该被当成引用
    text = "见 (see Table 1)。差异显著 (p < .05)。样本 (N = 2020)。"
    assert C.extract_intext_citations(text) == []


def test_extract_dedupes_repeated_citation():
    text = "Smith (2020) 首次报告。后续 Smith (2020) 又验证。"
    cites = C.extract_intext_citations(text)
    assert len([c for c in cites if c["canon"] == ("smith", "2020")]) == 1


def test_year_suffix_normalized():
    canons = {c["canon"] for c in C.extract_intext_citations("Smith (2020a) 与 Smith (2020b)")}
    assert canons == {("smith", "2020")}


# ---------------------------------------------------------------------------
# _canon_key
# ---------------------------------------------------------------------------

def test_canon_key_parses_variants():
    assert C._canon_key("Smith et al. (2020)") == ("smith", "2020")
    assert C._canon_key("Doe & Roe (2019)") == ("doe", "2019")
    assert C._canon_key("张伟 (2021)") == ("张伟", "2021")
    assert C._canon_key("佚名 (2021a)") == ("佚名", "2021")
    assert C._canon_key("not a key") is None


# ---------------------------------------------------------------------------
# audit_citations
# ---------------------------------------------------------------------------

def test_audit_all_grounded():
    allowed = ["Smith et al. (2020)", "Doe & Roe (2019)"]
    text = "Smith et al. (2020) found X, consistent with (Doe & Roe, 2019)."
    a = C.audit_citations(text, allowed)
    assert a["orphan_n"] == 0
    assert a["grounded_n"] == 2
    assert a["no_fabricated_citations"] is True
    assert a["manual_review"] is False


def test_audit_signal_prefix_parenthetical_grounded():
    # APA 常见的 (e.g., Smith, 2020) / (see Smith, 2020):信号词逗号不得把姓氏误成 "e.g"。
    allowed = ["Smith (2020)"]
    for txt in ["研究支持该点 (e.g., Smith, 2020)。",
                "另见 (see Smith, 2020)。",
                "如 (cf. Smith, 2020) 所述。"]:
        a = C.audit_citations(txt, allowed)
        assert a["orphan_n"] == 0, txt
        assert a["grounded_n"] == 1, txt


def test_audit_detects_orphan_fabrication():
    allowed = ["Smith et al. (2020)"]
    text = "Smith et al. (2020) found X. However, Ghost et al. (2099) claimed W."
    a = C.audit_citations(text, allowed)
    assert a["orphan_n"] == 1
    assert a["orphan"][0]["surname"] == "ghost"
    assert a["no_fabricated_citations"] is False


def test_audit_manual_review_no_corpus():
    a = C.audit_citations("Smith (2020) found X.", [])
    assert a["manual_review"] is True
    # 无语料 → 未检出孤儿(不过度拦),但 method 显式提示人工核
    assert a["orphan_n"] == 0
    assert "人工核" in a["method"]


def test_audit_manual_review_no_citations():
    a = C.audit_citations("这是一段没有任何文内引用的方法学描述。", ["Smith (2020)"])
    assert a["manual_review"] is True
    assert a["cited_n"] == 0


# ---------------------------------------------------------------------------
# load_allowed
# ---------------------------------------------------------------------------

def test_load_allowed_from_evidence_map(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "evidence_map.json").write_text(json.dumps(
        {"references": [{"key": "Smith et al. (2020)"}, {"key": "Doe (2019)"}]}),
        encoding="utf-8")
    keys, source = C.load_allowed(str(tmp_path))
    assert "Smith et al. (2020)" in keys
    assert source == "notes/evidence_map.json"


def test_load_allowed_falls_back_to_lit_search(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "lit_search.json").write_text(json.dumps(
        {"results": [{"title": "T", "authors": ["John Smith"], "year": 2020,
                      "doi": "10.1/x", "abstract": "memory"}]}),
        encoding="utf-8")
    keys, source = C.load_allowed(str(tmp_path))
    assert keys and source == "notes/lit_search.json"


def test_load_allowed_none_when_empty(tmp_path):
    assert C.load_allowed(str(tmp_path)) == ([], None)


# ---------------------------------------------------------------------------
# run_citation_audit (端到端:落 sidecar + 报告)
# ---------------------------------------------------------------------------

def test_run_citation_audit_writes_sidecar_and_flags_orphan(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "evidence_map.json").write_text(json.dumps(
        {"references": [{"key": "Smith et al. (2020)"}]}), encoding="utf-8")
    draft = notes / "lit_review.md"
    draft.write_text("Smith et al. (2020) 是真的。Ghost (2099) 是编的。", encoding="utf-8")

    a = C.run_citation_audit(str(draft), project_dir=str(tmp_path))
    assert a["orphan_n"] == 1
    assert a["no_fabricated_citations"] is False
    sidecar = json.loads((notes / "citation_audit.json").read_text(encoding="utf-8"))
    assert sidecar["corpus_source"] == "notes/evidence_map.json"
    assert (notes / "citation_audit.md").exists()


def test_run_citation_audit_ignores_reference_list_section(tmp_path):
    """参考文献区(证据图谱)本身即语料,不应被当成正文文内引用再核验成孤儿。"""
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "evidence_map.json").write_text(json.dumps(
        {"references": [{"key": "Smith et al. (2020)"}]}), encoding="utf-8")
    draft = notes / "lit_review.md"
    draft.write_text(
        "## 综述\n\nSmith et al. (2020) 报告了效应。\n\n"
        "## 证据图谱(构念 → 支持文献)\n\n"
        "1. John Smith, Jane Doe & Bob Roe (2020). 某标题. https://doi.org/10.1/x\n",
        encoding="utf-8")
    a = C.run_citation_audit(str(draft), project_dir=str(tmp_path))
    # 正文只有 Smith (2020) 一条且已溯源;参考文献里的 Roe/Doe 不应冒出孤儿
    assert a["orphan_n"] == 0
    assert a["no_fabricated_citations"] is True


def test_run_citation_audit_prose_refword_does_not_truncate(tmp_path):
    """正文里散提「参考文献」(如 参考文献管理软件)不得截断正文,后面的杜撰引用仍须被抓到。"""
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "evidence_map.json").write_text(json.dumps(
        {"references": [{"key": "Smith (2020)"}]}), encoding="utf-8")
    draft = notes / "lit_review.md"
    draft.write_text(
        "## 方法\n\n我们用参考文献管理软件整理文献。随后 Ghost (2099) 支持了假设。\n\n"
        "## 参考文献\n\n1. Smith (2020). 某标题.\n",
        encoding="utf-8")
    a = C.run_citation_audit(str(draft), project_dir=str(tmp_path))
    # 正文里的 Ghost(2099) 仍应被抓成孤儿;参考文献区(标题行后)不参与
    assert a["orphan_n"] == 1
    assert a["orphan"][0]["surname"] == "ghost"


def test_run_citation_audit_clean_passes(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "evidence_map.json").write_text(json.dumps(
        {"references": [{"key": "Smith et al. (2020)"}]}), encoding="utf-8")
    draft = notes / "lit_review.md"
    draft.write_text("Smith et al. (2020) found the effect.", encoding="utf-8")
    a = C.run_citation_audit(str(draft), project_dir=str(tmp_path))
    assert a["no_fabricated_citations"] is True
    assert a["orphan_n"] == 0


# ---------------------------------------------------------------------------
# 质量检查对接:WRITE.citations (trigger citation_check, kind "citation")
# ---------------------------------------------------------------------------

def test_gate_blocks_on_orphan(tmp_path):
    from psyclaw.gates.checker import check_artifact
    sidecar = tmp_path / "citation_audit.json"
    sidecar.write_text(json.dumps({"no_fabricated_citations": False, "orphan_n": 2}),
                       encoding="utf-8")
    res = check_artifact(str(sidecar), "citation")
    assert res["passed"] is False
    assert any(b["gate"] == "WRITE.citations" for b in res["blocking"])


def test_gate_passes_when_grounded(tmp_path):
    from psyclaw.gates.checker import check_artifact
    sidecar = tmp_path / "citation_audit.json"
    sidecar.write_text(json.dumps({"no_fabricated_citations": True, "orphan_n": 0}),
                       encoding="utf-8")
    res = check_artifact(str(sidecar), "citation")
    assert res["passed"] is True
