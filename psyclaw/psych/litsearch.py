"""文献检索 + 全文获取(纯 stdlib urllib)。

合规边界(重要):
- 检索走公开学术 API:OpenAlex、Europe PMC、Crossref、arXiv。
- **全文只走合法开放获取(OA)渠道**:Unpaywall(DOI→合法 OA 链接)、
  Europe PMC 全文 XML(OA 子集)、PMC、arXiv/预印本 PDF。
- 付费墙文章**不绕过**:只取摘要,明确标注 closed,引导用户用机构权限或 Zotero
  已购 PDF(见 zotero_client)。
- 所有请求带 User-Agent + mailto(OpenAlex/Crossref 礼貌池要求)。

PRISMA:检索→去重→筛选的计数贯穿,对接 LIT.prisma 质量检查。
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

UA = "PsyClaw/0.1 (research tool; mailto:psyclaw@example.org)"
TIMEOUT = 30


def _get(url: str, headers: dict | None = None) -> dict | str:
    # feat-128:启用沙箱时,学术 API 请求过网络面裁决(白名单外拒;PDF 下载
    # 是用户明确要的 OA 只读内容,走 download_pdf 不经此,不受白名单硬拦)。
    try:
        from psyclaw import sandbox as _sb
        pol = _sb.load_policy(".")
        if pol.get("enabled"):
            v = _sb.sandbox_check("net", "get", {"url": url}, project_dir=".")
            if not v["allow"]:
                raise urllib.error.URLError(f"沙箱网络面拒绝:{v['reason']}")
    except urllib.error.URLError:
        raise
    except Exception:  # noqa: BLE001  # 沙箱异常不阻断检索
        pass
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        data = r.read().decode("utf-8", errors="replace")
    ctype = r.headers.get("Content-Type", "")
    if "json" in ctype or data.lstrip().startswith(("{", "[")):
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return data
    return data


# ---------------------------------------------------------------------------
# 统一结果模型
# ---------------------------------------------------------------------------

def _paper(title="", authors=None, year=None, doi=None, abstract="",
           oa_status="unknown", oa_url=None, source="", pmid=None,
           pmcid=None, arxiv_id=None, citations=None) -> dict:
    return {"title": title, "authors": authors or [], "year": year, "doi": doi,
            "abstract": abstract, "oa_status": oa_status, "oa_url": oa_url,
            "source": source, "pmid": pmid, "pmcid": pmcid, "arxiv_id": arxiv_id,
            "citations": citations}   # citations:被引数(Semantic Scholar 给,影响力信号)


# ---------------------------------------------------------------------------
# OpenAlex(覆盖最广,自带 OA 状态)
# ---------------------------------------------------------------------------

def _paper_from_oa(w: dict) -> dict:
    """OpenAlex work → 统一题录(检索与引用滚雪球共用)。"""
    oa = w.get("open_access", {}) or {}
    return _paper(
        title=w.get("title", "") or "",
        authors=[a.get("author", {}).get("display_name", "")
                 for a in w.get("authorships", [])[:6]],
        year=w.get("publication_year"),
        doi=(w.get("doi") or "").replace("https://doi.org/", "") or None,
        abstract=_reconstruct_abstract(w.get("abstract_inverted_index")),
        oa_status=oa.get("oa_status", "unknown"), oa_url=oa.get("oa_url"),
        source="OpenAlex", citations=w.get("cited_by_count"))


def search_openalex(query: str, limit: int = 10, year_from: int | None = None) -> list:
    params = {"search": query, "per-page": min(limit, 25), "mailto": "psyclaw@example.org"}
    if year_from:
        params["filter"] = f"from_publication_date:{year_from}-01-01"
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    data = _get(url)
    results = data.get("results", []) if isinstance(data, dict) else []
    return [_paper_from_oa(w) for w in results]


def _reconstruct_abstract(inv: dict | None) -> str:
    """OpenAlex 摘要是倒排索引,还原成文本。"""
    if not inv:
        return ""
    positions = []
    for word, idxs in inv.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    return " ".join(w for _, w in positions)[:1500]


# ---------------------------------------------------------------------------
# Europe PMC(心理/医学,且能直接给 OA 全文)
# ---------------------------------------------------------------------------

def search_europepmc(query: str, limit: int = 10) -> list:
    params = {"query": query, "format": "json", "pageSize": min(limit, 25),
              "resultType": "core"}
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(params)
    data = _get(url)
    out = []
    results = (data.get("resultList", {}).get("result", []) if isinstance(data, dict) else [])
    for w in results:
        is_oa = w.get("isOpenAccess") == "Y" or w.get("inEPMC") == "Y"
        out.append(_paper(
            title=w.get("title", ""),
            authors=[a.strip() for a in (w.get("authorString", "")).split(",")[:6]],
            year=int(w["pubYear"]) if w.get("pubYear", "").isdigit() else None,
            doi=w.get("doi"),
            abstract=w.get("abstractText", "")[:1500],
            oa_status="gold" if is_oa else "closed",
            source="EuropePMC",
            pmid=w.get("pmid"),
            pmcid=w.get("pmcid"),
        ))
    return out


# ---------------------------------------------------------------------------
# arXiv / 预印本(全文 PDF 直接合法可取)
# ---------------------------------------------------------------------------

def search_arxiv(query: str, limit: int = 10) -> list:
    params = {"search_query": f"all:{query}", "max_results": min(limit, 25)}
    url = "http://export.arxiv.org/api/query?" + urllib.parse.urlencode(params)
    xml = _get(url)
    if not isinstance(xml, str):
        return []
    import re
    out = []
    for entry in re.findall(r"<entry>(.*?)</entry>", xml, re.S):
        def tag(t):
            m = re.search(rf"<{t}>(.*?)</{t}>", entry, re.S)
            return (m.group(1).strip() if m else "")
        aid = tag("id").rsplit("/", 1)[-1]
        out.append(_paper(
            title=re.sub(r"\s+", " ", tag("title")),
            authors=re.findall(r"<name>(.*?)</name>", entry)[:6],
            year=tag("published")[:4] and int(tag("published")[:4]),
            abstract=re.sub(r"\s+", " ", tag("summary"))[:1500],
            oa_status="green",
            oa_url=f"https://arxiv.org/pdf/{aid}",
            source="arXiv",
            arxiv_id=aid,
        ))
    return out


# ---------------------------------------------------------------------------
# Crossref(DOI 元数据权威源;大量中文核心期刊有 DOI → 覆盖知网核心期刊那一块)
# ---------------------------------------------------------------------------

def search_crossref(query: str, limit: int = 10, year_from: int | None = None) -> list:
    params = {"query": query, "rows": min(limit, 25),
              "select": "DOI,title,author,issued,container-title,abstract"}
    if year_from:
        params["filter"] = f"from-pub-date:{year_from}-01-01"
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params)
    data = _get(url)
    items = (data.get("message", {}).get("items", []) if isinstance(data, dict) else [])
    out = []
    for it in items:
        title = (it.get("title") or [""])[0]
        if not title:
            continue
        parts = (it.get("issued", {}) or {}).get("date-parts", [[None]])
        year = parts[0][0] if parts and parts[0] else None
        authors = [f"{a.get('given', '')} {a.get('family', '')}".strip()
                   for a in it.get("author", [])[:6]]
        out.append(_paper(
            title=title, authors=[a for a in authors if a], year=year,
            doi=it.get("DOI"),
            abstract=re.sub(r"<[^>]+>", "", it.get("abstract", "") or "")[:1500],
            source="Crossref"))
    return out


# ---------------------------------------------------------------------------
# Semantic Scholar(摘要 + TL;DR + 被引数 + 引用图谱;中英覆盖广,综述神器)
# ---------------------------------------------------------------------------

def search_semantic_scholar(query: str, limit: int = 10) -> list:
    fields = "title,authors,year,abstract,externalIds,tldr,citationCount,openAccessPdf"
    url = ("https://api.semanticscholar.org/graph/v1/paper/search?"
           + urllib.parse.urlencode({"query": query, "limit": min(limit, 25), "fields": fields}))
    data = _get(url)
    out = []
    for p in (data.get("data", []) if isinstance(data, dict) else []):
        ext = p.get("externalIds") or {}
        tldr = (p.get("tldr") or {}).get("text") or ""
        abstract = p.get("abstract") or ""
        if tldr:
            abstract = f"TL;DR: {tldr}\n{abstract}".strip()
        oa = p.get("openAccessPdf") or {}
        out.append(_paper(
            title=p.get("title", "") or "",
            authors=[a.get("name", "") for a in (p.get("authors") or [])[:6]],
            year=p.get("year"), doi=ext.get("DOI"), abstract=abstract[:1500],
            oa_status="gold" if oa.get("url") else "unknown", oa_url=oa.get("url"),
            source="SemanticScholar", citations=p.get("citationCount")))
    return out


# ---------------------------------------------------------------------------
# 多源检索 + 去重(PRISMA 第一步)
# ---------------------------------------------------------------------------

DEFAULT_SOURCES = ["openalex", "crossref", "europepmc"]

# 源名同义词:模型/用户常按习惯写库名。能映射的就映射(PubMed/MEDLINE 的内容
# EuropePMC 就在索引),映射不了的在结果里**明确报出**,绝不静默丢弃。
_SOURCE_ALIASES = {
    "pubmed": "europepmc", "medline": "europepmc", "pmc": "europepmc",
    "europe_pmc": "europepmc", "europepubmedcentral": "europepmc",
    "s2": "semanticscholar", "semantic_scholar": "semanticscholar",
    "semantic scholar": "semanticscholar",
    "openalex.org": "openalex", "cross_ref": "crossref", "doi": "crossref",
    "arxiv.org": "arxiv",
}


def search(query: str, sources: list | None = None, limit: int = 10,
           year_from: int | None = None) -> dict:
    raw = []
    per_source = {}
    fn = {"openalex": lambda: search_openalex(query, limit, year_from),
          "europepmc": lambda: search_europepmc(query, limit),
          "arxiv": lambda: search_arxiv(query, limit),
          "crossref": lambda: search_crossref(query, limit, year_from),
          "semanticscholar": lambda: search_semantic_scholar(query, limit)}

    # 归一 + 分拣:不认识的源必须现形,否则「全不认识 → 0 条」与「真没论文」
    # 无法区分,调用方(尤其是模型)会误判成「没有检索能力」而放弃。
    requested = [str(s).strip().lower() for s in (sources or []) if str(s).strip()]
    resolved, unknown = [], []
    for s in requested:
        key = _SOURCE_ALIASES.get(s, s)
        if key in fn:
            if key not in resolved:
                resolved.append(key)
        else:
            unknown.append(s)
    if not resolved:                    # 一个可用源都没有 → 退回默认,别空手而归
        resolved = list(DEFAULT_SOURCES)
        if unknown:
            per_source["_note"] = (f"不认识的源 {unknown},已改用默认源 "
                                   f"{DEFAULT_SOURCES}(可用:{sorted(fn)})")
    elif unknown:
        per_source["_note"] = f"忽略不认识的源 {unknown}(可用:{sorted(fn)})"

    for s in resolved:
        try:
            hits = fn[s]()
            per_source[s] = len(hits)
            raw.extend(hits)
        except Exception as exc:  # noqa: BLE001
            per_source[s] = f"err: {exc}"
    # 去重:DOI 优先,无 DOI 则标题
    seen = {}
    for p in raw:
        key = (p["doi"] or "").lower() or p["title"].lower().strip()[:80]
        if key and key not in seen:
            seen[key] = p
    deduped = list(seen.values())
    return {"query": query, "per_source": per_source,
            "n_raw": len(raw), "n_deduped": len(deduped),
            "n_duplicates": len(raw) - len(deduped), "results": deduped}


def snowball(doi: str, direction: str = "citations", limit: int = 25) -> list:
    """引用滚雪球:从种子 DOI 沿 OpenAlex 引用网络扩展——文献综述的正道。

    direction:citations=引用了它的新文献(往前追前沿)/ references=它引的经典(往回追源头)
    / both。比关键词检索精准:一篇好综述的种子文献,其引用网络就是这个领域的地图。
    返回统一题录(去重)。任何网络异常都 fail-safe 返回已得部分。
    """
    base = "https://api.openalex.org"
    mail = "mailto=psyclaw@example.org"
    try:
        w = _get(f"{base}/works/https://doi.org/{urllib.parse.quote(doi)}?{mail}")
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(w, dict):
        return []
    n = min(max(limit, 1), 50)
    out = []
    if direction in ("citations", "both"):
        cu = w.get("cited_by_api_url")
        if cu:
            try:
                c = _get(f"{cu}&per-page={n}&{mail}")
                out += [_paper_from_oa(x) for x in
                        (c.get("results", []) if isinstance(c, dict) else [])]
            except Exception:  # noqa: BLE001
                pass
    if direction in ("references", "both"):
        refs = (w.get("referenced_works") or [])[:n]
        if refs:
            ids = "|".join(r.rsplit("/", 1)[-1] for r in refs)
            try:
                rr = _get(f"{base}/works?filter=openalex_id:{ids}&per-page={n}&{mail}")
                out += [_paper_from_oa(x) for x in
                        (rr.get("results", []) if isinstance(rr, dict) else [])]
            except Exception:  # noqa: BLE001
                pass
    seen, ded = set(), []
    for p in out:
        k = (p["doi"] or "").lower() or p["title"].lower().strip()[:80]
        if k and k not in seen:
            seen.add(k)
            ded.append(p)
    return ded


# ---------------------------------------------------------------------------
# 全文获取 —— 只走合法开放获取渠道
# ---------------------------------------------------------------------------

def unpaywall_oa(doi: str, email: str = "psyclaw@example.org") -> dict | None:
    """Unpaywall:DOI → 合法 OA 全文链接(若存在)。"""
    url = f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}?email={email}"
    try:
        data = _get(url)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict):
        return None
    best = data.get("best_oa_location")
    if not best:
        return {"is_oa": False}
    return {"is_oa": data.get("is_oa", False),
            "pdf_url": best.get("url_for_pdf"),
            "landing": best.get("url"),
            "version": best.get("version"),
            "license": best.get("license"),
            "host": best.get("host_type")}


def europepmc_fulltext(pmcid: str) -> str | None:
    """Europe PMC 全文 XML(仅 OA 子集合法可取)。返回纯文本。"""
    pmcid = pmcid if pmcid.startswith("PMC") else "PMC" + pmcid.lstrip("PMC")
    url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
    try:
        xml = _get(url)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(xml, str) or "<body" not in xml:
        return None
    import re
    body = re.search(r"<body.*?>(.*?)</body>", xml, re.S)
    text = body.group(1) if body else xml
    text = re.sub(r"<[^>]+>", " ", text)         # 去标签
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def get_fulltext(paper: dict, out_dir: str | None = None) -> dict:
    """按合规优先级取全文。paper 为 search 结果项或含 doi/pmcid/arxiv_id 的 dict。

    优先级:Europe PMC OA 全文 > Unpaywall OA PDF > arXiv PDF > 仅摘要(付费墙)。
    返回 {status, channel, text?, pdf_url?, note}。
    """
    from pathlib import Path

    # 1. Europe PMC 全文(OA,直接给正文文本)
    pmcid = paper.get("pmcid")
    if pmcid:
        text = europepmc_fulltext(pmcid)
        if text and len(text) > 500:
            saved = _save_text(text, paper, out_dir)
            return {"status": "fulltext", "channel": "Europe PMC OA",
                    "chars": len(text), "saved": saved,
                    "text": text[:3000] + ("…" if len(text) > 3000 else ""),
                    "note": "开放获取全文(合法)"}

    # 2. Unpaywall OA PDF(合法链接)
    doi = paper.get("doi")
    if doi:
        oa = unpaywall_oa(doi)
        if oa and oa.get("is_oa") and (oa.get("pdf_url") or oa.get("landing")):
            return {"status": "oa_pdf", "channel": "Unpaywall OA",
                    "pdf_url": oa.get("pdf_url") or oa.get("landing"),
                    "license": oa.get("license"), "version": oa.get("version"),
                    "note": "合法 OA PDF 链接,可直接下载;不绕过任何付费墙"}

    # 3. arXiv / 预印本 PDF
    if paper.get("arxiv_id"):
        return {"status": "oa_pdf", "channel": "arXiv",
                "pdf_url": f"https://arxiv.org/pdf/{paper['arxiv_id']}",
                "note": "预印本全文 PDF(合法)"}
    if paper.get("oa_url") and paper.get("oa_status") in ("gold", "green", "hybrid", "bronze"):
        return {"status": "oa_pdf", "channel": f"OA({paper['oa_status']})",
                "pdf_url": paper["oa_url"], "note": "开放获取链接"}

    # 4. 机构权限(合法):LibKey 机构订阅 / EZProxy 改写链接(用户浏览器 SSO 会话)
    if doi:
        try:
            from psyclaw.psych import institution
            inst = institution.institutional_access(doi)
            if inst:
                return {"status": "institutional", "channel": inst["channel"],
                        "url": inst["url"], "note": inst["note"]}
        except Exception:  # noqa: BLE001
            pass

    # 5. 付费墙且无机构权限 —— 只给摘要,明确不绕过
    return {"status": "closed", "channel": "paywalled",
            "abstract": paper.get("abstract", ""),
            "note": ("该文献为付费墙/非开放获取。PsyClaw 不绕过付费墙。"
                     "配置机构权限:psyclaw auth --set(EZProxy/LibKey);"
                     "或若你的 Zotero 已存有该 PDF,用 `psyclaw lit --zotero <DOI>` 取你已购的全文。")}


def _save_text(text: str, paper: dict, out_dir: str | None):
    if not out_dir:
        return None
    from pathlib import Path
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    fp = _dedup_path(d / (pdf_filename(paper)[:-4] + ".txt"))   # feat-109:同一命名方案
    fp.write_text(text, encoding="utf-8")
    return str(fp)


# ---------------------------------------------------------------------------
# PDF 下载与规范命名(feat-109)——goal 实测三错:宣称可下载却不下载 /
# 落盘名无作者年份标题 / 裸 DOI 无元数据可命名。
# ---------------------------------------------------------------------------

_FNAME_BAD = re.compile(r'[\\/:*?"<>|\s]+')


def pdf_filename(paper: dict) -> str:
    """题录 → 规范文件名:<一作姓>_<年份>_<标题前若干词>.pdf(CJK 原样保留)。"""
    authors = paper.get("authors") or []
    first = (authors[0] if authors else "").strip()
    if first:
        toks = [t.strip(".") for t in first.replace(",", " ").split() if t.strip(".")]
        if _has_cjk(first) or not toks:
            surname = first
        else:
            # 末 token 通常是姓;但「Chen Z.」式单字母缩写在末尾时取首 token
            # (实测 Z_2026 bug;Wu/Li 等双字母真姓不受影响)
            surname = toks[-1] if len(toks[-1]) > 1 else toks[0]
    else:
        surname = "UnknownAuthor"
    year = str(paper.get("year") or "n.d.")
    title = (paper.get("title") or "untitled").strip()
    words = title.split()
    short = "".join(title[:24].split()) if _has_cjk(title) else "-".join(words[:7])
    name = f"{surname}_{year}_{short}"
    name = _FNAME_BAD.sub("-", name).strip("-._")[:90]
    return f"{name}.pdf"


def _has_cjk(s: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in s or "")


def _dedup_path(fp):
    """同名文件已存在 → 追加 -2/-3 …,绝不静默覆盖。"""
    if not fp.exists():
        return fp
    stem, suffix, parent = fp.stem, fp.suffix, fp.parent
    for i in range(2, 100):
        cand = parent / f"{stem}-{i}{suffix}"
        if not cand.exists():
            return cand
    return parent / f"{stem}-dup{suffix}"


def paper_from_doi(doi: str) -> dict | None:
    """裸 DOI → 题录(OpenAlex),供命名用;取不到返回 None(不阻塞下载)。"""
    try:
        data = _get("https://api.openalex.org/works/doi:"
                    + urllib.parse.quote(doi) + "?mailto=psyclaw@example.org")
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict) or not data.get("title"):
        return None
    return _paper(
        title=data.get("title", ""),
        authors=[a.get("author", {}).get("display_name", "")
                 for a in data.get("authorships", [])[:5]],
        year=data.get("publication_year"), doi=doi, source="OpenAlex")


# PDF 直下用浏览器式 UA:多家出版社对工具 UA 一律 403(实测 annualreviews),
# 目标是**合法 OA** 内容,换 UA 不涉付费墙。
_PDF_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def _fetch_pdf_bytes(url: str) -> tuple[bytes | None, str]:
    """取一个候选链接的 PDF 字节;返回 (bytes|None, 失败原因)。TLS 瞬断重试一次。"""
    req = urllib.request.Request(url, headers={"User-Agent": _PDF_UA,
                                               "Accept": "application/pdf,*/*"})
    last = ""
    for _attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                head = r.read(5)
                if not head.startswith(b"%PDF"):
                    return None, "返回的不是 PDF(落地页/HTML)"
                return head + r.read(), ""
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
            if "EOF occurred" not in last and "handshake" not in last:
                break              # 非 TLS 瞬断不重试
    if ("EOF occurred" in last or "handshake" in last):
        import ssl
        if "LibreSSL" in ssl.OPENSSL_VERSION:   # 实测:系统 Py3.9 老栈连不上部分出版社
            last += "(本机 Python 用 LibreSSL 老 TLS 栈——建议在 Python 3.12/OpenSSL 环境重试)"
    return None, f"下载失败:{last}"


def download_pdf(url: str, dest_dir: str, paper: dict) -> dict:
    """把 OA PDF 真正下载到 dest_dir(规范命名)。诚实校验:响应必须是 PDF
    (%PDF 魔数),落地页/HTML 一律如实报失败,绝不把网页存成 .pdf。"""
    from pathlib import Path
    body, why = _fetch_pdf_bytes(url)
    if body is None:
        return {"ok": False, "url": url,
                "note": f"{why}——已放弃保存,可用浏览器打开链接手动下载"}
    d = Path(dest_dir)
    d.mkdir(parents=True, exist_ok=True)
    fp = _dedup_path(d / pdf_filename(paper))
    fp.write_bytes(body)
    return {"ok": True, "path": str(fp), "bytes": len(body), "url": url}


def _pdf_candidates(paper: dict, res: dict) -> list[str]:
    """按可信度排 PDF 候选链接:unpaywall pdf → EuropePMC 渲染 → OpenAlex oa_url
    → arXiv。逐个试到 %PDF 为止(单一链接失败率高,实测 5/7 可救)。"""
    cands: list[str] = []
    if res.get("pdf_url"):
        cands.append(res["pdf_url"])
    if res.get("url"):                 # 机构权限链接(LibKey 全文直链 / EZProxy 入口 / IP 直连)
        cands.append(res["url"])
    pmcid = paper.get("pmcid")
    if pmcid:
        pid = pmcid if str(pmcid).startswith("PMC") else f"PMC{pmcid}"
        cands.append("https://europepmc.org/backend/ptpmcrender.fcgi"
                     f"?accid={pid}&blobtype=pdf")
    if paper.get("oa_url"):
        cands.append(paper["oa_url"])
    if paper.get("arxiv_id"):
        cands.append(f"https://arxiv.org/pdf/{paper['arxiv_id']}")
    seen: set[str] = set()
    return [c for c in cands if c and not (c in seen or seen.add(c))]


def fetch_and_save(paper: dict, out_dir: str) -> dict:
    """取全文并**真正落盘**:OA PDF 下载为规范命名 .pdf;EuropePMC 文本存 .txt。

    候选链接依次尝试,第一个真 PDF 落盘;全失败则逐条原因如实呈报。
    返回 get_fulltext 的结果并附 {downloaded: {ok, path?, note?, tried}}。
    """
    res = get_fulltext(paper, out_dir=out_dir)
    # OA 与机构权限都真下载:OA 走合法开放链接;机构权限走 LibKey 全文直链 / IP 授权直连。
    # EZProxy 这类需浏览器 SSO 会话的链接 urllib 下不了(会拿到登录页 HTML,download_pdf
    # 靠 %PDF 魔数如实报失败),此时回执带 browser_hint 引导用已登录浏览器打开(或 --via-bridge)。
    if res.get("status") in ("oa_pdf", "institutional"):
        meta = paper if paper.get("title") else (paper_from_doi(paper.get("doi") or "")
                                                 or paper)
        notes = []
        for url in _pdf_candidates(paper, res):
            dl = download_pdf(url, out_dir, meta)
            if dl.get("ok"):
                dl["tried"] = len(notes) + 1
                res["downloaded"] = dl
                return res
            notes.append(f"{url[:60]}: {dl.get('note', '')[:60]}")
        failed = {"ok": False, "tried": len(notes),
                  "note": " | ".join(notes) or "无候选链接"}
        if res.get("status") == "institutional" and res.get("url"):
            failed["browser_hint"] = ("机构权限链接可能需浏览器 SSO 会话——"
                                      f"用已登录机构的浏览器打开:{res['url']}")
        res["downloaded"] = failed
    return res
