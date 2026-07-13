"""psyclaw check — 投稿前一键质检(易用性:五件套不再要用户自己记得跑)。

一条命令聚合全部适用检查,一屏汇总 ✓/✗/⚠:
  ① JARS 检查单(缺失数据处理/剔除信息等,APA 2018)
  ② 引用保真(文内引用逐条溯源到检索语料;--journal 附引用风格核对 + 退稿红线自查)
  ③ 复现溯源(outputs/ 下生成脚本的 <产物>.provenance.json 齐不齐)
  ④ KG 关系溯源(建了图才查;citation 边孤儿=疑似杜撰关系)

collect 纯聚合(每项独立 fail-safe,一项炸不拖累其余);单项深查仍用各自命令
(jars / cite-check / provenance / kg verify)。
"""

from __future__ import annotations

from pathlib import Path


def _item(name: str, status: str, detail: str, fix: str = "") -> dict:
    # status: pass | fail | manual | absent
    return {"name": name, "status": status, "detail": detail, "fix": fix}


def run_check(draft: str | None = None, journal: str | None = None,
              project_dir: str = ".", research_type: str = "quant") -> dict:
    """跑全部适用检查。返回 {items, n_fail, passed, journal}。"""
    project = Path(project_dir)
    items: list[dict] = []

    draft_p = Path(draft) if draft else (project / "outputs" / "report.md")
    draft_text = ""
    if draft_p.exists():
        try:
            draft_text = draft_p.read_text(encoding="utf-8")
        except OSError:
            pass

    # ① JARS
    if draft_text:
        try:
            from psyclaw.output.jars import check_draft
            r = check_draft(draft_text, research_type)
            if r["passed"]:
                items.append(_item("JARS 检查单", "pass",
                                   f"{r['n_present']}/{r['n_total']} 项已报告,无阻断缺失"))
            else:
                miss = "; ".join(b["label"] for b in r["blocking"][:3])
                blocks = [f["label"] for f in r.get("integrity") or []
                          if f["severity"] == "block"]
                if blocks:              # feat-096:诚信启发式阻断一并点名
                    miss = "; ".join(filter(None, [miss, *blocks[:2]]))
                n_block = r["n_blocking"] + r.get("n_integrity_block", 0)
                items.append(_item("JARS 检查单", "fail",
                                   f"阻断缺失 {n_block} 项:{miss}",
                                   f"psyclaw jars \"{draft_p}\" 看修复建议"))
        except Exception as exc:  # noqa: BLE001
            items.append(_item("JARS 检查单", "manual", f"检查失败:{exc}"))
    else:
        items.append(_item("JARS 检查单", "absent",
                           f"无稿件({draft_p});psyclaw check <稿件.md> 指定"))

    # ② 引用保真(+期刊风格)
    if draft_text:
        try:
            from psyclaw.psych.citations import run_citation_audit
            a = run_citation_audit(str(draft_p), project_dir=project_dir,
                                   journal=journal)
            if a["orphan_n"]:
                orphans = "; ".join(o["raw"] for o in a["orphan"][:3])
                items.append(_item("引用保真", "fail",
                                   f"孤儿引用 {a['orphan_n']} 条(疑似杜撰):{orphans}",
                                   "删除或先 psyclaw lit 补检索"))
            elif a["manual_review"]:
                items.append(_item("引用保真", "manual", a["method"]))
            else:
                items.append(_item("引用保真", "pass",
                                   f"{a['cited_n']} 条文内引用均可溯源"))
            if a.get("journal"):
                ok = a.get("citation_style_ok")
                items.append(_item(
                    f"期刊风格({a['journal'][:24]})",
                    "pass" if ok else "fail",
                    f"期望 {a.get('citation_format_expected')} / "
                    f"实测 {a.get('citation_format_detected')}",
                    "" if ok else "按期刊引用风格调整(psyclaw journal 看画像)"))
        except Exception as exc:  # noqa: BLE001
            items.append(_item("引用保真", "manual", f"检查失败:{exc}"))

    # ③ 复现溯源(outputs/ 生成脚本)
    outputs = project / "outputs"
    scripts = sorted(outputs.glob("*.py")) if outputs.is_dir() else []
    if scripts:
        import json
        for s in scripts:
            side = s.with_suffix(s.suffix + ".provenance.json")
            label = f"复现溯源({s.name})"
            if not side.exists():
                items.append(_item(label, "fail", "缺 provenance 包",
                                   f"psyclaw provenance \"{s}\""))
                continue
            try:
                prov = json.loads(side.read_text(encoding="utf-8"))
                ok = prov.get("provenance_complete") is True
                items.append(_item(label, "pass" if ok else "fail",
                                   "代码+环境+说明齐备" if ok else "溯源不完整",
                                   "" if ok else f"psyclaw provenance \"{s}\" 重新生成"))
            except Exception:  # noqa: BLE001
                items.append(_item(label, "fail", "provenance 包不可解析"))

    # ④ KG 关系溯源(建了图才查)
    if (project / ".psyclaw" / "kg" / "graph.db").exists():
        try:
            from psyclaw.kg import KnowledgeGraph
            v = KnowledgeGraph(project_dir).verify(project_dir)
            if v.get("manual_review"):
                items.append(_item("KG 关系溯源", "manual",
                                   v.get("note", "无检索语料,需人工核")))
            elif v["citation_edges"] == 0:
                items.append(_item("KG 关系溯源", "manual", "无 citation 边可核"))
            elif v["no_orphan_relations"]:
                items.append(_item("KG 关系溯源", "pass",
                                   f"{v['grounded']}/{v['citation_edges']} 条关系边溯源命中"))
            else:
                items.append(_item("KG 关系溯源", "fail",
                                   f"孤儿关系 {len(v['orphans'])} 条(疑似杜撰)",
                                   "psyclaw kg verify 看明细"))
        except Exception as exc:  # noqa: BLE001
            items.append(_item("KG 关系溯源", "manual", f"检查失败:{exc}"))

    n_fail = sum(1 for i in items if i["status"] == "fail")
    return {"items": items, "n_fail": n_fail,
            "passed": n_fail == 0, "journal": journal,
            "draft": str(draft_p) if draft_text else None}


_MARKS = {"pass": ("✓", "ok"), "fail": ("✗", "err"),
          "manual": ("⚠", "warn"), "absent": ("·", "dim")}


def print_check(res: dict) -> None:
    from psyclaw import ui
    print(ui.title("psyclaw check — 一键质检")
          + ui.dim(f"  {res.get('draft') or '(无稿件,仅项目级检查)'}"))
    for it in res["items"]:
        mark, style = _MARKS.get(it["status"], ("·", "dim"))
        painter = getattr(ui, style)
        print(f"  {painter(mark)} {it['name']:<22} {it['detail']}")
        if it["fix"]:
            print(ui.dim(f"      ↳ {it['fix']}"))
    print()
    if res["passed"]:
        print(ui.ok(f"  ✓ 全部通过({len(res['items'])} 项;⚠ 项需人工过目)"))
    else:
        print(ui.err(f"  ✗ {res['n_fail']} 项未过 — 修复后重跑 psyclaw check"))
