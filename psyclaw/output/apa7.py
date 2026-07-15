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

import os
import re
import struct
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape


# ---------------------------------------------------------------------------
# W-2: APA7 统计结果格式化
# ---------------------------------------------------------------------------

def format_apa_stat_md(text: str) -> str:
    """对 APA7 统计结果字符串应用 Markdown 斜体格式（符合 APA7 §6.42 斜体规则）。

    处理：t/F/r 前置 (；p/d/dz/V 前置 =/< ；M/SD 前置 =；η²/ω²/Cohen's d 等。
    """
    # stat(df) 模式
    text = re.sub(r'\bt\(', '*t*(', text)
    text = re.sub(r'\bF\(', '*F*(', text)
    text = re.sub(r'\br\(', '*r*(', text)
    text = re.sub(r'\bz\(', '*z*(', text)
    text = re.sub(r'χ²\(', '*χ*²(', text)
    # p/stat 前置 = < >
    text = re.sub(r'\bp\s*(=|<|>)\s*', lambda m: f'*p* {m.group(1)} ', text)
    # 效应量符号
    text = re.sub(r"Cohen's\s+(d[z]?)\b", lambda m: f"Cohen's *{m.group(1)}*", text)
    text = re.sub(r'\brank-biserial\s+r\b', 'rank-biserial *r*', text)
    text = re.sub(r"Cramér's\s+V\b", "Cramér's *V*", text)
    text = re.sub(r'\bη²\b', '*η*²', text)
    text = re.sub(r'\bω²\b', '*ω*²', text)
    text = re.sub(r'\bR²\b', '*R*²', text)
    # M= / SD=
    text = re.sub(r'\bM\s*=', '*M* =', text)
    text = re.sub(r'\bSD\s*=', '*SD* =', text)
    # 移除多余空格
    text = re.sub(r'  +', ' ', text)
    return text


def format_apa_p(p: float) -> str:
    """APA7 p 值格式：p < .001；不保留前导零；三位小数。"""
    if p != p:
        return "*p* = NA"
    return "*p* < .001" if p < 0.001 else f"*p* = {p:.3f}".replace("0.", ".")


def format_apa_stat(value: float, n_dec: int = 2) -> str:
    """APA7 数值格式：两位小数；|v|<1 时去除前导零（.34 非 0.34）。"""
    if value != value:
        return "NA"
    formatted = f"{value:.{n_dec}f}"
    if abs(value) < 1:
        formatted = formatted.lstrip("0") if value >= 0 else "-" + formatted[2:]
        if not formatted or formatted in (".", "-."):
            formatted = ".00"
    return formatted


def _split_for_italic(text: str) -> list[tuple[str, bool]]:
    """将 APA 统计字符串分拆为 (片段, 是否斜体) 列表，供 docx run 生成使用。

    把 *...* 标记内的文本设为斜体。
    """
    parts: list[tuple[str, bool]] = []
    pattern = re.compile(r'\*([^*]+)\*')
    last = 0
    for m in pattern.finditer(text):
        if m.start() > last:
            parts.append((text[last:m.start()], False))
        parts.append((m.group(1), True))
        last = m.end()
    if last < len(text):
        parts.append((text[last:], False))
    return parts or [(text, False)]


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

    def add_stat_table(self, caption: str, headers: list[str],
                       rows: list[list[str]]) -> None:
        """添加 APA7 三线统计表格（用于相关矩阵、ANOVA 表等）。"""
        self.blocks.append(("table", (caption, headers, rows)))

    def add_figure(self, path: str, caption: str = "") -> None:
        """添加图片(feat-137)。Markdown 里的 ![caption](path) 解析成此。

        docx 导出时真嵌入 PNG(居中 + APA 图注);文件不存在则退化为文字占位,
        绝不静默丢图(此前 parse_md 完全忽略图片语法,图注留下、图丢了)。
        """
        self.blocks.append(("figure", (str(path), caption.strip())))

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
        for kind, content in self.blocks:
            if kind == "p":
                out += [content, ""]
            elif kind == "table":
                caption, headers, rows = content
                if caption:
                    out += [caption, ""]
                sep = "|".join(["---"] * len(headers))
                out += ["| " + " | ".join(headers) + " |",
                        "| " + sep + " |"]
                for row in rows:
                    out += ["| " + " | ".join(str(v) for v in row) + " |"]
                out += [""]
            elif kind == "figure":
                fpath, caption = content
                out += [f"![{caption}]({fpath})", ""]
            else:
                out += ["#" * (int(kind[1]) + 1) + " " + content, ""]
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
        media: list = []          # feat-137:待打包的图片 [(rid, arcname, bytes)]
        extra_rels: list = []     # 图片关系条目
        for kind, content in self.blocks:
            if kind == "table":
                caption, headers, rows = content
                body.append(_table_three_line(headers, rows, caption=caption))
            elif kind == "p":
                body.append(_p_stat(content, style="PCBody"))
            elif kind == "figure":
                fpath, caption = content
                xml = self._figure_xml(fpath, caption, media, extra_rels)
                body.append(xml)
            else:
                style = {"h1": "PCH1", "h2": "PCH2", "h3": "PCH3"}[kind]
                body.append(_p(content, style=style))
        # 参考文献
        if self.references:
            body.append(_page_break())
            body.append(_p("References", style="PCH1"))
            for r in sorted(self.references, key=str.lower):
                body.append(_p(r, style="PCRef"))

        document = _DOCUMENT_XML.format(body="".join(body))
        doc_rels = _DOC_RELS.replace("</Relationships>",
                                     "".join(extra_rels) + "</Relationships>")
        content_types = _CONTENT_TYPES
        if media and "image/png" not in content_types:
            content_types = content_types.replace(
                "</Types>",
                '<Default Extension="png" ContentType="image/png"/></Types>')
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", content_types)
            z.writestr("_rels/.rels", _RELS)
            z.writestr("word/document.xml", document)
            z.writestr("word/styles.xml", _STYLES_XML)
            z.writestr("word/header1.xml", _HEADER_XML)
            z.writestr("word/_rels/document.xml.rels", doc_rels)
            z.writestr("docProps/core.xml", _CORE_XML.format(title=escape(self.title)))
            for _rid, arc, data in media:
                z.writestr(arc, data)
        return path

    def _figure_xml(self, fpath: str, caption: str, media: list,
                    extra_rels: list) -> str:
        """图片 block → 居中 drawing + APA 图注;图不存在则文字占位(不静默丢)。"""
        import os as _os
        if not fpath or not _os.path.isfile(fpath):
            note = f"[图片未找到:{fpath}]" + (f" {caption}" if caption else "")
            return _p(note, style="PCNoIndent")
        try:
            data = open(fpath, "rb").read()
            w_emu, h_emu = _png_size_emu(data)
        except Exception:  # noqa: BLE001
            return _p(f"[图片读取失败:{fpath}]", style="PCNoIndent")
        idx = len(media) + 1
        rid = f"rIdImg{idx}"
        arc = f"word/media/image{idx}.png"
        media.append((rid, arc, data))
        extra_rels.append(
            f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/'
            f'officeDocument/2006/relationships/image" Target="media/image{idx}.png"/>')
        parts = [_drawing_xml(rid, w_emu, h_emu, idx)]
        if caption:                                  # APA 图注在图下方
            parts.append(_p(caption, style="PCNoIndent"))
        return "".join(parts)


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
            m = _IMG_RE.match(s)               # feat-137:![图注](路径) → 嵌图
            if m:
                flush()
                base = getattr(parse_md, "_base_dir", None)
                path = m.group(2).strip()
                if base and not os.path.isabs(path):
                    path = os.path.join(base, path)
                doc.add_figure(path, m.group(1).strip())
            else:
                para_buf.append(s)
    flush()
    return doc


_IMG_RE = re.compile(r"^!\[(.*?)\]\(([^)]+)\)\s*$")


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
    parse_md._base_dir = str(src.resolve().parent)   # feat-137:相对图片路径基于 md 目录
    doc = parse_md(src.read_text(encoding="utf-8"))
    parse_md._base_dir = None
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

def _run(text: str, italic: bool = False) -> str:
    rpr = "<w:rPr><w:i/><w:iCs/></w:rPr>" if italic else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def _p(text: str, style: str = "PCBody") -> str:
    runs = f'<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r>' if text else ""
    return f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>{runs}</w:p>'


def _p_stat(text: str, style: str = "PCBody") -> str:
    """段落，自动对 *...* 标记的片段应用斜体 run。"""
    parts = _split_for_italic(text)
    runs = "".join(_run(t, italic=it) for t, it in parts)
    return f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>{runs}</w:p>'


def _table_three_line(headers: list[str], rows: list[list[str]],
                      caption: str = "") -> str:
    """生成 APA7 三线表 OOXML（顶线加粗、表头下细线、底线加粗、无竖线）。

    headers: 列标题列表
    rows: 数据行列表，每行是字符串列表（与 headers 等长）
    caption: 表注（如 "Table 1\\n注变量间相关矩阵"）
    """
    THICK = "24"
    THIN = "12"

    def _border(name: str, size: str) -> str:
        return (f'<w:top w:val="single" w:sz="{size}" w:space="0" w:color="000000"/>'
                if name == "top"
                else f'<w:bottom w:val="single" w:sz="{size}" w:space="0" w:color="000000"/>')

    def _cell(txt: str, bold: bool = False, top_border: str = "",
              bot_border: str = "") -> str:
        borders = ""
        if top_border or bot_border:
            parts_b = []
            if top_border:
                parts_b.append(f'<w:top w:val="single" w:sz="{top_border}" '
                                'w:space="0" w:color="000000"/>')
            if bot_border:
                parts_b.append(f'<w:bottom w:val="single" w:sz="{bot_border}" '
                                'w:space="0" w:color="000000"/>')
            # suppress left/right/insideH borders
            parts_b.append('<w:left w:val="none" w:sz="0" w:space="0" w:color="auto"/>')
            parts_b.append('<w:right w:val="none" w:sz="0" w:space="0" w:color="auto"/>')
            borders = f'<w:tcBorders>{"".join(parts_b)}</w:tcBorders>'
        rpr = "<w:rPr><w:b/></w:rPr>" if bold else ""
        run = f'<w:r>{rpr}<w:t xml:space="preserve">{escape(str(txt))}</w:t></w:r>'
        return (f'<w:tc><w:tcPr>{borders}</w:tcPr>'
                f'<w:p><w:pPr><w:pStyle w:val="PCNoIndent"/></w:pPr>{run}</w:p></w:tc>')

    parts: list[str] = []
    if caption:
        parts.append(_p(caption, style="PCNoIndent"))

    # 表头行 (top=thick, bottom=thin)
    header_cells = "".join(
        _cell(h, bold=True, top_border=THICK, bot_border=THIN) for h in headers)
    parts.append(f'<w:tr>{header_cells}</w:tr>')

    # 数据行 (最后一行 bottom=thick)
    for i, row in enumerate(rows):
        is_last = (i == len(rows) - 1)
        bot = THICK if is_last else ""
        data_cells = "".join(_cell(str(v), bot_border=bot) for v in row)
        parts.append(f'<w:tr>{data_cells}</w:tr>')

    table_content = "".join(parts[1:]) if caption else "".join(parts)
    table_xml = f'<w:tbl><w:tblPr><w:tblStyle w:val="TableNormal"/><w:tblW w:w="0" w:type="auto"/></w:tblPr>{table_content}</w:tbl>'
    return (parts[0] if caption else "") + table_xml


def _p_keywords(kw: str) -> str:
    return ('<w:p><w:pPr><w:pStyle w:val="PCBody"/></w:pPr>'
            '<w:r><w:rPr><w:i/></w:rPr><w:t xml:space="preserve">Keywords: </w:t></w:r>'
            f'<w:r><w:t xml:space="preserve">{escape(kw)}</w:t></w:r></w:p>')


def _page_break() -> str:
    return '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'


# feat-137:图片嵌入(纯 stdlib OOXML DrawingML)。宽度上限 6",按 PNG 原比例缩放。
_MAX_W_EMU = 6 * 914400          # 6 英寸(EMU:914400/inch),APA 正文宽度上限
_DEFAULT_DPI = 96


def _png_size_emu(data: bytes) -> tuple[int, int]:
    """从 PNG 头读像素宽高 → EMU(按 96 dpi;超 6" 等比缩小)。非 PNG 回退默认。"""
    w = h = 0
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        w, h = struct.unpack(">II", data[16:24])
    if not w or not h:
        w, h = 480, 360
    w_emu = int(w / _DEFAULT_DPI * 914400)
    h_emu = int(h / _DEFAULT_DPI * 914400)
    if w_emu > _MAX_W_EMU:
        h_emu = int(h_emu * _MAX_W_EMU / w_emu)
        w_emu = _MAX_W_EMU
    return w_emu, h_emu


def _drawing_xml(rid: str, w_emu: int, h_emu: int, idx: int) -> str:
    """居中的内联图片段落(DrawingML)。"""
    return (
        '<w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:drawing>'
        f'<wp:inline distT="0" distB="0" distL="0" distR="0" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
        f'<wp:extent cx="{w_emu}" cy="{h_emu}"/>'
        '<wp:effectExtent l="0" t="0" r="0" b="0"/>'
        f'<wp:docPr id="{idx}" name="Figure{idx}"/>'
        '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        f'<pic:nvPicPr><pic:cNvPr id="{idx}" name="Figure{idx}"/><pic:cNvPicPr/></pic:nvPicPr>'
        f'<pic:blipFill><a:blip r:embed="{rid}" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/>'
        '<a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        '<pic:spPr><a:xfrm><a:off x="0" y="0"/>'
        f'<a:ext cx="{w_emu}" cy="{h_emu}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
        '</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>')


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
