"""PDF 正文抽取测试 —— stdlib 兜底(未压缩/FlateDecode)+ 质量门 + smart_excerpt 路由。"""

from __future__ import annotations

import zlib
from pathlib import Path

from psyclaw import pdf_extract as PX
from psyclaw.context import smart_excerpt


_SENTENCE = b"Hello World. This is the methods section; we used a Welch t-test (p < .05)."


def _pdf_uncompressed() -> bytes:
    body = b"BT /F1 12 Tf 72 720 Td (" + _SENTENCE + b") Tj ET"
    return (b"%PDF-1.4\n1 0 obj<</Length 90>>\nstream\n" + body
            + b"\nendstream\nendobj\n%%EOF")


def _pdf_flate() -> bytes:
    content = (b"BT (Compressed methods text long enough to pass the quality gate: "
               b"randomized controlled trial with Cohen's d reported.) Tj ET")
    comp = zlib.compress(content)
    return (b"%PDF-1.4\n2 0 obj<</Filter/FlateDecode/Length "
            + str(len(comp)).encode() + b">>\nstream\n" + comp
            + b"\nendstream\nendobj\n%%EOF")


def test_extract_uncompressed(tmp_path):
    res = PX.extract_pdf_text(_write(tmp_path, _pdf_uncompressed()))
    assert res["ok"] is True
    assert "methods section" in res["text"]


def test_extract_flate_compressed(tmp_path):
    res = PX.extract_pdf_text(_write(tmp_path, _pdf_flate()))
    assert res["ok"] is True
    assert "Compressed methods text" in res["text"]


def test_non_pdf_rejected(tmp_path):
    res = PX.extract_pdf_text(_write(tmp_path, b"just some plain text, not a pdf at all"))
    assert res["ok"] is False
    assert "PDF" in res["note"]


def test_no_extractable_text_gives_honest_note(tmp_path):
    # 有 %PDF- 头但无文本流(模拟扫描件/图片型)→ 诚实提示,不吐乱码
    res = PX.extract_pdf_text(_write(tmp_path, b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF"))
    assert res["ok"] is False
    assert res["text"] == ""
    assert "pypdf" in res["note"] or "扫描件" in res["note"]


def test_quality_gate():
    assert PX._looks_like_text("") is False
    assert PX._looks_like_text("short") is False
    assert PX._looks_like_text("a genuinely readable sentence with plenty of letters here.") is True
    # 大量控制/高位字节 → 判为乱码
    assert PX._looks_like_text("".join(chr(x % 8 + 1) for x in range(200))) is False


def test_truncation(tmp_path):
    big = b"BT (" + (b"anxiety depression study " * 2000) + b") Tj ET"
    pdf = b"%PDF-1.4\n1 0 obj<</Length 9>>\nstream\n" + big + b"\nendstream\nendobj\n%%EOF"
    res = PX.extract_pdf_text(_write(tmp_path, pdf), max_chars=500)
    assert res["ok"] is True
    assert "已截断" in res["text"]


# --- smart_excerpt 路由(@file 与自动检测都走它)---------------------------

def test_smart_excerpt_routes_pdf_to_text(tmp_path):
    p = _write(tmp_path, _pdf_uncompressed(), name="paper.pdf")
    out = smart_excerpt(p)
    assert "<pdf" in out
    assert "methods section" in out
    assert "endstream" not in out          # 绝不泄露二进制


def test_smart_excerpt_pdf_failure_is_note_not_garbage(tmp_path):
    p = _write(tmp_path, b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF", name="scan.pdf")
    out = smart_excerpt(p)
    assert "抽取失败" in out
    assert "pypdf" in out or "扫描件" in out


def _write(tmp_path, data: bytes, name: str = "doc.pdf") -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p
