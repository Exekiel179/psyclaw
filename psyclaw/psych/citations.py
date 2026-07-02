"""引用保真核查 (citation fidelity) — 反杜撰参考文献。

``synthesize_review`` 已**指示** LLM「只准引用真实检索命中的键」,但**没有任何环节核验它
是否照做**——这正是 AI 写作最常见的学术不端漏洞(编造看似合理却不存在的参考文献)。本模块
补上这道**独立验收**:把稿件里出现的每一条文内引用,与检索命中的允许键集
(``notes/evidence_map.json`` 的 ``references[].key``,回落 ``notes/lit_search.json``)
逐一比对;比不上的 = **孤儿引用(疑似杜撰)**。

设计对齐项目铁律与 Claude Science「独立 reviewer 核查每条引用」思路:
- **实现与验收分离**:允许键由真实检索命中确定(DOI/题录可回溯),稿件由 LLM 生成,两者独立。
- **不算统计、不碰 data/raw**:纯文本比对,只读稿件与 notes/ 下的检索产物。
- **确定性、可单测**:``extract_intext_citations`` / ``audit_citations`` 是纯函数。
- **诚实降级**:无检索语料或稿件无可解析引用时,不假装"已核验通过"——``manual_review`` 显式标注。

比对粒度 = **(首位作者姓氏, 4 位年份)**。文内引用与 ``citation_key`` 都只暴露首作者,粒度天然
对齐;这也是查杜撰的行业标准粒度(能可靠抓出凭空捏造的作者/年份)。

对接门禁:``run_citation_audit`` 落 ``notes/citation_audit.json`` sidecar(``no_fabricated_citations``
布尔),``WRITE.citations`` 门禁(trigger ``citation_check``)据此 block 掉含孤儿引用的稿件。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# 年份 token:1500–2099(+ 可选消歧后缀 a/b/c)或 无日期。限定区间以免把样本量等 4 位数误当年份。
_YR = r"(?:1[5-9]\d{2}|20\d{2})[a-z]?|n\.d\."
# 一个作者姓氏 token:中文串,或大写起首的拉丁词(含重音/连字符/撇号)。
_NAME = r"(?:[一-鿿·]+|[A-Z][A-Za-zÀ-ɏ.'’\-]*)"
# 叙述式引用:  First (& Second | and Roe)* (et al.)?  (YEAR)   —— 作者在括号外。
# 连接词只认 `&` 与 `and`(citation_key 生成的键用 `&`;APA 叙述式用 "and")——**刻意不认逗号**:
# 逗号既是多作者分隔又是句内标点,"However, Ghost et al. (2020)" 会把转折词误并进作者段。
_NARRATIVE = re.compile(
    rf"({_NAME}(?:\s*(?:&|and)\s*{_NAME})*(?:\s+et\s+al\.?)?)\s*[(（]\s*({_YR})\s*[)）]"
)
# 参考文献 / 证据图谱区起始标记:该区本身就是允许键语料,不应作为「文内引用」再核验。
_REF_MARKS = ("## 证据图谱", "参考文献", "\n## references", "\n# references", "\nreferences\n")
# 括号(可能是夹注式引用,也可能是普通插注);内部按 ; 分条再判
_PAREN = re.compile(r"[(（]([^()（）]*?)[)）]")
# 夹注式单条:  Authors, YEAR   (末尾锚定年份,作者里须含至少一个 name token)
_PAREN_ITEM = re.compile(rf"^\s*(.*?),\s*({_YR})\s*$")
_NAME_RE = re.compile(_NAME)
# 从「Authors (YEAR)」形态的键里拆出作者段与年份(供解析允许键)。
_KEY_RE = re.compile(rf"^(.*?)[(（]\s*({_YR})\s*[)）]\s*$")


def _first_surname(chunk: str) -> str:
    """从作者段取**首位作者姓氏**,小写归一。

    与 ``synthesize._surname`` 消费的是同一批已生成好的键,故只需一致地约简两侧:
    切到第一个 ``& / , / and / et al`` 之前,再取末个空白 token(姓在末尾或整串即姓)。
    """
    head = re.split(r"\s*(?:&|,|、|\band\b|et\s+al)\.?", (chunk or "").strip(), maxsplit=1)[0]
    head = head.strip(" .，,")
    toks = head.split()
    tok = toks[-1] if toks else head
    return tok.lower().strip(".'’")


def _year_base(y: str) -> str:
    """年份归一:``2020a`` → ``2020``;``n.d.`` 原样。"""
    y = (y or "").strip().lower()
    return y[:4] if y[:4].isdigit() else y


def _canon(author_chunk: str, year: str) -> tuple[str, str]:
    return (_first_surname(author_chunk), _year_base(year))


def _canon_key(key: str) -> tuple[str, str] | None:
    """解析允许键 ``"Smith et al. (2020a)"`` → ``("smith", "2020")``。"""
    m = _KEY_RE.match((key or "").strip())
    if not m:
        return None
    surname = _first_surname(m.group(1))
    return (surname, _year_base(m.group(2))) if surname else None


def extract_intext_citations(text: str) -> list[dict]:
    """从稿件正文抽取文内引用(叙述式 + 夹注式)。纯函数,可单测。

    返回去重后(按 (姓氏,年份) 规范键去重)的 ``[{raw, surname, year, canon}]``。
    只关心「首位作者 + 年份」——足以查出凭空捏造的引用,且与 ``citation_key`` 粒度一致。
    """
    found: list[tuple[str, str, str]] = []  # (raw, author_chunk, year)
    for m in _NARRATIVE.finditer(text or ""):
        found.append((m.group(0).strip(), m.group(1), m.group(2)))
    for pm in _PAREN.finditer(text or ""):
        for part in re.split(r"[;；]", pm.group(1)):
            im = _PAREN_ITEM.match(part.strip())
            if im and _NAME_RE.search(im.group(1)):
                found.append((f"({part.strip()})", im.group(1), im.group(2)))

    seen: dict[tuple[str, str], dict] = {}
    for raw, chunk, year in found:
        surname, yb = _canon(chunk, year)
        if not surname:
            continue
        seen.setdefault((surname, yb), {
            "raw": raw, "surname": surname, "year": yb, "canon": (surname, yb)})
    return list(seen.values())


def audit_citations(text: str, allowed_keys: list[str]) -> dict:
    """核对稿件文内引用是否都能溯源到允许键集。纯函数,可单测。

    ``allowed_keys``:检索命中生成的允许引用键(``citation_key`` 形态)。
    返回含 ``no_fabricated_citations`` 布尔(孤儿数为 0)+ ``manual_review``(无语料/无引用→无法核验)。
    """
    allowed = {c for k in (allowed_keys or []) if (c := _canon_key(k))}
    cites = extract_intext_citations(text)
    if not allowed:
        # 无语料:无法判定任何引用是否杜撰 → 不产孤儿(避免过度拦),纯人工核。
        grounded, orphan, manual = [], [], True
    else:
        grounded = [c for c in cites if c["canon"] in allowed]
        orphan = [c for c in cites if c["canon"] not in allowed]
        manual = not cites

    if not allowed:
        method = "无检索语料(notes/evidence_map.json / lit_search.json 缺失),无法核验——需人工核"
    elif not cites:
        method = "稿件未解析到文内引用(可能无引用或格式特殊)——需人工核"
    else:
        method = (f"文内引用 {len(cites)} 条比对允许键 {len(allowed)} 个:"
                  f"溯源命中 {len(grounded)}、孤儿(疑似杜撰) {len(orphan)}")

    return {
        "allowed_n": len(allowed),
        "cited": [c["raw"] for c in cites],
        "cited_n": len(cites),
        "grounded_n": len(grounded),
        "orphan": [{"raw": c["raw"], "surname": c["surname"], "year": c["year"]}
                   for c in orphan],
        "orphan_n": len(orphan),
        "manual_review": manual,
        # 门禁判据:孤儿数为 0 = 未检出杜撰。语料/引用缺失时另由 manual_review 显式提示人工核,
        # 门禁只对**检出的**孤儿引用 fail-closed(不过度拦无引用的稿件)。
        "no_fabricated_citations": len(orphan) == 0,
        "method": method,
    }


def load_allowed(project_dir: str = ".") -> tuple[list[str], str | None]:
    """加载允许引用键:优先 ``notes/evidence_map.json``,回落 ``notes/lit_search.json``。

    回落时用 ``build_evidence_map`` 重建键,确保与稿件里的键同一确定性算法(含消歧)。
    """
    notes = Path(project_dir) / "notes"
    emap = notes / "evidence_map.json"
    if emap.exists():
        try:
            data = json.loads(emap.read_text(encoding="utf-8"))
            keys = [r["key"] for r in data.get("references", []) if r.get("key")]
            if keys:
                return keys, "notes/evidence_map.json"
        except (json.JSONDecodeError, OSError):
            pass
    ls = notes / "lit_search.json"
    if ls.exists():
        try:
            from psyclaw.psych.synthesize import build_evidence_map
            data = json.loads(ls.read_text(encoding="utf-8"))
            built = build_evidence_map("", data.get("results", []))
            keys = [r["key"] for r in built.get("references", []) if r.get("key")]
            return keys, "notes/lit_search.json"
        except (json.JSONDecodeError, OSError):
            pass
    return [], None


_NUMERIC_CITE = re.compile(r"(?<![\w.])\[\d{1,3}\](?![\w])")


def detect_citation_format(text: str) -> str:
    """粗判稿件文内引用格式:'author-year' | 'numeric' | 'mixed' | 'none'。纯函数。

    供期刊风格核对(如期刊要作者-年而稿件在用数字上标 [1] 时提醒)。作者-年数取自
    ``extract_intext_citations``;数字式数 ``[n]`` 括号编号(避开 URL/小数)。
    """
    ay = len(extract_intext_citations(text))
    num = len(_NUMERIC_CITE.findall(text or ""))
    if ay == 0 and num == 0:
        return "none"
    if ay and ay >= num:
        return "author-year"
    if num > ay and num >= 3:
        return "numeric"
    return "mixed"


def _body_only(text: str) -> str:
    """截去参考文献 / 证据图谱区(其本身即允许键语料),只留正文供文内引用核验。"""
    low = (text or "").lower()
    cut = len(text)
    for mark in _REF_MARKS:
        i = low.find(mark.lower())
        if i != -1:
            cut = min(cut, i)
    return text[:cut]


def _render_report(audit: dict) -> str:
    lines = ["# 引用保真核查报告", ""]
    lines.append(f"- 稿件:{audit.get('manuscript', '?')}")
    lines.append(f"- 允许键来源:{audit.get('corpus_source') or '(无)'}")
    lines.append(f"- 方法:{audit['method']}")
    lines.append("")
    if audit["orphan_n"]:
        lines.append(f"## ✗ 孤儿引用 {audit['orphan_n']} 条(疑似杜撰,溯源不到检索命中)")
        for o in audit["orphan"]:
            lines.append(f"- `{o['raw']}` — 未在允许键集中找到 ({o['surname']}, {o['year']})")
        lines.append("")
        lines.append("**处理**:删除该引用,或先 `psyclaw lit <检索式>` 把它检索进来再复核。")
    elif audit["manual_review"]:
        lines.append("## ⚠ 未能自动核验(需人工核)")
        lines.append(f"- {audit['method']}")
    else:
        lines.append(f"## ✓ 全部 {audit['cited_n']} 条文内引用均可溯源到检索命中")
    if audit.get("journal"):
        lines.append("")
        lines.append(f"## 期刊定制:{audit['journal']}")
        lines.append(f"- 期望引用风格:{audit.get('citation_style')} "
                     f"({audit.get('citation_format_expected')})")
        mark = "✓ 一致" if audit.get("citation_style_ok") else "⚠ 不一致(建议按期刊调整)"
        lines.append(f"- 稿件实测格式:{audit.get('citation_format_detected')} — {mark}")
        if audit.get("red_lines"):
            lines.append("- 退稿红线自查:")
            for r in audit["red_lines"]:
                lines.append(f"  - [ ] {r}")
    elif audit.get("journal_note"):
        lines.append("")
        lines.append(f"> {audit['journal_note']}")
    return "\n".join(lines) + "\n"


def _apply_journal(audit: dict, text: str, journal: str) -> None:
    """按期刊画像给 audit 附引用**风格**核对(软提示,不改 no_fabricated_citations 硬判据)。"""
    from psyclaw.psych.journals import expected_citation_format, get_journal
    profile = get_journal(journal)
    if not profile:
        audit["journal"] = None
        audit["journal_note"] = f"未收录期刊 {journal}(psyclaw journal 看目录)"
        return
    expected = expected_citation_format(profile)
    detected = detect_citation_format(text)
    style_ok = (not expected) or detected in ("none", "mixed") or detected == expected
    audit["journal"] = profile["name"]
    audit["citation_style"] = profile.get("citation_style")
    audit["citation_format_expected"] = expected
    audit["citation_format_detected"] = detected
    audit["citation_style_ok"] = style_ok
    audit["red_lines"] = profile.get("red_lines", [])


def run_citation_audit(manuscript_path: str, project_dir: str = ".",
                       journal: str | None = None) -> dict:
    """跑引用保真核查并落 sidecar + 人读报告。返回 audit dict。

    ``journal`` 给定时附该期刊的引用**风格**核对与退稿红线提示(软提示;
    孤儿引用仍是唯一的硬门禁判据)。
    """
    project = Path(project_dir)
    notes = project / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    mp = Path(manuscript_path)
    text = _body_only(mp.read_text(encoding="utf-8")) if mp.exists() else ""
    keys, source = load_allowed(project_dir)
    audit = audit_citations(text, keys)
    audit["manuscript"] = str(manuscript_path)
    audit["corpus_source"] = source
    if journal:
        _apply_journal(audit, text, journal)
    (notes / "citation_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    (notes / "citation_audit.md").write_text(_render_report(audit), encoding="utf-8")
    return audit
