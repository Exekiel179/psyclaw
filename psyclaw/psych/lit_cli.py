"""psyclaw lit — 文献检索 + 全文获取的命令层(PRISMA 计数)。"""

from __future__ import annotations

from pathlib import Path


def lit_cli(query: str, sources: str = "openalex,europepmc", limit: int = 10,
            year_from: int | None = None, fulltext_doi: str | None = None,
            zotero_doi: str | None = None, project_dir: str = ".") -> int:
    from psyclaw import ui
    from psyclaw.psych import litsearch, zotero_client

    # 模式 A:取某 DOI 的全文(合规优先级)
    if fulltext_doi:
        print(ui.title(f"全文获取 — {fulltext_doi}"))
        print(ui.rule())
        res = litsearch.get_fulltext({"doi": fulltext_doi},
                                     out_dir=str(Path(project_dir) / "outputs" / "fulltext"))
        _print_fulltext(res, ui)
        return 0

    # 模式 B:从你自己的 Zotero 文库取全文(付费墙文献的合法来源)
    if zotero_doi:
        print(ui.title(f"Zotero 文库全文 — {zotero_doi}"))
        print(ui.rule())
        res = zotero_client.get_fulltext_by_doi(zotero_doi)
        if res.get("status") == "fulltext":
            print(ui.ok(f"✓ 来自{res['channel']}:{res['title']}({res['chars']} 字符)"))
            print(ui.panel("全文(前 3000 字符)", res["text"]))
        else:
            print(ui.warn(f"  {res.get('note', res.get('status'))}"))
        return 0

    # 模式 C:检索(PRISMA 第一步)
    print(ui.title(f"文献检索 — {query}"))
    print(ui.rule())
    src = [s.strip() for s in sources.split(",") if s.strip()]
    r = litsearch.search(query, sources=src, limit=limit, year_from=year_from)
    print(ui.dim(f"来源 {r['per_source']} · 原始 {r['n_raw']} · "
                 f"去重后 {r['n_deduped']}(去掉 {r['n_duplicates']} 条重复)"))
    print()
    oa_n = 0
    for i, p in enumerate(r["results"][:limit], 1):
        oa = p["oa_status"]
        is_oa = oa in ("gold", "green", "hybrid", "bronze")
        oa_n += is_oa
        badge = ui.ok(f"OA:{oa}") if is_oa else ui.dim(f"closed")
        au = ", ".join(p["authors"][:3]) + (" 等" if len(p["authors"]) > 3 else "")
        print(f"{ui.accent(str(i)+'.')} {p['title'][:88]}")
        print(f"   {ui.dim(au)} ({p.get('year','?')}) · {badge} · {p['source']}"
              + (f" · doi:{p['doi']}" if p["doi"] else ""))
    print(ui.dim(f"\n开放获取 {oa_n}/{len(r['results'][:limit])} 篇可直接取全文"))
    print(ui.dim("取全文:psyclaw lit --fulltext <DOI>(走合法 OA);"
                 "付费墙的用 --zotero <DOI> 从你自己文库取。"))

    # PRISMA 计数落盘(对接 LIT.prisma 门禁)
    notes = Path(project_dir) / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    (notes / "prisma_search.md").write_text(
        f"# PRISMA 检索记录\n\n- 检索式: {query}\n- 来源: {r['per_source']}\n"
        f"- 识别(identification): {r['n_raw']} 条\n"
        f"- 去重后: {r['n_deduped']} 条(去除 {r['n_duplicates']} 重复)\n"
        f"- 开放获取可得全文: {oa_n} 条\n"
        f"- 下一步(screening): 按纳入排除标准人工筛选,记录排除数与原因\n",
        encoding="utf-8")
    print(ui.dim(f"PRISMA 检索记录 → {notes / 'prisma_search.md'}"))
    return 0


def _print_fulltext(res: dict, ui) -> None:
    st = res["status"]
    if st == "fulltext":
        print(ui.ok(f"✓ {res['channel']} — {res['chars']} 字符 · {res['note']}"))
        if res.get("saved"):
            print(ui.dim(f"  全文已存:{res['saved']}"))
        print(ui.panel("全文(前 3000 字符)", res["text"]))
    elif st == "oa_pdf":
        print(ui.ok(f"✓ {res['channel']} — 合法 OA PDF"))
        print(f"  {ui.accent(res['pdf_url'])}")
        print(ui.dim(f"  {res['note']}"
                     + (f" · 许可:{res.get('license')}" if res.get('license') else "")))
    elif st == "institutional":
        print(ui.ok(f"✓ {res['channel']} — 机构权限入口(合法)"))
        print(f"  {ui.accent(res['url'])}")
        print(ui.dim(f"  {res['note']}"))
    else:  # closed
        print(ui.warn("⚠ 付费墙 / 非开放获取"))
        if res.get("abstract"):
            print(ui.panel("摘要(全文不可合法免费获取)", res["abstract"][:1500]))
        print(ui.dim("  " + res["note"]))
