"""psyclaw lit — 文献检索 + 全文获取的命令层(PRISMA 计数)。"""

from __future__ import annotations

import json
from pathlib import Path


def lit_cli(query: str, sources: str = "openalex,europepmc", limit: int = 10,
            year_from: int | None = None, fulltext_doi: str | None = None,
            zotero_doi: str | None = None, synthesize: bool = False,
            project_dir: str = ".") -> int:
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

    # PRISMA 计数落盘(对接 LIT.prisma 质量检查)
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

    # 检索结果缓存(供 `psyclaw research` ① 文献阶段据真实题录合成综述)
    (notes / "lit_search.json").write_text(
        json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    print(ui.dim(f"检索结果缓存 → {notes / 'lit_search.json'}"
                 "(下次 psyclaw research 将据此合成有据综述)"))

    if synthesize:
        _synthesize_review(query, r, project_dir, ui)
    else:
        print(ui.dim("一键生成结构化综述:加 --synthesize(据上述真实命中合成)。"))
    return 0


def _synthesize_review(query: str, search_result: dict, project_dir: str, ui) -> None:
    """据检索命中一键合成结构化综述 → notes/lit_review.md + evidence_map.json。"""
    from psyclaw import config as cfg
    from psyclaw.providers import get_provider
    from psyclaw.psych import synthesize

    notes = Path(project_dir) / "notes"
    if not search_result.get("results"):
        print(ui.warn("  无检索命中,跳过综述合成。"))
        return
    provider = get_provider(cfg.load_config())
    print(ui.dim(f"  合成综述(provider={provider.name})…"))
    syn = synthesize.synthesize_review(query, search_result, provider=provider)
    (notes / "lit_review.md").write_text(syn["markdown"], encoding="utf-8")
    (notes / "evidence_map.json").write_text(
        json.dumps(syn["evidence_map"], ensure_ascii=False, indent=2),
        encoding="utf-8")
    tag = ui.ok("有据叙事") if syn["grounded"] else ui.warn("确定性骨架(LLM 未接入)")
    print(ui.ok(f"✓ 结构化综述 → {notes / 'lit_review.md'}") + f" · {tag}")
    print(ui.dim(f"  证据图谱 → {notes / 'evidence_map.json'}"
                 f"(构念 {len(syn['evidence_map']['themes'])} · "
                 f"参考文献 {syn['n_papers']})"))


def lit_cli_argv(argv: list[str], project_dir: str = ".") -> int:
    """薄入口(REPL `/lit` 复用):lit <检索式> [--synthesize] [--limit N]
    [--sources s1,s2] [--year-from Y] [--fulltext DOI] [--zotero DOI]。"""
    if argv and argv[0] == "plan":         # feat-103:/lit plan <主题> [--target N]
        topic_parts, n_target = [], 20
        j = 1
        while j < len(argv):
            if argv[j] == "--target" and j + 1 < len(argv):
                j += 1
                try:
                    n_target = int(argv[j])
                except ValueError:
                    n_target = 20
            elif not argv[j].startswith("-"):
                topic_parts.append(argv[j])
            j += 1
        import argparse as _ap
        from psyclaw.cli import cmd_lit
        return cmd_lit(_ap.Namespace(query=" ".join(topic_parts), plan=True,
                                     limit=n_target, sources="", year_from=None,
                                     fulltext=None, zotero=None, synthesize=False))
    if argv and argv[0] in ("import", "matrix"):   # feat-104:/lit import|matrix
        import argparse as _ap
        from psyclaw.cli import cmd_lit
        rest = [a for a in argv[1:] if not a.startswith("-")]
        return cmd_lit(_ap.Namespace(
            query=" ".join(rest) if argv[0] == "matrix" else "",
            plan=False, matrix=argv[0] == "matrix",
            import_file=(rest[0] if rest else None) if argv[0] == "import" else None,
            limit=10, sources="", year_from=None, fulltext=None, zotero=None,
            synthesize=False))
    query_parts: list[str] = []
    sources, limit, year_from = "openalex,europepmc", 10, None
    fulltext_doi = zotero_doi = None
    synthesize = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--synthesize", "-s"):
            synthesize = True
        elif a == "--limit" and i + 1 < len(argv):
            i += 1
            try:
                limit = int(argv[i])
            except ValueError:
                limit = 10
        elif a == "--sources" and i + 1 < len(argv):
            i += 1
            sources = argv[i]
        elif a == "--year-from" and i + 1 < len(argv):
            i += 1
            try:
                year_from = int(argv[i])
            except ValueError:
                year_from = None
        elif a == "--fulltext" and i + 1 < len(argv):
            i += 1
            fulltext_doi = argv[i]
        elif a == "--zotero" and i + 1 < len(argv):
            i += 1
            zotero_doi = argv[i]
        elif not a.startswith("-"):
            query_parts.append(a)
        i += 1
    return lit_cli(query=" ".join(query_parts), sources=sources, limit=limit,
                   year_from=year_from, fulltext_doi=fulltext_doi,
                   zotero_doi=zotero_doi, synthesize=synthesize,
                   project_dir=project_dir)


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
