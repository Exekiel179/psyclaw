"""psyclaw lit — 文献检索 + 全文获取的命令层(PRISMA 计数)。"""

from __future__ import annotations

import json
from pathlib import Path


def lit_cli(query: str, sources: str = "openalex,europepmc", limit: int = 10,
            year_from: int | None = None, fulltext_doi: str | None = None,
            zotero_doi: str | None = None, synthesize: bool = False,
            download: bool = False, project_dir: str = ".",
            bridge: bool | None = None) -> int:
    from psyclaw import ui
    from psyclaw.psych import litsearch, zotero_client

    pdf_dir = str(Path(project_dir) / "outputs" / "pdfs")

    # 模式 A:取某 DOI 的全文(合规优先级;feat-109:OA PDF 真下载+规范命名)
    if fulltext_doi:
        print(ui.title(f"全文获取 — {fulltext_doi}"))
        print(ui.rule())
        res = litsearch.fetch_and_save({"doi": fulltext_doi}, out_dir=pdf_dir)
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
    if download:                          # feat-109:OA PDF 批量真下载,规范命名落盘
        print()
        got = failed = 0
        for p in r["results"][:limit]:
            if p.get("oa_status") not in ("gold", "green", "hybrid", "bronze") \
                    and not p.get("arxiv_id") and not p.get("pmcid"):
                continue
            res = litsearch.fetch_and_save(p, out_dir=pdf_dir)
            dl = res.get("downloaded") or {}
            if dl.get("ok"):
                got += 1
                print(ui.ok(f"  ⬇ {Path(dl['path']).name}"
                            f"({dl['bytes'] // 1024} KB)"))
            elif res.get("status") == "fulltext" and res.get("saved"):
                got += 1
                print(ui.ok(f"  ⬇ {Path(res['saved']).name}(全文文本)"))
            else:
                failed += 1
                print(ui.warn(f"  ✗ {p['title'][:46]}:"
                              f"{(dl.get('note') or res.get('note', ''))[:60]}"))
        print(ui.dim(f"  下载 {got} 篇 → {pdf_dir};失败 {failed} 篇(如实标注,不假装)"))
    else:
        print(ui.dim("取全文:psyclaw lit --fulltext <DOI>(走合法 OA);"
                     "--download 批量下载本次 OA 命中;付费墙用 --zotero <DOI>。"))

    # 自动机构库桥接:公开 API 检不到知网/万方,驱动 WebBridge 补检并合并进结果与缓存
    bridge_ran = _maybe_bridge(query, r, bridge, ui, limit)

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

    # 机构库桥接的所有提示(可用即自动跑 / 不可用给一步开启指引)由 _maybe_bridge 内部负责;
    # bridge_ran 为 False 仅当用户显式 --no-bridge——此时不再劝。

    if synthesize:
        _synthesize_review(query, r, project_dir, ui)
    else:
        print(ui.dim("一键生成结构化综述:加 --synthesize(据上述真实命中合成)。"))
    return 0


def _has_cjk(s: str) -> bool:
    return any("一" <= c <= "鿿" for c in (s or ""))


def _maybe_bridge(query: str, r: dict, bridge: bool | None, ui, limit: int) -> bool:
    """自动驱动 WebBridge 进机构库补检并合并进 r。返回是否真的跑了桥接。

    bridge:None=自动(可用才跑,不可用静默降级)· True=强制(不可用也报原因)· False=关闭。
    全程 fail-safe——litbridge 内部不抛,这里任何异常也吞掉,绝不中断 lit。
    """
    if bridge is False:
        return False
    try:
        from psyclaw.psych import litbridge
        ok, reason = litbridge.bridge_available()
        if not ok:
            # 默认(auto)与强制(True)都精确指路:差哪一步、一条命令开启,而非泛化提示
            print(ui.warn(institutional_hint(query)))
            print(ui.dim(f"  一步开启机构库自动补检:{litbridge.enable_command(reason)}"
                         f"({reason};开启后 lit 默认自动进知网,无需 --bridge)"))
            return True                        # 已就桥接给足指引,外层不再重复
        db = litbridge.DEFAULT_DB              # 目前默认知网(中文覆盖最差处)
        name = litbridge._DB_PROFILES[db]["name"]
        print(ui.dim(f"正在驱动浏览器进{name}检索(WebBridge,复用你的登录态,可能开新标签)…"))
        out = litbridge.bridge_search(query, db=db, limit=limit)
        if not out["ok"]:
            print(ui.warn(f"  {name}桥接未成功:{out['reason']}"))
            return True
        before = {(x.get("doi") or "").lower() or (x.get("title") or "").lower().strip()[:80]
                  for x in r["results"]}
        merged, added = litbridge.merge_results(r["results"], out["records"])
        r["results"] = merged
        r["n_deduped"] = len(merged)
        r["n_raw"] = r.get("n_raw", 0) + len(out["records"])   # PRISMA identification 计入桥命中
        r.setdefault("per_source", {})[name] = len(out["records"])
        if out["records"]:
            print(ui.ok(f"  ✓ {name}命中 {len(out['records'])} 条,新增 {added} 条(合并去重后共 {len(merged)}):"))
            shown = 0
            for p in out["records"]:
                k = (p.get("doi") or "").lower() or (p.get("title") or "").lower().strip()[:80]
                is_new = k not in before
                au = ", ".join(p["authors"][:3]) + (" 等" if len(p["authors"]) > 3 else "")
                tag = ui.accent("＋") if is_new else ui.dim("·")
                print(f"   {tag} {p['title'][:80]} {ui.dim(au)} ({p.get('year') or '?'}) · {name}")
                shown += 1
                if shown >= limit:
                    break
        else:
            print(ui.warn(f"  {out['reason'] or f'{name}未抽取到题录'}"))
        return True
    except Exception:  # noqa: BLE001 — 桥接任何异常都不影响 lit 主流程
        return False


def institutional_hint(query: str) -> str:
    """检索后的机构库补全提示。纯函数,可单测。

    lit 只打公开 API(OpenAlex/EuropePMC)——中文文献大量在知网/万方/维普,英文付费
    文献也检不全。用户实测:搜「公正世界信念」以为会自动调 Kimi WebBridge,其实 lit
    与 webbridge 是两条独立通道。主动指路:机构库检索走 lit --plan 生成桥接分步 +
    浏览器桥(Kimi WebBridge)进真实库检索。中文主题时话更重(公开 API 覆盖尤其差)。
    """
    if _has_cjk(query):
        return ("覆盖提醒:公开 API(OpenAlex/EuropePMC)检不到知网/万方/维普的中文文献。"
                "要机构库全量检索,走浏览器桥:`psyclaw lit \"%s\" --plan` 生成桥接分步 → "
                "`psyclaw webbridge`(Kimi WebBridge 驱动真实浏览器进知网检索)。" % query.strip())
    return ("覆盖提醒:公开 API 检不全付费墙/机构库文献。要更全,走浏览器桥:"
            "`psyclaw lit --plan` 生成桥接分步 → `psyclaw webbridge`(进 WoS/Scopus 等)。")


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
    download = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--synthesize", "-s"):
            synthesize = True
        elif a in ("--download", "-d"):
            download = True
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
                   download=download, project_dir=project_dir)


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
        dl = res.get("downloaded") or {}     # feat-109:下载结果如实呈报
        if dl.get("ok"):
            print(ui.ok(f"  ⬇ 已下载:{dl['path']}({dl['bytes'] // 1024} KB)"))
        elif dl:
            print(ui.warn(f"  ✗ 未能保存:{dl.get('note', '')}"))
    elif st == "institutional":
        print(ui.ok(f"✓ {res['channel']} — 机构权限入口(合法)"))
        print(f"  {ui.accent(res['url'])}")
        print(ui.dim(f"  {res['note']}"))
    else:  # closed
        print(ui.warn("⚠ 付费墙 / 非开放获取"))
        if res.get("abstract"):
            print(ui.panel("摘要(全文不可合法免费获取)", res["abstract"][:1500]))
        print(ui.dim("  " + res["note"]))
