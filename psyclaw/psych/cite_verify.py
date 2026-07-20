"""引用存在性查证——拿参考文献条目去真实索引里查,证明它确实存在。

为什么要有这层(psyclaw 的血泪教训):
系统提示词曾允许「凭记忆的文献条目标⚠未核实」,模型在检索失败后照此输出了整段
编造书目。规则层已改成零杜撰,但**规则是模型可以违反的,查证不行**——所以补这层
确定性核查(思路借鉴 academic-research-skills 的 lookup_verified 三态设计)。

与既有 citations.py 的分工:
- ``citations.audit_citations`` 查「文内引用是否溯源到本地检索语料」(离线,语料相对);
- ``citations.consistency_check`` 查「文内 ↔ 文末是否对得上」(离线,纯自洽);
- 本模块查「这条文献在现实世界里到底存不存在」(联网,绝对)——前两者都判不了
  「格式规整、内外自洽、但纯属虚构」的条目,这正是编造最常见的形态。

三态(照抄 ARS 的精确性优先原则,宁可不判也不误伤):
- ``verified``      索引里查到且作者姓氏+年份对得上 → 真实存在;
- ``not_found``     索引可达、查了、没有匹配 → **疑似杜撰,硬判据**;
- ``unresolvable``  网络/索引不可达,或本就不被索引收录(中文专著、灰色文献、
                    内部报告)→ **只提示不拦截**。把「查不到」和「没法查」混为一谈
                    会让整套核查失去公信力,所以严格区分。
"""

from __future__ import annotations

import re
import urllib.parse

# 年份容差:出版年 vs 在线优先/见刊年常差 1 年,卡死会造成大量假阳性
_YEAR_TOL = 1


def extract_title(raw: str) -> str:
    """从 APA 风格条目里取标题(``作者 (年). 标题. 期刊…``)。取不到返回空串。"""
    m = re.search(r"\(\s*\d{4}[a-z]?\s*\)\.?\s*(.+)", raw or "")
    if not m:
        return ""
    tail = m.group(1).strip()
    # 标题止于第一个句点(但别被 "Vol." "et al." "U.S." 这类缩写切断)
    parts = re.split(r"(?<=[a-z0-9\)\?\!])\.\s+", tail, maxsplit=1)
    return parts[0].strip(" .")[:300]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9一-鿿]+", " ", (s or "").lower()).strip()


def _match_ok(entry: dict, hit: dict) -> bool:
    """命中是否算「同一篇」:作者姓氏出现在作者串 且 年份在容差内。

    两个条件都要,单靠标题相似会把「同题不同文」判成存在;单靠作者年份会把
    同作者同年的另一篇判成存在——两种都会让杜撰蒙混过关。
    """
    surname = _norm(entry.get("surname") or "")
    if surname:
        authors = _norm(" ".join(hit.get("authors") or []))
        if surname not in authors:
            return False
    y_want, y_got = entry.get("year"), hit.get("year")
    if y_want and y_got:
        try:
            if abs(int(str(y_want)[:4]) - int(str(y_got)[:4])) > _YEAR_TOL:
                return False
        except (TypeError, ValueError):
            pass
    return True


def _crossref_bibliographic(raw: str, getter=None) -> list[dict]:
    """用 Crossref 的 query.bibliographic 端点整条匹配参考文献字符串。

    该端点就是为「拿一整条参考文献找对应记录」设计的,比拆字段再拼关键词准得多。
    """
    from psyclaw.psych import litsearch
    get = getter or litsearch._get
    params = {"query.bibliographic": raw[:400], "rows": 3,
              "select": "DOI,title,author,issued,container-title"}
    data = get("https://api.crossref.org/works?" + urllib.parse.urlencode(params))
    items = (data.get("message", {}).get("items", []) if isinstance(data, dict) else [])
    out = []
    for it in items:
        parts = (it.get("issued", {}) or {}).get("date-parts", [[None]])
        out.append({
            "title": (it.get("title") or [""])[0],
            "doi": it.get("DOI"),
            "year": parts[0][0] if parts and parts[0] else None,
            "authors": [f"{a.get('given', '')} {a.get('family', '')}".strip()
                        for a in (it.get("author") or [])[:8]],
            "venue": (it.get("container-title") or [""])[0],
            "source": "Crossref",
        })
    return [o for o in out if o["title"]]


def verify_entry(entry: dict, getter=None) -> dict:
    """查证单条参考文献 → ``{status, note, matched}``,status ∈ 上述三态。

    entry 至少含 ``raw``;有 ``surname``/``year`` 则用于匹配判定(见 _match_ok)。
    """
    raw = (entry.get("raw") or "").strip()
    if not raw:
        return {"status": "unresolvable", "note": "空条目", "matched": None}

    try:
        hits = _crossref_bibliographic(raw, getter=getter)
    except Exception as exc:  # noqa: BLE001  网络/索引不可达 ≠ 文献不存在
        return {"status": "unresolvable",
                "note": f"索引不可达({type(exc).__name__}),未能查证——不作为杜撰判据",
                "matched": None}

    for h in hits:
        if _match_ok(entry, h):
            return {"status": "verified",
                    "note": f"Crossref 命中 · doi:{h.get('doi') or '?'}",
                    "matched": h}
    if hits:
        return {"status": "not_found",
                "note": "索引有近似结果但作者/年份对不上——疑似杜撰或著录有误;"
                        f"最接近:{(hits[0].get('title') or '')[:70]}",
                "matched": None}
    return {"status": "not_found",
            "note": "Crossref 查无此文——疑似杜撰(若为中文专著/内部报告等不被收录的"
                    "文献类型,请人工确认后忽略)",
            "matched": None}


def verify_references(entries: list[dict], getter=None, limit: int = 40) -> dict:
    """批量查证 → 汇总。``suspect`` 非空即视为存在杜撰嫌疑(硬判据)。

    limit 兜底:稿件文献表动辄上百条,全查会打爆 Crossref 也拖垮体验;
    超出部分如实计入 ``skipped``(**绝不静默截断**——静默截断会让"全部通过"名不副实)。
    """
    checked, verified, suspect, unresolved = [], [], [], []
    for e in entries[:limit]:
        r = verify_entry(e, getter=getter)
        rec = {"raw": e.get("raw"), "status": r["status"], "note": r["note"],
               "doi": (r.get("matched") or {}).get("doi")}
        checked.append(rec)
        {"verified": verified, "not_found": suspect,
         "unresolvable": unresolved}[r["status"]].append(rec)
    skipped = max(0, len(entries) - limit)
    return {
        "n": len(entries), "checked_n": len(checked), "skipped": skipped,
        "verified": verified, "verified_n": len(verified),
        "suspect": suspect, "suspect_n": len(suspect),
        "unresolvable": unresolved, "unresolvable_n": len(unresolved),
        "checked": checked,
        # 判据:只有 not_found 算杜撰嫌疑;unresolvable 一律不拦
        "ok": not suspect,
    }
