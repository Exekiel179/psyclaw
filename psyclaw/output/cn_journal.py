"""中文心理学期刊格式模块 (W-3).

支持《心理学报》/ 《心理科学》/ APA7 三种格式切换，以及中英双语文档模板。

主要功能:
    - JOURNALS: 期刊格式规格字典
    - format_bilingual_abstract(): 生成中英双语摘要 Markdown
    - format_cn_reference(): GB/T 7714-2015 期刊参考文献格式
    - convert_apa_ref_to_cn(): APA7 单条参考文献转 GB/T 7714 格式（启发式）
    - CnJournalDocument: 继承 APA7Document，添加双语字段 + 中文格式切换
    - cn_journal_cli(): CLI 入口
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

from psyclaw.output.apa7 import APA7Document, format_apa_stat_md


# ---------------------------------------------------------------------------
# 期刊格式规格表
# ---------------------------------------------------------------------------

JOURNALS: dict[str, dict[str, Any]] = {
    "apa7": {
        "label": "APA 7th Edition",
        "lang": "en",
        "citation_style": "apa",
        "abstract_lang": ["en"],
        "keyword_sep": "; ",
        "ref_header": "References",
        "abstract_header_en": "Abstract",
        "section_labels": {
            "introduction": "Introduction",
            "method": "Method",
            "results": "Results",
            "discussion": "Discussion",
            "conclusion": "Conclusion",
        },
    },
    "xinlixuebao": {
        "label": "心理学报 (Acta Psychologica Sinica)",
        "lang": "zh",
        "citation_style": "gbt7714",
        "abstract_lang": ["zh", "en"],
        "keyword_sep": "；",
        "ref_header": "参考文献",
        "abstract_header_zh": "摘  要",
        "abstract_header_en": "Abstract",
        "keyword_header_zh": "关键词",
        "keyword_header_en": "Key words",
        "abstract_len_zh": 400,
        "abstract_len_en": 250,
        "section_labels": {
            "introduction": "引  言",
            "method": "研究方法",
            "results": "结  果",
            "discussion": "讨  论",
            "conclusion": "结  论",
        },
        "notes": "参考文献格式: 作者. 标题[J]. 心理学报, 年, 卷(期): 页-页. DOI",
    },
    "xinlikexue": {
        "label": "心理科学 (Psychological Science, China)",
        "lang": "zh",
        "citation_style": "gbt7714",
        "abstract_lang": ["zh", "en"],
        "keyword_sep": "；",
        "ref_header": "参考文献",
        "abstract_header_zh": "摘  要",
        "abstract_header_en": "Abstract",
        "keyword_header_zh": "关键词",
        "keyword_header_en": "Key words",
        "abstract_len_zh": 300,
        "abstract_len_en": 200,
        "section_labels": {
            "introduction": "引  言",
            "method": "方  法",
            "results": "结  果",
            "discussion": "讨  论",
            "conclusion": "结  论",
        },
        "notes": "参考文献格式: 作者. 标题[J]. 心理科学, 年, 卷(期): 页-页.",
    },
}

# 中文 section 标题模式（用于格式转换）
_CN_SECTION_ALIASES: dict[str, list[str]] = {
    "introduction": ["引言", "引  言", "前言", "Introduction"],
    "method": ["方法", "研究方法", "方  法", "Method", "Methods"],
    "results": ["结果", "结  果", "Results"],
    "discussion": ["讨论", "讨  论", "Discussion"],
    "conclusion": ["结论", "结  论", "Conclusion", "Conclusions"],
}


def list_journals() -> dict[str, str]:
    """返回可用期刊 id → label 的映射。"""
    return {jid: spec["label"] for jid, spec in JOURNALS.items()}


def get_journal_spec(journal_id: str) -> dict[str, Any]:
    """获取期刊格式规格，未知 id 返回 apa7。"""
    return JOURNALS.get(journal_id.lower(), JOURNALS["apa7"])


# ---------------------------------------------------------------------------
# 双语摘要格式化
# ---------------------------------------------------------------------------

def format_bilingual_abstract(
    cn_abstract: str,
    en_abstract: str,
    cn_keywords: list[str] | None = None,
    en_keywords: list[str] | None = None,
    journal: str = "xinlixuebao",
) -> str:
    """生成中英双语摘要 Markdown 块。

    中文摘要在前，英文摘要在后（符合国内期刊惯例）。
    """
    spec = get_journal_spec(journal)
    kw_sep = spec.get("keyword_sep", "；")
    zh_hdr = spec.get("abstract_header_zh", "摘  要")
    en_hdr = spec.get("abstract_header_en", "Abstract")
    zh_kw_hdr = spec.get("keyword_header_zh", "关键词")
    en_kw_hdr = spec.get("keyword_header_en", "Key words")

    out: list[str] = []

    if cn_abstract:
        out.append(f"## {zh_hdr}")
        out.append("")
        out.append(cn_abstract.strip())
        if cn_keywords:
            out.append("")
            out.append(f"**{zh_kw_hdr}：** {kw_sep.join(cn_keywords)}")
        out.append("")

    if en_abstract:
        out.append(f"## {en_hdr}")
        out.append("")
        out.append(en_abstract.strip())
        if en_keywords:
            out.append("")
            kw_en_sep = "; " if journal == "apa7" else "; "
            out.append(f"**{en_kw_hdr}:** {kw_en_sep.join(en_keywords)}")
        out.append("")

    return "\n".join(out)


# ---------------------------------------------------------------------------
# 参考文献格式化（GB/T 7714-2015 顺序编码制）
# ---------------------------------------------------------------------------

def format_cn_reference(
    authors: str,
    year: int | str,
    title: str,
    journal: str,
    volume: str = "",
    issue: str = "",
    pages: str = "",
    doi: str = "",
) -> str:
    """格式化单条 GB/T 7714-2015 期刊文献（顺序编码制）。

    格式: 作者. 标题[J]. 期刊名, 年, 卷(期): 页码. DOI
    """
    ref = f"{authors}. {title}[J]. {journal}"
    vol_str = str(volume) if volume else ""
    if issue:
        vol_str += f"({issue})"
    ref += f", {year}"
    if vol_str:
        ref += f", {vol_str}"
    if pages:
        ref += f": {pages}"
    ref += "."
    if doi:
        doi_url = doi if doi.startswith("http") else f"https://doi.org/{doi}"
        ref += f" {doi_url}"
    return ref


def convert_apa_ref_to_cn(apa_ref: str) -> str:
    """启发式地将 APA7 参考文献转为 GB/T 7714 期刊格式（浅转换）。

    仅处理典型期刊文章格式；无法识别的条目原样返回。
    """
    # 典型 APA 格式: Author, A. B. (Year). Title. Journal, volume(issue), pages. DOI
    m = re.match(
        r'^(.+?)\s*\((\d{4})\)\.\s*(.+?)\.\s*([A-Z].+?),\s*(\d+)(?:\((\d+)\))?,\s*([\d–-]+)\.',
        apa_ref.strip()
    )
    if not m:
        return apa_ref
    authors_raw, year, title, journal_name, vol, issue, pages = m.groups()
    # 简化作者（APA: Last, F. M. → GB/T: Last F M 等）
    doi_m = re.search(r'https?://doi\.org/(\S+)', apa_ref)
    doi = doi_m.group(1) if doi_m else ""
    return format_cn_reference(
        authors=authors_raw,
        year=year,
        title=title,
        journal=journal_name,
        volume=vol or "",
        issue=issue or "",
        pages=pages,
        doi=doi,
    )


# ---------------------------------------------------------------------------
# 中文统计结果格式化
# ---------------------------------------------------------------------------

def format_cn_stat_md(text: str) -> str:
    """国内心理学期刊统计结果格式化。

    中文期刊（心理学报/心理科学）沿用西文统计符号（t/F/r/p/η²），
    但排版习惯与 APA7 基本一致，直接复用 format_apa_stat_md。
    """
    return format_apa_stat_md(text)


# ---------------------------------------------------------------------------
# 格式转换：将 APA7 Markdown 草稿转为中文期刊格式
# ---------------------------------------------------------------------------

def convert_to_cn_format(md_text: str, journal: str = "xinlixuebao") -> str:
    """将 APA7 格式 Markdown 草稿转换为指定中文期刊格式。

    转换内容:
    - References 节头 → 参考文献
    - Abstract 节头 → 摘  要 / Abstract（双语）
    - Method/Results/Discussion 等节头 → 中文对应标题
    - 参考文献条目按 GB/T 7714 格式化（启发式）
    """
    if journal == "apa7":
        return md_text

    spec = get_journal_spec(journal)
    section_labels = spec.get("section_labels", {})
    ref_header = spec.get("ref_header", "参考文献")
    lines = md_text.splitlines()
    out: list[str] = []
    in_refs = False

    for line in lines:
        stripped = line.strip()

        # 节标题替换
        if stripped.startswith("#"):
            heading_text = stripped.lstrip("#").strip()
            hashes = stripped[:len(stripped) - len(stripped.lstrip("#"))]
            replaced = False
            for key, aliases in _CN_SECTION_ALIASES.items():
                if heading_text in aliases:
                    target = section_labels.get(key, heading_text)
                    out.append(f"{hashes} {target}")
                    replaced = True
                    if key == "introduction" and len(out) > 1:
                        # 引言后不需要节标题在国内期刊中通常省略，但保留以便编辑决定
                        pass
                    break
            if not replaced:
                if heading_text in ("References",):
                    out.append(f"{hashes} {ref_header}")
                    in_refs = True
                    replaced = True
                elif heading_text in ("参考文献",):
                    in_refs = True
                    out.append(line)
                    replaced = True
                else:
                    out.append(line)
            continue

        # 参考文献条目转换
        if in_refs and stripped and not stripped.startswith("#"):
            out.append(convert_apa_ref_to_cn(stripped))
            continue

        out.append(line)

    return "\n".join(out)


# ---------------------------------------------------------------------------
# CnJournalDocument
# ---------------------------------------------------------------------------

class CnJournalDocument(APA7Document):
    """中文心理学期刊文档（双语标题、双语摘要、中文关键词）。

    继承 APA7Document，扩展字段:
      cn_title: 中文标题
      cn_authors: 中文作者
      cn_abstract: 中文摘要
      cn_keywords: 中文关键词列表
      journal_id: 目标期刊 id

    to_markdown() 按目标期刊输出格式。
    """

    def __init__(
        self,
        title: str = "Untitled",
        cn_title: str = "",
        authors: str = "",
        cn_authors: str = "",
        affiliation: str = "",
        journal_id: str = "xinlixuebao",
        date_str: str = "",
    ) -> None:
        super().__init__(
            title=title,
            authors=authors,
            affiliation=affiliation,
            date_str=date_str,
        )
        self.cn_title = cn_title
        self.cn_authors = cn_authors
        self.journal_id = journal_id
        self.journal_spec = get_journal_spec(journal_id)
        self.cn_abstract: str = ""
        self.cn_keywords: list[str] = []

    def set_cn_abstract(self, text: str, keywords: list[str] | None = None) -> None:
        self.cn_abstract = text.strip()
        self.cn_keywords = keywords or []

    def to_markdown(self) -> str:
        """生成中文期刊格式 Markdown（双语标题 + 双语摘要 + 中文节标题）。"""
        spec = self.journal_spec
        kw_sep = spec.get("keyword_sep", "；")
        ref_header = spec.get("ref_header", "参考文献")
        zh_hdr = spec.get("abstract_header_zh", "摘  要")
        en_hdr = spec.get("abstract_header_en", "Abstract")
        zh_kw_hdr = spec.get("keyword_header_zh", "关键词")
        en_kw_hdr = spec.get("keyword_header_en", "Key words")
        is_cn = self.journal_id != "apa7"

        out: list[str] = ["---"]
        if self.cn_title:
            out.append(f"cn_title: {self.cn_title}")
        out.append(f"title: {self.title}")
        if self.cn_authors:
            out.append(f"cn_authors: {self.cn_authors}")
        out.append(f"authors: {self.authors}")
        out.append(f"affiliation: {self.affiliation}")
        out.append(f"journal: {spec['label']}")
        if self.cn_keywords:
            out.append(f"cn_keywords: {kw_sep.join(self.cn_keywords)}")
        if self.keywords:
            out.append(f"keywords: {', '.join(self.keywords)}")
        out.extend(["---", ""])

        # 标题（中文期刊: 中文标题在前，英文标题在后）
        if is_cn and self.cn_title:
            out.append(f"# {self.cn_title}")
            out.append(f"# {self.title}")
        else:
            out.append(f"# {self.title}")
        out.append("")

        # 双语摘要
        if is_cn:
            if self.cn_abstract:
                out.extend([f"## {zh_hdr}", "", self.cn_abstract])
                if self.cn_keywords:
                    out.extend(["", f"**{zh_kw_hdr}：** {kw_sep.join(self.cn_keywords)}"])
                out.append("")
            if self.abstract:
                out.extend([f"## {en_hdr}", "", self.abstract])
                if self.keywords:
                    out.extend(["", f"**{en_kw_hdr}:** {'; '.join(self.keywords)}"])
                out.append("")
        else:
            # APA7 模式: 仅英文摘要
            if self.abstract:
                out.extend(["## Abstract", "", self.abstract])
                if self.keywords:
                    out.extend(["", f"*Keywords:* {', '.join(self.keywords)}"])
                out.append("")

        # 正文 blocks
        section_labels = spec.get("section_labels", {})
        for kind, content in self.blocks:
            if kind == "p":
                out.extend([content, ""])
            elif kind == "table":
                caption, headers, rows = content
                if caption:
                    out.extend([caption, ""])
                sep = "|".join(["---"] * len(headers))
                out.append("| " + " | ".join(headers) + " |")
                out.append("| " + sep + " |")
                for row in rows:
                    out.append("| " + " | ".join(str(v) for v in row) + " |")
                out.append("")
            else:
                level = int(kind[1]) + 1
                heading_text = content
                if is_cn:
                    for key, aliases in _CN_SECTION_ALIASES.items():
                        if content in aliases:
                            heading_text = section_labels.get(key, content)
                            break
                out.extend([f"{'#' * level} {heading_text}", ""])

        # 参考文献
        if self.references:
            out.extend([f"## {ref_header}", ""])
            sorted_refs = sorted(self.references, key=str.lower)
            for i, r in enumerate(sorted_refs, 1):
                ref_text = convert_apa_ref_to_cn(r) if is_cn else r
                if is_cn:
                    out.extend([f"[{i}] {ref_text}", ""])
                else:
                    out.extend([r, ""])

        return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def cn_journal_cli(argv: list[str] | None = None) -> int:
    """psyclaw export --journal <id> 的格式转换入口。

    用法: cn_journal_cli([input_md, "--journal", "xinlixuebao", "--out", "out.md"])
    """
    import argparse

    p = argparse.ArgumentParser(prog="cn-journal", description="中文期刊格式转换")
    p.add_argument("file", help="输入 Markdown 草稿")
    p.add_argument(
        "--journal", "-j",
        choices=list(JOURNALS.keys()),
        default="xinlixuebao",
        help=f"目标期刊格式 ({', '.join(JOURNALS.keys())})，默认 xinlixuebao",
    )
    p.add_argument("--out", "-o", default=None, help="输出路径（默认打印到 stdout）")
    p.add_argument("--list-journals", action="store_true", help="列出可用期刊格式")
    args = p.parse_args(argv)

    if args.list_journals:
        for jid, label in list_journals().items():
            print(f"  {jid:<18} {label}")
        return 0

    src = Path(args.file)
    if not src.exists():
        print(f"[cn-journal] 文件不存在: {src}", file=sys.stderr)
        return 1

    md_text = src.read_text(encoding="utf-8")
    converted = convert_to_cn_format(md_text, args.journal)

    if args.out:
        Path(args.out).write_text(converted, encoding="utf-8")
        spec = get_journal_spec(args.journal)
        print(f"[cn-journal] 已转换为 {spec['label']} 格式 → {args.out}")
    else:
        print(converted)

    return 0
