"""feat-143:export 行内 Markdown 强调解析——**粗体** / *斜体* / `代码`。

缺陷现场(活体交付 docx 时实锤):
- 正文 `**粗体**` 被 _split_for_italic 的 `\\*([^*]+)\\*` 错误吃成
  「* + 斜体内容 + *」——星号字面量漏进 Word 且语义错(粗体变斜体);
- Abstract / References 走 _p 完全不解析,`**背景**` 原样漏出。
用户按 Markdown 习惯写稿,交付品就带垃圾字符。
"""
from __future__ import annotations

from pathlib import Path
import zipfile

from psyclaw.output.apa7 import (
    APA7Document,
    _split_for_italic,
    _split_inline,
    parse_md,
)


# ---- _split_inline 纯函数 -------------------------------------------------------

def _texts(parts):
    return "".join(t for t, *_ in parts)


def test_bold_parsed_no_literal_asterisks():
    parts = _split_inline("**背景** 本文")
    assert ("背景", True, False, False) in parts      # (text, bold, italic, code)
    assert "*" not in _texts(parts)                    # 星号不再漏进正文


def test_italic_still_works_no_regression():
    parts = _split_inline("This is *italic* text")
    assert ("italic", False, True, False) in parts
    assert "*" not in _texts(parts)


def test_bold_not_mangled_into_italic():
    """回归钉:**粗体** 绝不能被当成斜体(旧 bug 的语义错)。"""
    parts = _split_inline("**粗体**")
    assert parts == [("粗体", True, False, False)]


def test_code_span_parsed():
    parts = _split_inline("见 `script.py` 文件")
    assert ("script.py", False, False, True) in parts
    assert "`" not in _texts(parts)


def test_mixed_bold_italic_code():
    parts = _split_inline("**粗** 与 *斜* 与 `码`")
    flags = {t: (b, i, c) for t, b, i, c in parts}
    assert flags["粗"] == (True, False, False)
    assert flags["斜"] == (False, True, False)
    assert flags["码"] == (False, False, True)


def test_plain_text_untouched():
    assert _split_inline("plain text") == [("plain text", False, False, False)]


def test_empty_string():
    assert _texts(_split_inline("")) == ""


def test_apa_stat_string_italic_preserved():
    """APA 统计串 *t*(24) = 2.34, *p* < .001 —— 既有主用途不回归。"""
    parts = _split_inline("*t*(24) = 2.34, *p* < .001")
    italics = [t for t, b, i, c in parts if i]
    assert "t" in italics and "p" in italics
    assert "*" not in _texts(parts)


def test_split_for_italic_contract_unchanged():
    """既有 _split_for_italic 契约(text, bool)不破——已有测试依赖它。"""
    parts = _split_for_italic("This is *italic* text")
    assert ("italic", True) in parts


# ---- 端到端:docx XML 里真出现 <w:b/> ------------------------------------------

def _docx_xml(doc: APA7Document, tmp_path: Path) -> str:
    out = tmp_path / "t.docx"
    doc.to_docx(out)
    with zipfile.ZipFile(out) as z:
        return z.read("word/document.xml").decode("utf-8")


def test_body_bold_becomes_w_b(tmp_path):
    doc = APA7Document(title="T")
    doc.add_paragraph("**关键** 结论")
    xml = _docx_xml(doc, tmp_path)
    assert "<w:b/>" in xml
    assert "**" not in xml                             # 无字面量残留


def test_abstract_parses_inline_markup(tmp_path):
    """Abstract 此前走 _p 完全不解析——交付 docx 里 `**背景**` 原样漏出。"""
    doc = APA7Document(title="T")
    doc.abstract = "**背景** 本研究探讨 *中介* 效应"
    xml = _docx_xml(doc, tmp_path)
    assert "**" not in xml and "<w:b/>" in xml
    assert "<w:i/>" in xml


def test_references_italic_journal_name(tmp_path):
    """APA 参考文献期刊名需斜体——References 此前也走 _p 不解析。"""
    doc = APA7Document(title="T")
    doc.add_reference("Smith, J. (2020). Title. *Journal of Testing*, 5(2), 1-10.")
    xml = _docx_xml(doc, tmp_path)
    assert "*" not in xml
    assert "<w:i/>" in xml


def test_headings_left_literal(tmp_path):
    """标题本身已由样式加粗,不该再解析行内标记(避免双重语义)。"""
    doc = APA7Document(title="T")
    doc.add_heading("方法", 1)
    xml = _docx_xml(doc, tmp_path)
    assert "方法" in xml


def test_parse_md_end_to_end_bold(tmp_path):
    src = tmp_path / "d.md"
    src.write_text("---\ntitle: T\n---\n\n# Abstract\n\n**背景** 演示\n\n"
                   "# 引言\n\n这里有 **重点** 和 `code`。\n", encoding="utf-8")
    doc = parse_md(src.read_text(encoding="utf-8"))
    xml = _docx_xml(doc, tmp_path)
    assert "**" not in xml and "`" not in xml
    assert "<w:b/>" in xml
