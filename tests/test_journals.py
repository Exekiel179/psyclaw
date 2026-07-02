"""期刊画像层测试 —— 画像加载/匹配 + cite-check 风格核对 + provenance 数据可得性收紧。"""

from __future__ import annotations

import json

from psyclaw.psych import citations as C
from psyclaw.psych import journals as J
from psyclaw import provenance as P


# ---------------------------------------------------------------------------
# journals.py 画像
# ---------------------------------------------------------------------------

def test_load_and_list_journals():
    ids = J.list_journal_ids()
    for jid in ("xinlixuebao", "xinlikexue", "psych-science", "jpsp", "psych-bulletin"):
        assert jid in ids


def test_get_journal_by_id_alias_name():
    assert J.get_journal("jpsp")["id"] == "jpsp"
    assert J.get_journal("心理学报")["id"] == "xinlixuebao"
    assert J.get_journal("Psychological Bulletin")["id"] == "psych-bulletin"
    assert J.get_journal("nope") is None


def test_get_journal_exact_alias_beats_substring():
    # "Psychological Science" 是 psych-science 的精确别名,不能被 xinlikexue 名称
    # "…Journal of Psychological Science" 的子串命中抢走。
    assert J.get_journal("Psychological Science")["id"] == "psych-science"
    assert J.get_journal("心理科学")["id"] == "xinlikexue"


def test_requires_data_availability():
    assert J.requires_data_availability(J.get_journal("psych-science")) is True
    assert J.requires_data_availability(J.get_journal("xinlixuebao")) is False
    assert J.requires_data_availability(None) is False


def test_expected_citation_format():
    assert J.expected_citation_format(J.get_journal("jpsp")) == "author-year"


# ---------------------------------------------------------------------------
# detect_citation_format (纯函数)
# ---------------------------------------------------------------------------

def test_detect_author_year():
    assert C.detect_citation_format("Smith et al. (2020) found X; (Doe, 2019).") == "author-year"


def test_detect_numeric():
    assert C.detect_citation_format("Prior work [1] and [2] and [3] showed X.") == "numeric"


def test_detect_none():
    assert C.detect_citation_format("这段文字没有任何引用。") == "none"


# ---------------------------------------------------------------------------
# cite-check 期刊定制(风格核对为软提示,不改硬判据)
# ---------------------------------------------------------------------------

def test_cite_check_journal_style_ok(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "evidence_map.json").write_text(json.dumps(
        {"references": [{"key": "Smith et al. (2020)"}]}), encoding="utf-8")
    draft = notes / "d.md"
    draft.write_text("Smith et al. (2020) reported the effect.", encoding="utf-8")
    a = C.run_citation_audit(str(draft), project_dir=str(tmp_path), journal="jpsp")
    assert a["journal"] and a["citation_format_expected"] == "author-year"
    assert a["citation_format_detected"] == "author-year"
    assert a["citation_style_ok"] is True
    assert a["red_lines"]


def test_cite_check_journal_style_mismatch(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "evidence_map.json").write_text(json.dumps({"references": []}), encoding="utf-8")
    draft = notes / "d.md"
    draft.write_text("Prior work [1], [2], [3], [4] established the effect.", encoding="utf-8")
    a = C.run_citation_audit(str(draft), project_dir=str(tmp_path), journal="psych-science")
    assert a["citation_format_detected"] == "numeric"
    assert a["citation_style_ok"] is False


def test_cite_check_unknown_journal_notes(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "evidence_map.json").write_text(json.dumps({"references": []}), encoding="utf-8")
    draft = notes / "d.md"
    draft.write_text("text", encoding="utf-8")
    a = C.run_citation_audit(str(draft), project_dir=str(tmp_path), journal="zzz")
    assert a["journal"] is None and "未收录" in a["journal_note"]


# ---------------------------------------------------------------------------
# provenance 期刊定制(要求数据可得性 → 须带数据指纹才算完整)
# ---------------------------------------------------------------------------

def test_provenance_journal_requires_data_fingerprint(tmp_path):
    art = tmp_path / "analysis.py"
    art.write_text('"""可复现分析。"""', encoding="utf-8")
    # psych-science 要求数据可得性,但没给 data → 不完整
    prov = P.build_provenance(str(art), project_dir=str(tmp_path), journal="psych-science")
    assert prov["data_availability_required"] is True
    assert prov["provenance_complete"] is False
    assert prov["data_availability_ok"] is False


def test_provenance_journal_complete_with_data(tmp_path):
    art = tmp_path / "analysis.py"
    art.write_text('"""可复现分析。"""', encoding="utf-8")
    clean = tmp_path / "data" / "clean"
    clean.mkdir(parents=True)
    dcsv = clean / "scores.csv"
    dcsv.write_text("a,b\n1,2\n", encoding="utf-8")
    prov = P.build_provenance(str(art), project_dir=str(tmp_path),
                              data_path=str(dcsv), journal="psych-science")
    assert prov["data_availability_ok"] is True
    assert prov["provenance_complete"] is True


def test_provenance_no_journal_unaffected(tmp_path):
    art = tmp_path / "analysis.py"
    art.write_text('"""可复现分析。"""', encoding="utf-8")
    prov = P.build_provenance(str(art), project_dir=str(tmp_path))
    assert prov["data_availability_required"] is False
    assert prov["provenance_complete"] is True
