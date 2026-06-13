"""APA7 文档引擎 — 纯 stdlib 直写 OOXML(.docx)+ Markdown 双输出。

稳定性来自确定性:同一输入永远产出同一格式,没有"LLM 这次排版排歪了"。

APA7(学生论文版)规格,全部落实在 styles.xml:
- Times New Roman 12pt,全文双倍行距,正文首行缩进 0.5"
- 标题页:标题加粗居中(上空 3-4 行),作者/单位居中
- 三级标题:L1 居中加粗;L2 左对齐加粗;L3 左对齐加粗斜体
- 参考文献:悬挂缩进 0.5"
- 页码右上角(学生版无 running head;专业版可扩展)
- 中文混排:eastAsia 字体设宋体

用法:
    doc = APA7Document(title=..., authors=..., affiliation=...)
    doc.set_abstract(text, keywords=[...])
    doc.add_heading("方法", 1); doc.add_paragraph("...")
    doc.add_reference("Hamaker, E. L., ...")
    doc.to_markdown() / doc.to_docx("out.docx")

或从结构化 Markdown 解析:parse_md(text) -> APA7Document
(YAML 头 title/authors/affiliation/keywords;# Abstract 与 # References 为特殊节)
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape


# ---------------------------------------------------------------------------
# 文档模型
# ---------------------------------------------------------------------------

class APA7Document:
    def __init__(self, title: str = "Untitled", authors: str = "",
                 affiliation: str = "", course: str = "", date_str: str = "") -> None:
        self.title = title
        self.authors = authors
        self.affiliation = affiliation
        self.course = course
        self.date_str = date_str
        self.abstract: str = ""
        self.keywords: list = []
        self.blocks: list = []      # ("h1"|"h2"|"h3"|"p", text)
        self.references: list = []

    def set_abstract(self, text: str, keywords: list | None = None) -> None:
        self.abstract = text.strip()
        self.keywords = keywords or []

    def add_heading(self, text: str, level: int = 1) -> None:
        level = max(1, min(3, level))
        self.blocks.append((f"h{level}", text.strip()))

    def add_paragraph(self, text: str) -> None:
        if text.strip():
            self.blocks.append(("p", text.strip()))

    def add_reference(self, text: str) -> None:
        if text.strip():
            self.references.append(text.strip())

    # -- Markdown 输出 -------------------------------------------------------
    def to_markdown(self) -> str:
        out = ["---",
               f"title: {self.title}",
               f"authors: {self.authors}",
               f"affiliation: {self.affiliation}",
               f"keywords: {', '.join(self.keywords)}",
               "format: APA7",
               "---", "",
               f"# {self.title}", ""]
        if self.abstract:
            out += ["## Abstract", "", self.abstract, ""]
            if self.keywords:
                out += [f"*Keywords:* {', '.join(self.keywords)}", ""]
        for kind, text in self.blocks:
            if kind == "p":
                out += [text, ""]
            else:
                out += ["#" * (int(kind[1]) + 1) + " " + text, ""]
        if self.references:
            out += ["## References", ""]
            for r in sorted(self.references, key=str.lower):
                out += [r, ""]
        return "\n".join(out)

    # -- docx 输出 -----------------------------------------------------------
    def to_docx(self, path: str | Path) -> Path:
        path = Path(path)
        body: list = []
        # 标题页
        body.append(_p("", style="Normal"))
        body.append(_p("", style="Normal"))
        body.append(_p(self.title, style="PCTitle"))
        body.append(_p("", style="Normal"))
        if self.authors:
            body.append(_p(self.authors, style="PCCenter"))
        if self.affiliation:
            body.append(_p(self.affiliation, style="PCCenter"))
        if self.course:
            body.append(_p(self.course, style="PCCenter"))
        if self.date_str:
            body.append(_p(self.date_str, style="PCCenter"))
        body.append(_page_break())
        # 摘要页
        if self.abstract:
            body.append(_p("Abstract", style="PCH1"))
            body.append(_p(self.abstract, style="PCNoIndent"))
            if self.keywords:
                body.append(_p_keywords(", ".join(self.keywords)))
            body.append(_page_break())
        # 正文(APA7:正文第一页顶部重复标题,加粗居中)
        body.append(_p(self.title, style="PCH1"))
        for kind, text in self.blocks:
            style = {"h1": "PCH1", "h2": "PCH2", "h3": "PCH3", "p": "PCBody"}[kind]
            body.append(_p(text, style=style))
        # 参考文献
        if self.references:
            body.append(_page_break())
            body.append(_p("References", style="PCH1"))
            for r in sorted(self.references, key=str.lower):
                body.append(_p(r, style="PCRef"))

        document = _DOCUMENT_XML.format(body="".join(body))
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", _CONTENT_TYPES)
            z.writestr("_rels/.rels", _RELS)
            z.writestr("word/document.xml", document)
            z.writestr("word/styles.xml", _STYLES_XML)
            z.writestr("word/header1.xml", _HEADER_XML)
            z.writestr("word/_rels/document.xml.rels", _DOC_RELS)
            z.writestr("docProps/core.xml", _CORE_XML.format(title=escape(self.title)))
        return path


# ---------------------------------------------------------------------------
# 结构化 Markdown → 文档
# ---------------------------------------------------------------------------

def parse_md(text: str) -> APA7Document:
    meta: dict = {}
    body = text
    if text.lstrip().startswith("---"):
        stripped = text.lstrip()
        end = stripped.find("---", 3)
        if end != -1:
            for line in stripped[3:end].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip().lower()] = v.strip()
            body = stripped[end + 3:]

    doc = APA7Document(
        title=meta.get("title", "Untitled"),
        authors=meta.get("authors", meta.get("author", "")),
        affiliation=meta.get("affiliation", ""),
        course=meta.get("course", ""),
        date_str=meta.get("date", ""),
    )
    keywords = [k.strip() for k in meta.get("keywords", "").split(",") if k.strip()]

    section = "body"
    para_buf: list = []

    def flush() -> None:
        if para_buf:
            joined = " ".join(para_buf).strip()
            if section == "abstract":
                doc.set_abstract(joined, keywords)
            elif section == "body":
                doc.add_paragraph(joined)
            para_buf.clear()

    for line in body.splitlines():
        s = line.strip()
        if s.startswith("#"):
            flush()
            level = len(s) - len(s.lstrip("#"))
            heading = s.lstrip("#").strip()
            low = heading.lower()
            if low in ("abstract", "摘要"):
                section = "abstract"
            elif low in ("references", "参考文献"):
                section = "references"
            else:
                if section in ("abstract",):
                    section = "body"
                if section == "body" and low != doc.title.lower():
                    # 输入约定:# = APA 一级,## = 二级,### = 三级
                    doc.add_heading(heading, level)
        elif not s:
            flush()
        elif section == "references":
            doc.add_reference(s.lstrip("- ").strip())
        else:
            para_buf.append(s)
    flush()
    return doc


def export_cli(argv: list) -> int:
    """psyclaw export draft.md [--docx out.docx] [--md out.md]"""
    if not argv:
        print("用法:psyclaw export <draft.md> [--docx out.docx] [--md out.md]")
        print("  draft.md 格式:YAML 头(title/authors/affiliation/keywords)+")
        print("  # Abstract / # 标题(#=一级,##=二级)/ # References(每行一条)")
        return 1
    src = Path(argv[0])
    if not src.exists():
        print(f"文件不存在:{src}")
        return 1
    doc = parse_md(src.read_text(encoding="utf-8"))
    docx_out = Path(argv[argv.index("--docx") + 1]) if "--docx" in argv \
        else src.with_suffix(".apa7.docx")
    md_out = Path(argv[argv.index("--md") + 1]) if "--md" in argv \
        else src.with_suffix(".apa7.md")
    doc.to_docx(docx_out)
    md_out.write_text(doc.to_markdown(), encoding="utf-8")
    print(f"APA7 输出完成(确定性模板,格式稳定):")
    print(f"  Word    : {docx_out}")
    print(f"  Markdown: {md_out}")
    print(f"  规格:TNR 12pt·双倍行距·三级标题·参考文献悬挂缩进·页码右上")
    return 0


# ---------------------------------------------------------------------------
# OOXML 构件
# ---------------------------------------------------------------------------

def _p(text: str, style: str = "PCBody") -> str:
    runs = f'<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r>' if text else ""
    return f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>{runs}</w:p>'


def _p_keywords(kw: str) -> str:
    return ('<w:p><w:pPr><w:pStyle w:val="PCBody"/></w:pPr>'
            '<w:r><w:rPr><w:i/></w:rPr><w:t xml:space="preserve">Keywords: </w:t></w:r>'
            f'<w:r><w:t xml:space="preserve">{escape(kw)}</w:t></w:r></w:p>')


def _page_break() -> str:
    return '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'


_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""

_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rIdH1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>
<Relationship Id="rIdS1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

_CORE_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:title>{title}</dc:title><dc:creator>PsyClaw APA7 Engine</dc:creator>
</cp:coreProperties>"""

_HEADER_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:p><w:pPr><w:jc w:val="right"/></w:pPr>
<w:r><w:fldChar w:fldCharType="begin"/></w:r>
<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>
<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>
</w:hdr>"""

# 双倍行距 line=480;首行缩进 720 twip = 0.5"
_STYLES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr>
<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="SimSun"/>
<w:sz w:val="24"/><w:szCs w:val="24"/>
</w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:line="480" w:lineRule="auto" w:after="0"/></w:pPr></w:pPrDefault>
</w:docDefaults>
<w:style w:type="paragraph" w:styleId="Normal" w:default="1"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="PCBody"><w:name w:val="PC Body"/><w:basedOn w:val="Normal"/>
<w:pPr><w:ind w:firstLine="720"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="PCNoIndent"><w:name w:val="PC NoIndent"/><w:basedOn w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="PCTitle"><w:name w:val="PC Title"/><w:basedOn w:val="Normal"/>
<w:pPr><w:jc w:val="center"/></w:pPr><w:rPr><w:b/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="PCCenter"><w:name w:val="PC Center"/><w:basedOn w:val="Normal"/>
<w:pPr><w:jc w:val="center"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="PCH1"><w:name w:val="PC Heading 1"/><w:basedOn w:val="Normal"/>
<w:pPr><w:jc w:val="center"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="PCH2"><w:name w:val="PC Heading 2"/><w:basedOn w:val="Normal"/>
<w:pPr><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="PCH3"><w:name w:val="PC Heading 3"/><w:basedOn w:val="Normal"/>
<w:pPr><w:outlineLvl w:val="2"/></w:pPr><w:rPr><w:b/><w:i/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="PCRef"><w:name w:val="PC Reference"/><w:basedOn w:val="Normal"/>
<w:pPr><w:ind w:left="720" w:hanging="720"/></w:pPr></w:style>
</w:styles>"""

_DOCUMENT_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<w:body>{body}
<w:sectPr>
<w:headerReference w:type="default" r:id="rIdH1"/>
<w:pgSz w:w="12240" w:h="15840"/>
<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720"/>
</w:sectPr>
</w:body></w:document>"""
