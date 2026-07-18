"""cite「引用文章」半:文献元数据 → 规范参考文献条目 + 文内引用(stdlib only)。

cite 的另一半是引文核查(citations.py);本模块把结构化元数据(作者/年/题/刊/卷期页/
doi)格式化成可直接粘进参考文献表的 APA7 条目,并给叙述式/夹注式两种文内引用,
免去手排格式易错的活。纯字符串处理——无网络、无统计(守铁律)。

DOI 解析、在线检索元数据不在此:那要联网,交外部(psyclaw lit / MCP)。本模块只做
「已有元数据 → 规范格式」这一段确定性变换,可离线、可单测。
"""

from __future__ import annotations

_ENDASH = "–"   # en dash,APA7 页码/范围用


def parse_author(name: str) -> tuple[str, str]:
    """把一个作者名解析成 (姓, 首字母缩写)。支持两种写法:

    - 「姓, 名 中间名」(如 "Hamaker, Ellen L.") ;
    - 「名 中间名 姓」(如 "Ellen L. Hamaker")。
    返回 (family, "E. L.");无法解析返回 (原串.strip(), "")。
    """
    s = (name or "").strip()
    if not s:
        return ("", "")
    if "," in s:
        family, _, given = s.partition(",")
        family = family.strip()
        given_parts = given.split()
    else:
        parts = s.split()
        if len(parts) == 1:
            return (parts[0], "")
        family = parts[-1]
        given_parts = parts[:-1]
    initials = " ".join(f"{p[0].upper()}." for p in given_parts if p and p[0].isalpha())
    return (family, initials)


def _ref_author(name: str) -> str:
    """单个作者的参考文献表形态:「Family, I. M.」。"""
    family, initials = parse_author(name)
    if not family:
        return ""
    return f"{family}, {initials}" if initials else family


def format_authors_ref(authors: list[str]) -> str:
    """APA7 参考文献表的作者串。

    ≤20 人全列,最后一位前加「, & 」;>20 人列前 19 + 「, ... 」+ 最后一位。
    """
    names = [_ref_author(a) for a in (authors or []) if (a or "").strip()]
    names = [n for n in names if n]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) <= 20:
        return ", ".join(names[:-1]) + ", & " + names[-1]
    # >20:前 19 + 省略号 + 末位(APA7 规则)
    return ", ".join(names[:19]) + ", ... " + names[-1]


def intext_citation(meta: dict, paren: bool = True) -> str:
    """文内引用。paren=True 夹注式「(Family & Family, Year)」,
    False 叙述式「Family and Family (Year)」。3+ 作者用「et al.」。"""
    authors = meta.get("authors") or []
    families = [parse_author(a)[0] for a in authors if (a or "").strip()]
    families = [f for f in families if f]
    year = str(meta.get("year", "") or "n.d.").strip()

    if not families:
        names = ""
    elif len(families) == 1:
        names = families[0]
    elif len(families) == 2:
        joiner = " & " if paren else " and "
        names = joiner.join(families)
    else:
        names = f"{families[0]} et al."

    if paren:
        inside = f"{names}, {year}" if names else year
        return f"({inside})"
    return f"{names} ({year})" if names else f"({year})"


def _fmt_pages(pages: str) -> str:
    """页码范围里的连字符归一成 en dash(APA7)。"""
    p = str(pages or "").strip()
    if not p:
        return ""
    return p.replace("--", _ENDASH).replace("-", _ENDASH)


def format_reference(meta: dict, style: str = "apa7") -> str:
    """把元数据格式化成一条参考文献。当前 style 仅 apa7(期刊论文)。

    meta 键:authors(list[str])、year、title、journal、volume、issue、pages、doi。
    缺省的可选字段(卷/期/页/doi)优雅省略,不留空壳标点。
    """
    authors = format_authors_ref(meta.get("authors") or [])
    year = str(meta.get("year", "") or "n.d.").strip()
    title = str(meta.get("title", "") or "").strip()
    journal = str(meta.get("journal", "") or "").strip()
    volume = str(meta.get("volume", "") or "").strip()
    issue = str(meta.get("issue", "") or "").strip()
    pages = _fmt_pages(meta.get("pages", ""))
    doi = str(meta.get("doi", "") or "").strip()

    parts: list[str] = []
    if authors:
        parts.append(f"{authors} ({year}).")
    else:
        parts.append(f"({year}).")
    if title:
        # 题名已以句末标点(. ? !)结尾则不再补句点(APA7:Does it work? 不加点)
        parts.append(title if title[-1] in ".?!" else f"{title}.")

    # 期刊 + 卷(期), 页. —— 只拼出现的段,避免「J, (), .」空壳
    if journal:
        src = journal
        if volume:
            src += f", {volume}"
            if issue:
                src += f"({issue})"
        elif issue:
            src += f", ({issue})"
        if pages:
            src += f", {pages}"
        parts.append(src + ".")

    ref = " ".join(parts)
    if doi:
        url = doi if doi.startswith("http") else f"https://doi.org/{doi}"
        ref = ref + " " + url
    return ref.strip()


def render_references(entries: list[dict], style: str = "apa7") -> str:
    """把多条元数据渲染成参考文献表(按作者姓字母序)+ 各自文内引用提示。"""
    formatted = []
    for m in entries or []:
        ref = format_reference(m, style=style)
        intext = intext_citation(m, paren=True)
        formatted.append((ref, intext))
    formatted.sort(key=lambda t: t[0].lower())
    lines = ["参考文献（APA7）:", ""]
    for ref, intext in formatted:
        lines.append(ref)
        lines.append(f"    文内引用：{intext}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
