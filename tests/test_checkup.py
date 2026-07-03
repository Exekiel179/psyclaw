"""psyclaw check 一键质检测试 —— 聚合 JARS/引用保真/期刊风格/复现溯源/KG。"""

from __future__ import annotations

import json

from psyclaw.checkup import run_check


def _by_name(res, prefix):
    return next((i for i in res["items"] if i["name"].startswith(prefix)), None)


def test_no_draft_reports_absent(tmp_path):
    res = run_check(project_dir=str(tmp_path))
    jars = _by_name(res, "JARS")
    assert jars["status"] == "absent"
    assert res["passed"] is True          # 缺稿件≠失败,只是没得查


def test_draft_runs_jars_and_citation(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "evidence_map.json").write_text(json.dumps(
        {"references": [{"key": "Smith (2020)"}]}), encoding="utf-8")
    draft = tmp_path / "draft.md"
    draft.write_text("Smith (2020) 支持假设。但 Ghost (2099) 是编的。", encoding="utf-8")
    res = run_check(draft=str(draft), project_dir=str(tmp_path))
    cite = _by_name(res, "引用保真")
    assert cite["status"] == "fail" and "Ghost" in cite["detail"]
    assert res["passed"] is False
    assert _by_name(res, "JARS") is not None


def test_journal_style_item(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "evidence_map.json").write_text(json.dumps({"references": []}),
                                             encoding="utf-8")
    draft = tmp_path / "d.md"
    draft.write_text("Prior work [1], [2], [3], [4] showed X.", encoding="utf-8")
    res = run_check(draft=str(draft), project_dir=str(tmp_path),
                    journal="psych-science")
    style = _by_name(res, "期刊风格")
    assert style is not None and style["status"] == "fail"


def test_provenance_items(tmp_path):
    out = tmp_path / "outputs"
    out.mkdir()
    (out / "analysis.py").write_text('"""x"""', encoding="utf-8")   # 无 provenance 包
    good = out / "meta_analysis.py"
    good.write_text('"""y"""', encoding="utf-8")
    good.with_suffix(".py.provenance.json").write_text(
        json.dumps({"provenance_complete": True}), encoding="utf-8")
    res = run_check(project_dir=str(tmp_path))
    missing = _by_name(res, "复现溯源(analysis.py)")
    ok = _by_name(res, "复现溯源(meta_analysis.py)")
    assert missing["status"] == "fail" and ok["status"] == "pass"


def test_kg_verify_included_when_graph_exists(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "evidence_map.json").write_text(json.dumps(
        {"references": [{"key": "Smith (2020)"}],
         "themes": [{"term": "焦虑", "cites": ["Smith (2020)"]}]}), encoding="utf-8")
    from psyclaw.kg import KnowledgeGraph
    KnowledgeGraph(str(tmp_path)).seed_from_evidence_map(str(tmp_path))
    res = run_check(project_dir=str(tmp_path))
    kgi = _by_name(res, "KG 关系溯源")
    assert kgi is not None and kgi["status"] == "pass"


def test_clean_project_passes(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "evidence_map.json").write_text(json.dumps(
        {"references": [{"key": "Smith (2020)"}]}), encoding="utf-8")
    draft = tmp_path / "d.md"
    draft.write_text(
        "Smith (2020) 发现效应。缺失数据用多重插补处理;剔除 3 名被试(注意检查未过),理由已报告。",
        encoding="utf-8")
    res = run_check(draft=str(draft), project_dir=str(tmp_path))
    cite = _by_name(res, "引用保真")
    assert cite["status"] == "pass"
