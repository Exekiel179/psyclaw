"""文献矩阵 + 桥接结果导入(feat-104)——路线 B 的回灌闭环。

浏览器桥接检索(feat-103 计划包路线 B)产出 ``notes/bridge_results.md``
(Markdown 表格:标题|作者|年份|来源|关键词|摘要|链接);本模块把它导回
psyclaw 语料并生成**文献矩阵**:

- ``parse_bridge_results``:解析 Markdown 表 / CSV → 统一题录(纯函数);
  「未显示」等占位如实保留,缺标题的行剔除并计数,绝不编造;
- ``import_results``:合并进 ``notes/lit_search.json``(按 DOI/标题去重),
  PRISMA 记录追加导入痕迹——公开 API 与机构库命中汇成同一语料;
- ``build_matrix_md``:生成文献矩阵骨架(教学文档的字段约定:研究对象/
  方法/形式场景/发现/局限 = 「待核查」,纳入 = 待筛选;全文未获取如实标注),
  并把条目注册进 ``notes/evidence_map.json``——cite-check 允许键语料打通。
"""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path

# 表头别名 → 规范字段
_COL_ALIASES = {
    "title": ("标题", "题目", "title"),
    "authors": ("作者", "authors", "author"),
    "year": ("年份", "年", "year"),
    "source": ("来源", "期刊", "刊名", "source", "journal", "venue"),
    "keywords": ("关键词", "keywords"),
    "abstract": ("摘要", "abstract"),
    "url": ("链接", "url", "link", "网址"),
    "doi": ("doi",),
}
_PLACEHOLDER = ("未显示", "未获取", "全文未获取", "n/a", "na", "-", "—", "")


def _canon_col(name: str) -> str | None:
    low = (name or "").strip().lower()
    for canon, aliases in _COL_ALIASES.items():
        if low in aliases or any(a in low for a in aliases if len(a) > 2):
            return canon
    return None


def _clean_cell(v: str) -> str:
    v = (v or "").strip()
    return "" if v.lower() in _PLACEHOLDER else v


def _row_to_paper(row: dict) -> dict | None:
    title = _clean_cell(row.get("title", ""))
    if not title:
        return None
    authors = [a for a in re.split(r"[;；,，、&]| and ", _clean_cell(row.get("authors", "")))
               if a.strip()]
    year = None
    ym = re.search(r"(1[5-9]\d{2}|20\d{2})", row.get("year", "") or "")
    if ym:
        year = int(ym.group(1))
    return {"title": title, "authors": [a.strip() for a in authors], "year": year,
            "doi": _clean_cell(row.get("doi", "")) or None,
            "abstract": _clean_cell(row.get("abstract", "")),
            "oa_status": "unknown", "oa_url": _clean_cell(row.get("url", "")) or None,
            "source": "bridge:" + (_clean_cell(row.get("source", "")) or "机构库"),
            "keywords": _clean_cell(row.get("keywords", ""))}


def parse_bridge_results(text: str) -> dict:
    """解析桥接结果(Markdown 表优先,CSV 兜底)→ {papers, skipped}。纯函数。"""
    papers: list[dict] = []
    skipped = 0
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    md_rows = [ln for ln in lines if ln.strip().startswith("|")]
    if len(md_rows) >= 2:                        # Markdown 表
        header = [c.strip() for c in md_rows[0].strip().strip("|").split("|")]
        cols = [_canon_col(h) for h in header]
        for ln in md_rows[1:]:
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if all(set(c) <= {"-", ":", " "} for c in cells):
                continue                          # 分隔行
            row = {c: cells[i] for i, c in enumerate(cols)
                   if c and i < len(cells)}
            p = _row_to_paper(row)
            papers.append(p) if p else None
            skipped += 0 if p else 1
        return {"papers": papers, "skipped": skipped}
    # CSV 兜底
    try:
        reader = csv.DictReader(io.StringIO(text))
        for raw in reader:
            row = {}
            for k, v in raw.items():
                c = _canon_col(k or "")
                if c:
                    row[c] = v or ""
            p = _row_to_paper(row)
            papers.append(p) if p else None
            skipped += 0 if p else 1
    except csv.Error:
        pass
    return {"papers": papers, "skipped": skipped}


def _norm_title(t: str) -> str:
    return re.sub(r"[\W_]+", "", (t or "").lower())


def import_results(file_path: str, project_dir: str = ".") -> dict:
    """把桥接结果并入 notes/lit_search.json(DOI/标题去重),PRISMA 追加导入痕迹。"""
    p = Path(file_path)
    if not p.exists():
        raise ValueError(f"结果文件不存在:{file_path}")
    parsed = parse_bridge_results(p.read_text(encoding="utf-8", errors="replace"))
    notes = Path(project_dir) / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    corpus_p = notes / "lit_search.json"
    corpus = {"results": [], "n_raw": 0, "n_deduped": 0, "n_duplicates": 0,
              "per_source": {}}
    if corpus_p.exists():
        try:
            corpus = json.loads(corpus_p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    seen = {(_norm_title(x.get("title", "")) or None) for x in corpus.get("results", [])}
    seen |= {x.get("doi") for x in corpus.get("results", []) if x.get("doi")}
    added, dup = 0, 0
    for paper in parsed["papers"]:
        key_t, key_d = _norm_title(paper["title"]), paper.get("doi")
        if key_t in seen or (key_d and key_d in seen):
            dup += 1
            continue
        corpus.setdefault("results", []).append(paper)
        seen.add(key_t)
        if key_d:
            seen.add(key_d)
        added += 1
    corpus["n_raw"] = int(corpus.get("n_raw", 0)) + len(parsed["papers"])
    corpus["n_deduped"] = len(corpus["results"])
    corpus["n_duplicates"] = int(corpus.get("n_duplicates", 0)) + dup
    corpus.setdefault("per_source", {})["bridge"] = \
        int(corpus["per_source"].get("bridge", 0)) + added
    corpus_p.write_text(json.dumps(corpus, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    prisma = notes / "prisma_search.md"
    line = (f"- 机构库导入({p.name}):解析 {len(parsed['papers'])} 条,"
            f"新增 {added},重复 {dup},缺标题剔除 {parsed['skipped']}\n")
    if prisma.exists():
        prisma.write_text(prisma.read_text(encoding="utf-8") + line, encoding="utf-8")
    else:
        prisma.write_text("# PRISMA 检索记录\n\n" + line, encoding="utf-8")
    return {"parsed": len(parsed["papers"]), "added": added, "duplicates": dup,
            "skipped": parsed["skipped"], "total": corpus["n_deduped"],
            "corpus_path": str(corpus_p)}


_MATRIX_FIELDS = ["键", "标题", "作者(年份)", "来源", "研究对象", "研究方法",
                  "形式/场景", "主要发现", "局限", "纳入?"]


def build_matrix_md(papers: list[dict], topic: str = "") -> tuple[str, dict]:
    """文献矩阵骨架 → (markdown, evidence_map)。纯函数。

    已知字段填入,内容字段=「待核查」,纳入=待筛选;键与 evidence_map 同源
    (synthesize 的 citation key),综述引用可直接溯源到矩阵行。
    """
    from psyclaw.psych.synthesize import build_evidence_map
    emap = build_evidence_map(topic or "文献矩阵", papers)
    refs = {r["key"]: r for r in emap.get("references", [])}
    lines = [
        f"# 文献矩阵 — {topic or '(未命名主题)'}",
        "",
        "> 约定:内容字段未读原文前一律「待核查」;找不到全文标注「全文未获取」;",
        "> 绝不编造摘要/全文中没有的信息。筛选按 notes/screening_criteria.json 的",
        "> 预先声明标准执行,只输出 纳入/排除 + 理由,不得改标准。",
        "",
        "| " + " | ".join(_MATRIX_FIELDS) + " |",
        "|" + "|".join("---" for _ in _MATRIX_FIELDS) + "|",
    ]
    for p, ref in zip(papers, emap.get("references", [])):
        au = ", ".join(p.get("authors", [])[:2]) or "待核查"
        yr = p.get("year") or "?"
        title = (p.get("title", "") or "").replace("|", "/")[:60]
        has_abs = bool((p.get("abstract") or "").strip())
        content = "见摘要,待核查" if has_abs else "待核查(全文未获取)"
        lines.append(
            f"| {ref['key']} | {title} | {au}({yr}) | "
            f"{(p.get('source') or '?').replace('|', '/')} | 待核查 | {content} | "
            f"待核查 | 待核查 | 待核查 | ☐ 待筛选 |")
    lines += ["",
              f"共 {len(papers)} 条;下一步:①按标准筛选(填「纳入?」列并给理由);"
              "②对纳入项取全文(psyclaw lit --fulltext <DOI> / Zotero)补内容列;"
              "③psyclaw research 据语料合成综述。"]
    return "\n".join(lines) + "\n", emap


def write_matrix(project_dir: str = ".", topic: str = "") -> dict:
    """从 notes/lit_search.json 生成 notes/lit_matrix.md + evidence_map.json。"""
    notes = Path(project_dir) / "notes"
    corpus_p = notes / "lit_search.json"
    if not corpus_p.exists():
        raise ValueError("无检索语料:先 psyclaw lit <检索式> 或 lit --import <结果表>")
    corpus = json.loads(corpus_p.read_text(encoding="utf-8"))
    papers = corpus.get("results", [])
    if not papers:
        raise ValueError("检索语料为空,矩阵无从生成")
    md, emap = build_matrix_md(papers, topic=topic)
    matrix_p = notes / "lit_matrix.md"
    matrix_p.write_text(md, encoding="utf-8")
    emap_p = notes / "evidence_map.json"
    emap_p.write_text(json.dumps(emap, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    return {"n": len(papers), "matrix_path": str(matrix_p),
            "evidence_map_path": str(emap_p)}
