"""lit 自动调 WebBridge 进机构库(知网/万方)检索并合并(stdlib only)。

lit 只打公开 API(OpenAlex/EuropePMC)——中文文献大量在知网,公开 API 检不到。此前
只能提示用户手动走浏览器桥;本模块让 psyclaw **自己驱动** Kimi WebBridge(复用用户
已登录的真实浏览器):navigate 到机构库检索页 → evaluate 注入 JS 抽取结果行 → 归一成
lit 题录 schema → 与公开 API 结果合并去重。

铁律对齐:psyclaw 仓内零浏览器逻辑,一切经 webbridge.call 的 HTTP API 外移;抓取用
注入页面的 JS(在用户浏览器里跑),仓内只拼 URL/选择器/解析。全程 fail-safe:桥不可用、
navigate 失败、抽取为空、任何异常都不抛,降级回公开 API 结果——绝不中断 lit。

机构库页面结构会变:DB 画像(URL + 抽取选择器)集中在 _DB_PROFILES,坏了改这里即可,
且抽取 JS 多选择器兜底,抽不到就返回空(交由 lit 提示用户人工浏览/`lit --import` 回灌)。
"""

from __future__ import annotations

import json
from urllib.parse import quote


# 机构库画像:检索 URL 模板 + 结果行/字段选择器(易变,坏了改这里)
_DB_PROFILES: dict[str, dict] = {
    "cnki": {
        "name": "知网",
        # CNKI 快速检索结果页(主题检索);登录态由用户真实浏览器提供
        "search_url": "https://kns.cnki.net/kns8s/defaultresult/index?kw={q}&korder=SU",
        "row": ["table.result-table-list tbody tr", ".result-table-list tbody tr",
                "table tbody tr"],
        "title": ["td.name a", ".name a", "td.name", "a"],
        "author": ["td.author", ".author"],
        "source": ["td.source", ".source"],
        "date": ["td.date", ".date"],
    },
    "wanfang": {
        "name": "万方",
        "search_url": "https://s.wanfangdata.com.cn/paper?q={q}",
        "row": [".normal-list .list-item", ".result-list .list-item", "li.list-item"],
        "title": [".title a", ".title", "a.title"],
        "author": [".author", ".authors"],
        "source": [".periodical", ".source"],
        "date": [".year", ".date"],
    },
}

DEFAULT_DB = "cnki"


def bridge_available(installed_fn=None, status_fn=None) -> tuple[bool, str]:
    """WebBridge 是否可自动驱动:二进制在位 + 守护进程可达 + 扩展已连。

    返回 (ok, reason)。任一不满足 → (False, 人读原因)。检测失败一律判不可用,不抛。
    """
    try:
        if installed_fn is None or status_fn is None:
            from psyclaw import webbridge as wb
            installed_fn = installed_fn or wb.binary_installed
            status_fn = status_fn or wb.daemon_status
        if not installed_fn():
            return False, "WebBridge 未安装(psyclaw webbridge install)"
        st = status_fn(timeout=2.0) if _accepts_timeout(status_fn) else status_fn()
        if not st:
            return False, "WebBridge 守护进程未运行(psyclaw webbridge start)"
        if not st.get("extension_connected"):
            return False, "浏览器扩展未连接(psyclaw webbridge status 查看)"
        return True, ""
    except Exception:  # noqa: BLE001 — 探测异常一律判不可用
        return False, "WebBridge 状态探测失败"


def _accepts_timeout(fn) -> bool:
    try:
        import inspect
        return "timeout" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def db_search_url(db: str, query: str) -> str:
    """机构库检索 URL(查询做 URL 编码)。未知库返回空串。"""
    prof = _DB_PROFILES.get((db or "").lower())
    if not prof:
        return ""
    return prof["search_url"].format(q=quote((query or "").strip()))


def _extract_js(db: str) -> str:
    """生成在机构库结果页里跑的抽取 JS(多选择器兜底,返回 [{title,authors,year,source}])。"""
    prof = _DB_PROFILES.get(db, {})
    cfg = {k: prof.get(k, []) for k in ("row", "title", "author", "source", "date")}
    # JS:按 row 选择器找结果行,每行取 title/author/source/date 首个命中的选择器文本
    return (
        "(() => {\n"
        f"  const S = {json.dumps(cfg, ensure_ascii=False)};\n"
        "  const pick = (el, sels) => { for (const s of sels) { const n = el.querySelector(s);"
        " if (n && n.textContent.trim()) return n.textContent.trim(); } return ''; };\n"
        "  let rows = []; for (const rs of S.row) { rows = document.querySelectorAll(rs);"
        " if (rows.length) break; }\n"
        "  const out = [];\n"
        "  rows.forEach(r => { const t = pick(r, S.title); if (!t) return;\n"
        "    out.push({ title: t, authors: pick(r, S.author),\n"
        "      source: pick(r, S.source), year: (pick(r, S.date).match(/\\d{4}/)||[''])[0] }); });\n"
        "  return out.slice(0, 40);\n"
        "})()"
    )


def _split_authors(raw) -> list:
    if isinstance(raw, list):
        return [a.strip() for a in raw if str(a).strip()]
    s = str(raw or "").strip()
    if not s:
        return []
    import re
    parts = re.split(r"[;,、；，\s]+", s)
    return [p.strip() for p in parts if p.strip()]


def _payload_to_list(raw) -> list:
    """把 evaluate 的返回(可能是 list / {"result":list} / JSON 字符串)取成 list。"""
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return []
    if isinstance(raw, dict):
        for k in ("result", "data", "value", "records"):
            if isinstance(raw.get(k), list):
                return raw[k]
        return []
    return raw if isinstance(raw, list) else []


def parse_bridge_results(raw, source: str = "") -> list:
    """把抽取到的原始行归一成 lit 题录 schema(与 litsearch._record 同键)。

    空标题剔除;作者串按分隔符拆列表;补齐 doi/abstract/oa_* 等键(桥题录一般无 DOI)。
    """
    rows = _payload_to_list(raw)
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title", "") or "").strip()
        if not title:
            continue
        year = str(row.get("year", "") or "").strip() or None
        out.append({
            "title": title,
            "authors": _split_authors(row.get("authors")),
            "year": year,
            "doi": None,
            "abstract": str(row.get("abstract", "") or "").strip(),
            "oa_status": "unknown",
            "oa_url": None,
            "source": source or str(row.get("source", "") or "").strip() or "机构库",
            "pmid": None, "pmcid": None, "arxiv_id": None,
        })
    return out


def bridge_search(query: str, db: str = DEFAULT_DB, *, call=None,
                  available_fn=None, limit: int = 40) -> dict:
    """驱动 WebBridge 到机构库检索并抽取结果。返回 {ok, reason, records, db, name}。

    fail-safe:桥不可用/URL 未知/navigate 失败/抽取异常都 → ok=False(或空 records),
    绝不抛。call、available_fn 可注入,离线单测。
    """
    prof = _DB_PROFILES.get((db or "").lower())
    name = prof["name"] if prof else db
    result = {"ok": False, "reason": "", "records": [], "db": db, "name": name}
    try:
        avail = available_fn or bridge_available
        ok, reason = avail()
        if not ok:
            result["reason"] = reason
            return result
        if not prof:
            result["reason"] = f"未知机构库:{db}"
            return result
        url = db_search_url(db, query)
        if call is None:
            from psyclaw import webbridge as wb
            call = wb.call

        nav = call("navigate", {"url": url, "newTab": True,
                                "group_title": "psyclaw-lit"})
        if not (isinstance(nav, dict) and nav.get("success", True) is not False):
            result["reason"] = f"打开检索页失败:{(nav or {}).get('error', '未知')}"
            return result

        ev = call("evaluate", {"code": _extract_js((db or "").lower())})
        if isinstance(ev, dict) and ev.get("success") is False:
            result["reason"] = f"抽取失败:{ev.get('error', '未知')}"
            return result
        payload = ev.get("result", ev) if isinstance(ev, dict) else ev
        records = parse_bridge_results(payload, source=name)[:limit]
        result["ok"] = True
        result["records"] = records
        if not records:
            result["reason"] = "结果页已在浏览器打开,但未自动抽取到题录(可人工浏览或 lit --import 回灌)"
        return result
    except Exception as exc:  # noqa: BLE001 — 任何异常都不中断 lit
        result["reason"] = f"桥接检索异常:{exc}"
        return result


def merge_results(api_results: list, bridge_records: list) -> tuple[list, int]:
    """把桥题录并进公开 API 结果,按 (doi 或 题名前 80 字) 去重(与 litsearch 同口径)。

    返回 (合并后列表, 新增条数)。
    """
    def _key(r: dict) -> str:
        return (r.get("doi") or "").lower() or (r.get("title") or "").lower().strip()[:80]

    seen = {_key(r) for r in api_results}
    merged = list(api_results)
    added = 0
    for r in bridge_records:
        k = _key(r)
        if k and k not in seen:
            seen.add(k)
            merged.append(r)
            added += 1
    return merged, added
