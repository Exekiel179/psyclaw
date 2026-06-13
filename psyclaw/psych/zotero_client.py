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


def add_by_doi(doi: str) -> dict:
    """通过 DOI 把条目加入文库(用 Zotero 的 translation server 需额外服务;
    此处给元数据占位 + 引导)。"""
    return {"status": "guide",
            "note": (f"在 Zotero 中用 DOI {doi} 一键添加,或用浏览器插件抓取。"
                     "PsyClaw 可检索元数据,但导入你的私人文库建议在 Zotero 客户端完成。")}
