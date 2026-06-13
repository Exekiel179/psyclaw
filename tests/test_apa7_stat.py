"""W-2: APA7 格式器深化 — tests (stdlib only)."""
from __future__ import annotations

import inspect
import sys
import tempfile
import zipfile
from pathlib import Path

try:
    import pytest
except ModuleNotFoundError:
    class _Approx:
        def __init__(self, v, abs=1e-6, rel=None):
            self._v = v
            self._abs = abs
        def __eq__(self, other):
            return abs(other - self._v) <= self._abs
    class pytest:  # type: ignore[no-redef]
        @staticmethod
        def approx(v, abs=1e-6, rel=None):
            return _Approx(v, abs=abs)

from psyclaw.output.apa7 import (
    format_apa_stat_md,
    format_apa_p,
    format_apa_stat,
    _split_for_italic,
    _table_three_line,
    APA7Document,
)


# ---------------------------------------------------------------------------
# format_apa_stat
# ---------------------------------------------------------------------------

def test_format_apa_stat_two_dec():
    assert format_apa_stat(2.3456) == "2.35"
    assert format_apa_stat(0.1) == ".10"
    assert format_apa_stat(-0.5) == "-.50"


def test_format_apa_stat_no_leading_zero():
    assert format_apa_stat(0.34) == ".34"
    assert format_apa_stat(-0.34) == "-.34"


def test_format_apa_stat_ge_one():
    assert format_apa_stat(1.23) == "1.23"
    assert format_apa_stat(10.0) == "10.00"


def test_format_apa_stat_nan():
    assert format_apa_stat(float("nan")) == "NA"


# ---------------------------------------------------------------------------
# format_apa_p
# ---------------------------------------------------------------------------

def test_format_apa_p_small():
    assert format_apa_p(0.0001) == "*p* < .001"
    assert format_apa_p(0.000) == "*p* < .001"


def test_format_apa_p_normal():
    result = format_apa_p(0.023)
    assert "*p*" in result
    assert ".023" in result
    assert "0." not in result  # no leading zero


def test_format_apa_p_borderline():
    result = format_apa_p(0.001)
    assert "< .001" in result or "= .001" in result


# ---------------------------------------------------------------------------
# format_apa_stat_md — italic stat symbols
# ---------------------------------------------------------------------------

def test_italic_t():
    result = format_apa_stat_md("t(24) = 2.34")
    assert "*t*(24)" in result


def test_italic_F():
    result = format_apa_stat_md("F(2, 45) = 3.21")
    assert "*F*(2, 45)" in result


def test_italic_r():
    result = format_apa_stat_md("r(98) = .34, p = .001")
    assert "*r*(98)" in result


def test_italic_p_eq():
    result = format_apa_stat_md("p = .023")
    assert "*p*" in result


def test_italic_p_less():
    result = format_apa_stat_md("p < .001")
    assert "*p*" in result


def test_italic_cohens_d():
    result = format_apa_stat_md("Cohen's d = 0.45")
    assert "Cohen's *d*" in result


def test_italic_cohens_dz():
    result = format_apa_stat_md("Cohen's dz = 0.45")
    assert "Cohen's *dz*" in result


def test_italic_eta_squared():
    result = format_apa_stat_md("η² = .12")
    assert "*η*²" in result


def test_italic_omega_squared():
    result = format_apa_stat_md("ω² = .10")
    assert "*ω*²" in result


def test_italic_rank_biserial():
    result = format_apa_stat_md("rank-biserial r = .45")
    assert "rank-biserial *r*" in result


def test_italic_cramers_v():
    result = format_apa_stat_md("Cramér's V = .34")
    assert "Cramér's *V*" in result


def test_italic_M_SD():
    result = format_apa_stat_md("M = 2.34, SD = 0.56")
    assert "*M*" in result
    assert "*SD*" in result


def test_no_double_star():
    """已经斜体的不应双重标记。"""
    result = format_apa_stat_md("t(24) = 2.34")
    assert "**t**" not in result


# ---------------------------------------------------------------------------
# _split_for_italic
# ---------------------------------------------------------------------------

def test_split_italic_basic():
    parts = _split_for_italic("This is *italic* text")
    assert ("This is ", False) in parts
    assert ("italic", True) in parts
    assert (" text", False) in parts


def test_split_italic_no_marks():
    parts = _split_for_italic("plain text")
    assert parts == [("plain text", False)]


def test_split_italic_multiple():
    parts = _split_for_italic("*t*(24) = 2.34, *p* < .001")
    italic_parts = [t for t, it in parts if it]
    assert "t" in italic_parts
    assert "p" in italic_parts


# ---------------------------------------------------------------------------
# _table_three_line
# ---------------------------------------------------------------------------

def test_table_three_line_produces_xml():
    headers = ["Variable", "M", "SD", "1", "2"]
    rows = [
        ["Depression", "2.34", "0.56", "—", ""],
        ["Anxiety", "1.89", "0.72", ".45", "—"],
    ]
    xml = _table_three_line(headers, rows, caption="Table 1\nDescriptive Statistics")
    assert "<w:tbl>" in xml
    assert "<w:tr>" in xml
    assert "Depression" in xml
    assert "Anxiety" in xml
    assert "Variable" in xml


def test_table_three_line_has_top_border():
    xml = _table_three_line(["A", "B"], [["1", "2"]])
    # top border on header row
    assert 'w:val="single"' in xml


def test_table_three_line_no_caption():
    xml = _table_three_line(["X"], [["1"]])
    # No caption paragraph
    assert xml.startswith("<w:tbl>")


def test_table_three_line_with_caption():
    xml = _table_three_line(["X"], [["1"]], caption="Table 1")
    # Caption paragraph before table
    assert "<w:p>" in xml
    assert "<w:tbl>" in xml
    assert xml.index("<w:p>") < xml.index("<w:tbl>")


# ---------------------------------------------------------------------------
# APA7Document with stat table
# ---------------------------------------------------------------------------

def test_document_add_stat_table_md():
    doc = APA7Document(title="Test")
    doc.add_stat_table(
        "Table 1\nCorrelation Matrix",
        ["Variable", "1", "2", "3"],
        [["Age", "—", ".34", ".21"],
         ["Income", "", "—", ".56"],
         ["Stress", "", "", "—"]],
    )
    md = doc.to_markdown()
    assert "Table 1" in md
    assert "Variable" in md
    assert "Age" in md
    assert "|" in md  # Markdown table


def test_document_add_stat_table_docx(tmp_path):
    doc = APA7Document(title="Test Study", authors="Author A")
    doc.add_heading("Results", 1)
    doc.add_paragraph("The analysis revealed significant findings.")
    doc.add_stat_table(
        "Table 1\nDescriptive Statistics",
        ["Scale", "M", "SD", "α"],
        [["Depression", "14.2", "3.4", ".89"],
         ["Anxiety", "11.1", "2.9", ".87"]],
    )
    out = tmp_path / "test.docx"
    doc.to_docx(out)
    assert out.exists()
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        assert "word/document.xml" in names
        doc_xml = z.read("word/document.xml").decode("utf-8")
        assert "<w:tbl>" in doc_xml
        assert "Depression" in doc_xml


def test_document_stat_paragraph_italic(tmp_path):
    """段落中的 *stat* 标记应在 docx 中生成斜体 run。"""
    doc = APA7Document(title="T")
    doc.add_paragraph("The correlation was *r*(45) = .34, *p* < .001.")
    out = tmp_path / "t.docx"
    doc.to_docx(out)
    with zipfile.ZipFile(out) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    # Italic run should contain <w:i/>
    assert "<w:i/>" in xml


# ---------------------------------------------------------------------------
# Self-run block
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in fns:
        sig = inspect.signature(fn)
        try:
            if "tmp_path" in sig.parameters:
                with tempfile.TemporaryDirectory() as d:
                    fn(Path(d))
            else:
                fn()
            print(f"  ✓ {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  ✗ {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ✗ {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
