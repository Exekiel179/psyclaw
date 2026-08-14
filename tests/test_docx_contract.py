"""DOCX fixture regression: structure and bytes must remain stable."""
from __future__ import annotations

from pathlib import Path

import pytest

from psyclaw.output.apa7 import APA7Document
from psyclaw.output import apa7
from psyclaw.output.docx_contract import inspect_docx


def _fixture() -> APA7Document:
    doc = APA7Document(title="中文标题 / Stable Title", authors="Li, Ming", affiliation="PsyClaw Lab")
    doc.set_abstract("摘要含有 **粗体** 与 *斜体*。", keywords=["中文", "fixture"])
    doc.add_heading("方法", 1)
    doc.add_heading("参与者", 2)
    doc.add_heading("材料", 3)
    doc.add_paragraph_with_footnote("这是一段带有 *t*(12) = 2.20, *p* = .048 的中文正文。",
                                   "脚注：这是一个可重放的来源说明。")
    doc.add_stat_table("Table 1\n描述统计", ["变量", "M", "SD"], [["焦虑", "3.20", "0.80"]])
    doc.add_reference("Li, M. (2026). *A stable fixture*. Journal of Testing, 1, 1-2.")
    return doc


def test_fixture_docx_contract_and_binary_stability(tmp_path: Path):
    first, second = tmp_path / "first.docx", tmp_path / "second.docx"
    _fixture().to_docx(first)
    _fixture().to_docx(second)
    one, two = inspect_docx(first), inspect_docx(second)
    assert one["ok"], one["errors"]
    assert two["ok"], two["errors"]
    assert one["sha256"] == two["sha256"]
    assert one["tables"] == 1
    assert one["footnotes"] == 3  # separator + continuation + one user note
    assert "中文标题 / Stable Title" in one["texts"]


def test_contract_fails_closed_for_non_docx(tmp_path: Path):
    fake = tmp_path / "broken.docx"
    fake.write_text("not a zip", encoding="utf-8")
    result = inspect_docx(fake)
    assert result["ok"] is False
    assert result["errors"]


def test_latex_export_uses_same_document_model(tmp_path: Path):
    out = tmp_path / "paper.tex"
    result = _fixture().to_latex(out)
    text = result.read_text(encoding="utf-8")
    assert result == out
    assert "\\documentclass[12pt]{article}" in text
    assert "\\section{方法}" in text
    assert "\\begin{tabular}" in text
    assert "\\textit{t}" in text


def test_export_cli_latex(tmp_path: Path, capsys):
    source = tmp_path / "draft.md"
    source.write_text("# Title\n\n正文。\n", encoding="utf-8")
    out = tmp_path / "paper.tex"
    assert apa7.export_cli([str(source), "--format", "latex", "--latex", str(out)]) == 0
    assert out.exists()
    assert "LaTeX 输出完成" in capsys.readouterr().out


def test_export_cli_keeps_artifacts_and_fails_when_contract_fails(tmp_path, monkeypatch, capsys):
    source = tmp_path / "draft.md"
    source.write_text("# Title\n\n正文。\n", encoding="utf-8")
    monkeypatch.setattr(apa7, "inspect_docx", lambda path: {"ok": False, "errors": ["坏样式"]},
                        raising=False)
    # Import happens inside export_cli so patch the contract module, not a stale alias.
    monkeypatch.setattr("psyclaw.output.docx_contract.inspect_docx",
                        lambda path: {"ok": False, "errors": ["坏样式"]})
    out = tmp_path / "out.docx"
    assert apa7.export_cli([str(source), "--docx", str(out)]) == 1
    assert out.exists()
    assert "中间文件已保留" in capsys.readouterr().out
