from __future__ import annotations

import json

from psyclaw.materials import convert_to_markdown


def test_convert_csv_writes_markdown_and_replayable_audit(tmp_path):
    source = tmp_path / "scores.csv"
    source.write_text("id,score\n1,3\n", encoding="utf-8")
    res = convert_to_markdown(source)
    assert res["ok"] and res["backend"] == "stdlib"
    assert "| id | score |" in (tmp_path / "scores.md").read_text(encoding="utf-8")
    audit = json.loads((tmp_path / "scores.md.conversion.json").read_text(encoding="utf-8"))
    assert audit["source_sha256"] == res["source_sha256"]
    assert audit["output_sha256"] == res["output_sha256"]


def test_convert_html_and_missing_file_are_honest(tmp_path):
    source = tmp_path / "page.html"
    source.write_text("<h1>标题</h1><p>正文</p>", encoding="utf-8")
    res = convert_to_markdown(source)
    assert res["ok"] and "标题" in (tmp_path / "page.md").read_text(encoding="utf-8")
    missing = convert_to_markdown(tmp_path / "missing.pdf")
    assert missing["ok"] is False and missing["status"] == "missing"
