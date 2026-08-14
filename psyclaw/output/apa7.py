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
import unicodedata
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


# feat-143:行内 Markdown 强调解析。用户按 Markdown 习惯写稿(**粗体**/`代码`),
# 此前 **粗体** 会被上面 `\*([^*]+)\*` 的单星规则错吃成「* + 斜体 + *」——
# 星号漏进 Word 且语义错;Abstract/References 更是完全不解析、原样漏字面量。
# `**` 必须排在 `*` 之前(alternation 按序尝试),否则双星仍被单星规则抢走。
# 不处理嵌套(**粗*斜*体**)与转义(\*),APA 稿件罕见,YAGNI。
_INLINE_RE = re.compile(r'\*\*(.+?)\*\*|\*([^*]+)\*|`([^`]+)`')


def _split_inline(text: str) -> list[tuple[str, bool, bool, bool]]:
    """把行内标记拆成 (片段, 粗体, 斜体, 等宽) 列表,供 docx run 生成。

    纯函数。`_split_for_italic` 的超集,但契约不同(四元组),故另立函数——
    既有调用方与测试锁定了旧签名,不动它。
    """
    parts: list[tuple[str, bool, bool, bool]] = []
    last = 0
    for m in _INLINE_RE.finditer(text):
        if m.start() > last:
            parts.append((text[last:m.start()], False, False, False))
        bold, italic, code = m.group(1), m.group(2), m.group(3)
        if bold is not None:
            parts.append((bold, True, False, False))
        elif italic is not None:
            parts.append((italic, False, True, False))
        else:
            parts.append((code, False, False, True))
        last = m.end()
    if last < len(text):
        parts.append((text[last:], False, False, False))
    return parts or [(text, False, False, False)]


def _latex_escape(text: str) -> str:
    """Escape Markdown text for LaTeX while preserving Unicode prose."""
    out = str(text)
    for char, replacement in (("\\", r"\textbackslash{}"), ("&", r"\&"),
                              ("%", r"\%"), ("$", r"\$"), ("#", r"\#"),
                              ("_", r"\_"), ("{", r"\{"), ("}", r"\}"),
                              ("~", r"\textasciitilde{}"), ("^", r"\textasciicircum{}")):
        out = out.replace(char, replacement)
    return out


def _latex_inline(text: str) -> str:
    """Convert the small inline Markdown subset used by APA7Document."""
    tokens: list[str] = []

    def stash(value: str) -> str:
        tokens.append(value)
        return f"\x00{len(tokens) - 1}\x00"

    value = re.sub(r"!\[([^]]*)\]\(([^)]+)\)",
                   lambda m: stash(rf"\href{{{_latex_path(m.group(2))}}}{{{_latex_escape(m.group(1))}}}"),
                   str(text))
    value = re.sub(r"\[([^]]+)\]\(([^)]+)\)",
                   lambda m: stash(rf"\href{{{_latex_path(m.group(2))}}}{{{_latex_escape(m.group(1))}}}"),
                   value)
    value = re.sub(r"\*\*(.+?)\*\*", lambda m: stash(rf"\textbf{{{_latex_escape(m.group(1))}}}"), value)
    value = re.sub(r"\*([^*]+)\*", lambda m: stash(rf"\textit{{{_latex_escape(m.group(1))}}}"), value)
    value = re.sub(r"`([^`]+)`", lambda m: stash(rf"\texttt{{{_latex_escape(m.group(1))}}}"), value)
    value = _latex_escape(value)
    for i, token in enumerate(tokens):
        value = value.replace(_latex_escape(f"\x00{i}\x00"), token)
    return value


def _latex_path(path: str) -> str:
    return str(path).replace("\\", "/").replace(" ", r"\ ")


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
        self.footnotes: list[str] = []

    def set_abstract(self, text: str, keywords: list | None = None) -> None:
        self.abstract = text.strip()
        self.keywords = keywords or []

    def add_heading(self, text: str, level: int = 1) -> None:
        level = max(1, min(3, level))
        self.blocks.append((f"h{level}", text.strip()))

    def add_paragraph(self, text: str) -> None:
        if text.strip():
            self.blocks.append(("p", text.strip()))

    def add_paragraph_with_footnote(self, text: str, note: str) -> None:
        """Add a paragraph with a real Word footnote reference."""
        if text.strip() and note.strip():
            self.footnotes.append(note.strip())
            self.blocks.append(("pfn", (text.strip(), len(self.footnotes))))

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

    def to_latex(self, path: str | Path) -> Path:
        """Write a UTF-8 XeLaTeX manuscript from the same APA7 document model."""
        path = Path(path)
        lines = [
            r"\documentclass[12pt]{article}",
            r"\usepackage{fontspec}",
            r"\usepackage{xeCJK}",
            r"\usepackage[margin=1in]{geometry}",
            r"\usepackage{setspace}",
            r"\usepackage{booktabs}",
            r"\usepackage{graphicx}",
            r"\usepackage{hyperref}",
            r"\setmainfont{Times New Roman}",
            r"\setCJKmainfont{SimSun}",
            r"\doublespacing",
            r"\begin{document}",
            r"\begin{titlepage}",
            r"\centering",
            rf"{{\Large\bfseries {_latex_inline(self.title)}\par}}",
            r"\vfill",
        ]
        for value in (self.authors, self.affiliation, self.course, self.date_str):
            if value:
                lines.append(rf"{_latex_inline(value)}\par")
        lines += [r"\end{titlepage}"]
        if self.abstract:
            lines += [r"\begin{abstract}", _latex_inline(self.abstract), r"\end{abstract}"]
            if self.keywords:
                lines.append(r"\noindent\textit{Keywords}: " +
                             "; ".join(_latex_inline(k) for k in self.keywords))
            lines.append(r"\clearpage")
        lines.append(rf"\begin{{center}}\textbf{{{_latex_inline(self.title)}}}\end{{center}}")
        for kind, content in self.blocks:
            if kind == "p":
                lines += [_latex_inline(content), ""]
            elif kind == "pfn":
                text, footnote_id = content
                note = self.footnotes[footnote_id - 1] if footnote_id <= len(self.footnotes) else ""
                lines += [_latex_inline(text) + rf"\footnote{{{_latex_inline(note)}}}", ""]
            elif kind in {"h1", "h2", "h3"}:
                command = {"h1": "section", "h2": "subsection", "h3": "subsubsection"}[kind]
                lines.append(rf"\{command}{{{_latex_inline(content)}}}")
            elif kind == "table":
                caption, headers, rows = content
                lines += [r"\begin{table}[htbp]", r"\centering"]
                if caption:
                    lines.append(rf"\caption{{{_latex_inline(caption)}}}")
                spec = "l" + "c" * max(0, len(headers) - 1)
                lines.append(rf"\begin{{tabular}}{{{spec}}}")
                lines.append(r"\toprule")
                lines.append(" & ".join(_latex_inline(str(v)) for v in headers) + r" \\")
                lines.append(r"\midrule")
                for row in rows:
                    lines.append(" & ".join(_latex_inline(str(v)) for v in row) + r" \\")
                lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}"]
            elif kind == "figure":
                fpath, caption = content
                lines += [r"\begin{figure}[htbp]", r"\centering",
                          rf"\includegraphics[width=0.8\textwidth]{{{_latex_path(fpath)}}}"]
                if caption:
                    lines.append(rf"\caption{{{_latex_inline(caption)}}}")
                lines.append(r"\end{figure}")
        if self.references:
            lines += [r"\clearpage", r"\section*{References}", r"\begin{hangparas}{0.5in}{1}"]
            lines.extend(_latex_inline(r) for r in sorted(self.references, key=str.lower))
            lines.append(r"\end{hangparas}")
        lines.append(r"\end{document}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

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
            body.append(_p_stat(self.abstract, style="PCNoIndent"))  # feat-143
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
            elif kind == "pfn":
                text, footnote_id = content
                body.append(_p_stat_with_footnote(text, footnote_id, style="PCBody"))
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
                body.append(_p_stat(r, style="PCRef"))   # feat-143:期刊名斜体

        document = _DOCUMENT_XML.format(body="".join(body))
        doc_rels = _DOC_RELS.replace("</Relationships>",
                                     "".join(extra_rels) + "</Relationships>")
        content_types = _CONTENT_TYPES
        if not self.footnotes:
            doc_rels = doc_rels.replace(
                '<Relationship Id="rIdF1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes" Target="footnotes.xml"/>',
                "")
        else:
            content_types = content_types.replace(
                "</Types>", '<Override PartName="/word/footnotes.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"/></Types>')
        if media and "image/png" not in content_types:
            content_types = content_types.replace(
                "</Types>",
                '<Default Extension="png" ContentType="image/png"/></Types>')
        # ZIP headers include the current clock by default, making an otherwise
        # identical document differ on every run.  Fixed metadata keeps the
        # exported artifact reproducible and makes byte-level regression useful.
        entries = [
            ("[Content_Types].xml", content_types),
            ("_rels/.rels", _RELS),
            ("word/document.xml", document),
            ("word/styles.xml", _STYLES_XML),
            ("word/header1.xml", _HEADER_XML),
            ("word/_rels/document.xml.rels", doc_rels),
            ("docProps/core.xml", _CORE_XML.format(title=escape(self.title))),
        ]
        if self.footnotes:
            entries.append(("word/footnotes.xml", _FOOTNOTES_XML.format(
                notes="".join(_footnote_xml(i, note) for i, note in enumerate(self.footnotes, 1)))))
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for name, payload in entries:
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 0
                info.external_attr = 0
                z.writestr(info, payload.encode("utf-8"))
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


_PAGE_WIDTH_DXA = 12240
_PAGE_MARGIN_DXA = 1440
_TABLE_WIDTH_DXA = _PAGE_WIDTH_DXA - (_PAGE_MARGIN_DXA * 2)
_MIN_TABLE_COL_DXA = 480


def export_cli(argv: list) -> int:
    """Export one manuscript as Word (default), LaTeX, and Markdown."""
    if not argv:
        print("用法:psyclaw export <draft.md> [--format docx|latex] [--docx out.docx] [--latex out.tex] [--md out.md]")
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
    format_name = argv[argv.index("--format") + 1].lower() if "--format" in argv else "docx"
    if format_name not in {"docx", "latex"}:
        print(f"不支持的输出格式:{format_name}(可选:docx|latex)")
        return 1
    docx_out = Path(argv[argv.index("--docx") + 1]) if "--docx" in argv \
        else src.with_suffix(".apa7.docx")
    latex_out = Path(argv[argv.index("--latex") + 1]) if "--latex" in argv \
        else src.with_suffix(".apa7.tex")
    md_out = Path(argv[argv.index("--md") + 1]) if "--md" in argv \
        else src.with_suffix(".apa7.md")
    if format_name == "latex":
        doc.to_latex(latex_out)
        print("LaTeX 输出完成(UTF-8 + XeLaTeX 模板):")
        print(f"  LaTeX  : {latex_out}")
        return 0
    doc.to_docx(docx_out)
    md_out.write_text(doc.to_markdown(), encoding="utf-8")
    # A file existing is not sufficient evidence of a usable delivery.  Keep
    # both artifacts for diagnosis, but never report a broken DOCX as complete.
    from psyclaw.output.docx_contract import inspect_docx
    contract = inspect_docx(docx_out)
    if not contract["ok"]:
        print("APA7 输出失败(DOCX 契约未通过；中间文件已保留):")
        for error in contract["errors"]:
            print(f"  - {error}")
        print(f"  Word    : {docx_out}")
        print(f"  Markdown: {md_out}")
        return 1
    print(f"APA7 输出完成(确定性模板,格式稳定):")
    print(f"  Word    : {docx_out}")
    print(f"  Markdown: {md_out}")
    print(f"  规格:TNR 12pt·双倍行距·三级标题·参考文献悬挂缩进·页码右上")
    return 0


# ---------------------------------------------------------------------------
# OOXML 构件
# ---------------------------------------------------------------------------

def _run(text: str, italic: bool = False, bold: bool = False,
         code: bool = False) -> str:
    """一个 run;feat-143 起支持粗体与等宽(行内代码)。"""
    props = ""
    if bold:
        props += "<w:b/><w:bCs/>"
    if italic:
        props += "<w:i/><w:iCs/>"
    if code:                       # 行内代码:等宽字体(不改字号,免破坏行距)
        props += ('<w:rFonts w:ascii="Courier New" w:hAnsi="Courier New" '
                  'w:cs="Courier New"/>')
    rpr = f"<w:rPr>{props}</w:rPr>" if props else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def _p(text: str, style: str = "PCBody") -> str:
    """段落,文本原样不解析行内标记(标题等已由样式承担强调的场合用)。"""
    runs = f'<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r>' if text else ""
    return f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>{runs}</w:p>'


def _p_stat(text: str, style: str = "PCBody") -> str:
    """段落,解析行内 Markdown 强调(**粗体** / *斜体* / `代码`)。

    feat-143:此前只走 _split_for_italic 认 *斜体*,**粗体** 被错吃成
    「* + 斜体 + *」;现统一走 _split_inline。
    """
    if not text:
        return f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr></w:p>'
    parts = _split_inline(text)
    runs = "".join(_run(t, italic=i, bold=b, code=c) for t, b, i, c in parts)
    return f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>{runs}</w:p>'


def _p_stat_with_footnote(text: str, footnote_id: int, style: str = "PCBody") -> str:
    runs = "".join(_run(t, italic=i, bold=b, code=c)
                    for t, b, i, c in _split_inline(text))
    runs += (f'<w:r><w:footnoteReference w:id="{int(footnote_id)}"/></w:r>')
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

    headers, rows = _normalize_table(headers, rows)
    widths = _table_column_widths(headers, rows)

    def _cell(txt: str, bold: bool = False, top_border: str = "",
              bot_border: str = "", width: int = _TABLE_WIDTH_DXA) -> str:
        border_parts = []
        if top_border:
            border_parts.append(f'<w:top w:val="single" w:sz="{top_border}" '
                                'w:space="0" w:color="000000"/>')
        if bot_border:
            border_parts.append(f'<w:bottom w:val="single" w:sz="{bot_border}" '
                                'w:space="0" w:color="000000"/>')
        border_parts.append('<w:left w:val="none" w:sz="0" w:space="0" w:color="auto"/>')
        border_parts.append('<w:right w:val="none" w:sz="0" w:space="0" w:color="auto"/>')
        borders = f'<w:tcBorders>{"".join(border_parts)}</w:tcBorders>'
        cell_pr = (
            f'<w:tcW w:w="{width}" w:type="dxa"/>'
            f'{borders}'
            '<w:tcMar>'
            '<w:top w:w="80" w:type="dxa"/>'
            '<w:left w:w="120" w:type="dxa"/>'
            '<w:bottom w:w="80" w:type="dxa"/>'
            '<w:right w:w="120" w:type="dxa"/>'
            '</w:tcMar>'
            '<w:vAlign w:val="center"/>'
        )
        rpr = "<w:rPr><w:b/></w:rPr>" if bold else ""
        run = f'<w:r>{rpr}<w:t xml:space="preserve">{escape(str(txt))}</w:t></w:r>'
        # Quick Look ignores tcBorders in some DOCX previews.  A paragraph
        # bottom border keeps the header rule visible there, while tcBorders
        # remains the canonical Word/LibreOffice table definition.
        para_border = (
            f'<w:pBdr><w:bottom w:val="single" w:sz="{bot_border}" '
            'w:space="0" w:color="000000"/></w:pBdr>'
            if bot_border and bold else ""
        )
        para_pr = ('<w:pPr><w:pStyle w:val="PCNoIndent"/>'
                   f'{para_border}'
                   '<w:spacing w:line="240" w:lineRule="auto" w:after="0"/>'
                   '</w:pPr>')
        return f'<w:tc><w:tcPr>{cell_pr}</w:tcPr><w:p>{para_pr}{run}</w:p></w:tc>'

    parts: list[str] = []
    if caption:
        parts.extend(_p(line, style="PCNoIndent")
                     for line in str(caption).splitlines() if line.strip())

    # 表头行 (top=thick, bottom=thin)
    header_cells = "".join(
        _cell(h, bold=True, top_border=THICK, bot_border=THICK if not rows else THIN,
              width=widths[i])
        for i, h in enumerate(headers))
    table_rows = [f'<w:tr><w:trPr><w:cantSplit/><w:tblHeader/></w:trPr>{header_cells}</w:tr>']

    # 数据行 (最后一行 bottom=thick)
    for i, row in enumerate(rows):
        is_last = (i == len(rows) - 1)
        bot = THICK if is_last else ""
        data_cells = "".join(
            _cell(str(v), bot_border=bot, width=widths[j])
            for j, v in enumerate(row))
        table_rows.append(f'<w:tr><w:trPr><w:cantSplit/></w:trPr>{data_cells}</w:tr>')

    grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)
    table_pr = (
        '<w:tblPr>'
        '<w:tblStyle w:val="TableNormal"/>'
        f'<w:tblW w:w="{_TABLE_WIDTH_DXA}" w:type="dxa"/>'
        '<w:tblInd w:w="0" w:type="dxa"/>'
        '<w:tblBorders>'
        f'<w:top w:val="single" w:sz="{THICK}" w:space="0" w:color="000000"/>'
        f'<w:bottom w:val="single" w:sz="{THICK}" w:space="0" w:color="000000"/>'
        '<w:left w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
        '<w:right w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
        '<w:insideH w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
        '<w:insideV w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
        '</w:tblBorders>'
        '<w:tblLayout w:type="fixed"/>'
        '<w:tblCellMar>'
        '<w:top w:w="80" w:type="dxa"/>'
        '<w:left w:w="120" w:type="dxa"/>'
        '<w:bottom w:w="80" w:type="dxa"/>'
        '<w:right w:w="120" w:type="dxa"/>'
        '</w:tblCellMar>'
        '</w:tblPr>'
    )
    table_xml = f'<w:tbl>{table_pr}<w:tblGrid>{grid}</w:tblGrid>{"".join(table_rows)}</w:tbl>'
    return "".join(parts) + table_xml


def _normalize_table(headers: list[str], rows: list[list[str]]) -> tuple[list[str], list[list[str]]]:
    """让 OOXML 表格始终有稳定列数；不足补空，超出截断。"""
    col_count = len(headers)
    if col_count <= 0:
        col_count = max((len(row) for row in rows), default=1)
        headers = [f"Column {i + 1}" for i in range(col_count)]
    normalized_headers = [str(h) for h in headers[:col_count]]
    normalized_rows = []
    for row in rows:
        cells = [str(v) for v in row[:col_count]]
        cells.extend([""] * (col_count - len(cells)))
        normalized_rows.append(cells)
    return normalized_headers, normalized_rows


def _table_column_widths(headers: list[str], rows: list[list[str]],
                         total_width: int = _TABLE_WIDTH_DXA) -> list[int]:
    """按内容估算列宽，同时保证总宽精确等于正文宽度。

    Word/LibreOffice/Google Docs 对 auto 表格的重排差异很大；这里固定 DXA
    宽度、tblGrid 和 tcW，遵循 docx skill 的表格规则。
    """
    col_count = max(1, len(headers))
    if col_count * _MIN_TABLE_COL_DXA >= total_width:
        base = total_width // col_count
        widths = [base] * col_count
        widths[-1] += total_width - sum(widths)
        return widths

    weights: list[int] = []
    for idx in range(col_count):
        samples = [headers[idx]] + [row[idx] for row in rows if idx < len(row)]
        longest = max((_visual_width(v) for v in samples), default=1)
        weights.append(max(6, min(36, longest)))

    min_total = _MIN_TABLE_COL_DXA * col_count
    flex_total = total_width - min_total
    weight_total = sum(weights) or col_count
    widths = [
        _MIN_TABLE_COL_DXA + int(flex_total * weight / weight_total)
        for weight in weights
    ]
    widths[-1] += total_width - sum(widths)
    return widths


def _visual_width(text: object) -> int:
    width = 0
    for ch in str(text):
        width += 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1
    return width or 1


def _p_keywords(kw: str) -> str:
    return ('<w:p><w:pPr><w:pStyle w:val="PCBody"/></w:pPr>'
            '<w:r><w:rPr><w:i/></w:rPr><w:t xml:space="preserve">Keywords: </w:t></w:r>'
            f'<w:r><w:t xml:space="preserve">{escape(kw)}</w:t></w:r></w:p>')


def _page_break() -> str:
    # Paragraph-level pagination is rendered consistently by Word,
    # LibreOffice and macOS Quick Look; an inline page-break run appears as a
    # missing-glyph square in Quick Look thumbnails.
    return '<w:p><w:pPr><w:pageBreakBefore/></w:pPr></w:p>'


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
<Relationship Id="rIdF1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes" Target="footnotes.xml"/>
</Relationships>"""


_FOOTNOTES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:footnote w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>
<w:footnote w:id="0"><w:p><w:r><w:continuationSeparator/></w:r></w:p></w:footnote>
{notes}</w:footnotes>"""


def _footnote_xml(footnote_id: int, text: str) -> str:
    return (f'<w:footnote w:id="{int(footnote_id)}"><w:p>'
            f'<w:r><w:footnoteRef/></w:r><w:r><w:t xml:space="preserve">'
            f'{escape(text)}</w:t></w:r></w:p></w:footnote>')

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
