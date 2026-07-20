"""Zotero 直连(Web API v3,纯 stdlib)。

用途:复用用户**已有/已购**的文库与 PDF 全文——这是付费墙文献的合法全文来源
(用户自己有访问权)。

需环境变量:ZOTERO_API_KEY、ZOTERO_LIBRARY_ID(可选 ZOTERO_LIBRARY_TYPE=user|group)。
也可对接用户已连的 zotero MCP;此模块为 psyclaw 独立直连路径。

能力:搜文库、按 DOI 定位条目、取已索引全文、加条目(by DOI)。
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

BASE = "https://api.zotero.org"
TIMEOUT = 30


def _creds():
    key = os.environ.get("ZOTERO_API_KEY", "")
    lib = os.environ.get("ZOTERO_LIBRARY_ID", "")
    typ = os.environ.get("ZOTERO_LIBRARY_TYPE", "user")
    return key, lib, typ


def _req(path: str, method: str = "GET", body: bytes | None = None,
         extra_headers: dict | None = None):
    key, lib, typ = _creds()
    url = f"{BASE}/{typ}s/{lib}/{path}"
    headers = {"Zotero-API-Version": "3", "Authorization": f"Bearer {key}",
               "User-Agent": "PsyClaw/0.1", **(extra_headers or {})}
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        data = r.read().decode("utf-8", errors="replace")
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return data


def available() -> bool:
    key, lib, _ = _creds()
    return bool(key and lib)


def search_library(q: str, limit: int = 10) -> list:
    """全文+元数据检索用户文库。"""
    params = urllib.parse.urlencode({"q": q, "qmode": "everything",
                                     "limit": limit, "itemType": "-attachment"})
    data = _req(f"items?{params}")
    out = []
    for it in (data if isinstance(data, list) else []):
        d = it.get("data", {})
        out.append({"key": it.get("key"), "title": d.get("title", ""),
                    "doi": d.get("DOI"), "year": (d.get("date") or "")[:4],
                    "creators": [c.get("lastName", "") for c in d.get("creators", [])[:5]],
                    "itemType": d.get("itemType")})
    return out


def find_by_doi(doi: str) -> dict | None:
    for it in search_library(doi, limit=5):
        if (it.get("doi") or "").lower() == doi.lower():
            return it
    return None


def get_fulltext(item_key: str) -> str | None:
    """取条目的子附件中已索引的全文(Zotero 对 PDF 做了全文索引)。"""
    children = _req(f"items/{item_key}/children")
    for ch in (children if isinstance(children, list) else []):
        if ch.get("data", {}).get("itemType") == "attachment":
            ck = ch.get("key")
            try:
                ft = _req(f"items/{ck}/fulltext")
                if isinstance(ft, dict) and ft.get("content"):
                    return ft["content"]
            except Exception:  # noqa: BLE001
                continue
    return None


def get_fulltext_by_doi(doi: str) -> dict:
    """合法路径:从用户**自己的** Zotero 文库取该 DOI 的全文。"""
    if not available():
        return {"status": "no_creds",
                "note": "未配置 ZOTERO_API_KEY/ZOTERO_LIBRARY_ID(psyclaw config)。"}
    item = find_by_doi(doi)
    if not item:
        return {"status": "not_in_library",
                "note": f"DOI {doi} 不在你的 Zotero 文库。先把 PDF 存进 Zotero。"}
    text = get_fulltext(item["key"])
    if text:
        return {"status": "fulltext", "channel": "Zotero(你的文库)",
                "chars": len(text), "title": item["title"],
                "text": text[:3000] + ("…" if len(text) > 3000 else "")}
    return {"status": "no_indexed_text", "title": item["title"],
            "note": "条目在库但无已索引全文。请在 Zotero 中打开该 PDF 触发索引。"}


def _crossref_meta(doi: str, getter=None) -> dict | None:
    """按 DOI 取 Crossref 元数据(Zotero 的 translation server 是独立服务,
    但我们本来就在用 Crossref,直接拿它拼条目即可,不必多引入一个服务)。"""
    from psyclaw.psych import litsearch
    get = getter or litsearch._get
    data = get(f"https://api.crossref.org/works/{urllib.parse.quote(doi)}")
    return (data or {}).get("message") if isinstance(data, dict) else None


def _to_zotero_item(m: dict) -> dict:
    """Crossref message → Zotero journalArticle 条目。"""
    parts = (m.get("issued", {}) or {}).get("date-parts", [[None]])
    year = parts[0][0] if parts and parts[0] else None
    return {
        "itemType": "journalArticle",
        "title": (m.get("title") or [""])[0],
        "creators": [{"creatorType": "author",
                      "firstName": a.get("given", ""),
                      "lastName": a.get("family", "")}
                     for a in (m.get("author") or []) if a.get("family")],
        "publicationTitle": (m.get("container-title") or [""])[0],
        "volume": str(m.get("volume") or ""),
        "issue": str(m.get("issue") or ""),
        "pages": str(m.get("page") or ""),
        "date": str(year or ""),
        "DOI": m.get("DOI") or "",
        "url": m.get("URL") or "",
        "libraryCatalog": "Crossref (via PsyClaw)",
    }


def add_by_doi(doi: str, getter=None, poster=None) -> dict:
    """按 DOI 真正写入用户 Zotero 文库(Crossref 取元数据 → POST items)。

    幂等:已在库则不重复添加(Zotero 允许重复条目,重复写会污染用户文库)。
    写用户私人文库属副作用操作,调用方须走审批。
    """
    doi = (doi or "").strip()
    if not doi:
        return {"status": "error", "note": "需要 DOI"}
    if not available():
        return {"status": "no_creds",
                "note": "未配置 ZOTERO_API_KEY/ZOTERO_LIBRARY_ID(psyclaw config)。"}
    try:
        if find_by_doi(doi):                      # 幂等:不制造重复条目
            return {"status": "exists", "doi": doi,
                    "note": f"DOI {doi} 已在你的文库,未重复添加。"}
    except Exception as exc:  # noqa: BLE001  查重失败不等于该写入,宁可不写
        return {"status": "error", "note": f"查重失败,未写入:{exc}"}

    try:
        meta = _crossref_meta(doi, getter=getter)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "note": f"Crossref 取元数据失败:{exc}"}
    if not meta or not (meta.get("title") or [""])[0]:
        return {"status": "not_found",
                "note": f"Crossref 查无 DOI {doi} 的元数据,未写入(避免存入空条目)。"}

    item = _to_zotero_item(meta)
    try:
        post = poster or (lambda body: _req(
            "items", method="POST", body=body,
            extra_headers={"Content-Type": "application/json"}))
        resp = post(json.dumps([item]).encode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "note": f"写入 Zotero 失败:{exc}"}

    succ = ((resp or {}).get("successful") or {}) if isinstance(resp, dict) else {}
    failed = ((resp or {}).get("failed") or {}) if isinstance(resp, dict) else {}
    if failed:
        return {"status": "error", "title": item["title"],
                "note": f"Zotero 拒收:{json.dumps(failed, ensure_ascii=False)[:160]}"}
    key = None
    for v in succ.values():
        key = (v or {}).get("key") if isinstance(v, dict) else None
    return {"status": "added", "key": key, "doi": doi, "title": item["title"],
            "note": f"已加入 Zotero 文库:{item['title'][:60]}"}
