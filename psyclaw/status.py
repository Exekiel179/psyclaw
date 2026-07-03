"""psyclaw status — 一屏聚合项目态势(易用性:状态不再散落 8 个文件)。

聚合:研究目标 · 澄清进度 · auto-loop 回路状态 · 等人决策(直接打印 decision_request 内容,
不让用户去开文件)· 被阻塞项 · 最近产物 · 总验收 · 下一步建议(复用 discover_backlog)。

collect_status 纯采集(返回 dict,可单测);print_status 只负责渲染。全只读,不改任何状态。
"""

from __future__ import annotations

from pathlib import Path

_RECENT_N = 5


def _read(p: Path, limit: int = 2000) -> str:
    try:
        return p.read_text(encoding="utf-8")[:limit]
    except OSError:
        return ""


def collect_status(project_dir: str = ".") -> dict:
    """采集项目态势(只读,各块独立 fail-safe:一块坏了不影响其余)。"""
    project = Path(project_dir)
    st: dict = {"project": str(project.resolve())}

    # 研究目标
    try:
        from psyclaw.tasks import get_goal
        st["goal"] = get_goal(project_dir) or ""
    except Exception:  # noqa: BLE001
        st["goal"] = ""

    # 澄清进度
    try:
        from psyclaw.psych.clarify import check_card
        card = check_card(project_dir)
        st["clarify"] = {"exists": card.get("exists", False),
                         "resolved": card.get("resolved", 0),
                         "total": card.get("total", 0),
                         "unresolved": len(card.get("unresolved", []))}
    except Exception:  # noqa: BLE001
        st["clarify"] = {"exists": False, "resolved": 0, "total": 0, "unresolved": 0}

    # auto-loop 回路状态
    try:
        from psyclaw.autoloop import load_state
        s = load_state(project_dir)
        st["loop"] = {"iteration": s.get("iteration", 0),
                      "completed": list(s.get("completed_actions", [])),
                      "skipped": list(s.get("skipped", []))}
    except Exception:  # noqa: BLE001
        st["loop"] = {"iteration": 0, "completed": [], "skipped": []}

    # 等人决策(内容直接带出)/ 被阻塞
    notes = project / "notes"
    dr = notes / "decision_request.md"
    st["decision_request"] = _read(dr) if dr.exists() else ""
    bl = notes / "blocked.md"
    blocked = _read(bl, 4000)
    # 只留最后一条(## 开头的最后一段)
    if blocked:
        parts = [p for p in blocked.split("\n## ") if p.strip()]
        st["last_blocked"] = ("## " + parts[-1].strip()) if parts else blocked.strip()
    else:
        st["last_blocked"] = ""

    # 总验收
    st["workflow_verdict"] = ""
    ws = notes / "workflow_summary.json"
    if ws.exists():
        try:
            import json
            summary = json.loads(ws.read_text(encoding="utf-8"))
            v = summary.get("verdict", {})
            st["workflow_verdict"] = (
                f"{summary.get('workflow', '?')}:"
                + ("✓ 通过" if v.get("overall_passed") else
                   f"✗ 未过({'; '.join(v.get('reasons', [])) or '?'})"))
        except Exception:  # noqa: BLE001
            pass

    # 最近产物(notes/ + outputs/ 按修改时间)
    recent: list[tuple[float, str]] = []
    for d in (notes, project / "outputs"):
        if d.is_dir():
            for p in d.iterdir():
                if p.is_file():
                    try:
                        recent.append((p.stat().st_mtime, str(p.relative_to(project))))
                    except (OSError, ValueError):
                        pass
    recent.sort(reverse=True)
    st["recent_artifacts"] = [name for _, name in recent[:_RECENT_N]]

    # 下一步建议(复用 auto-loop 的感知)
    try:
        from psyclaw.autoloop import discover_backlog
        done = frozenset(st["loop"]["completed"]) | frozenset(st["loop"]["skipped"])
        backlog = discover_backlog(project_dir, done)
        if backlog:
            top = backlog[0]
            st["next"] = {"title": top["title"], "reason": top["reason"],
                          "blocker": bool(top.get("blocker"))}
        else:
            st["next"] = None
    except Exception:  # noqa: BLE001
        st["next"] = None
    return st


def print_status(st: dict) -> None:
    from psyclaw import ui
    print(ui.title("PsyClaw status") + ui.dim(f"  {st['project']}"))

    goal = st.get("goal") or "(未设定 — psyclaw goal <目标>)"
    print(f"  目标      : {goal.splitlines()[0][:70]}")

    c = st["clarify"]
    if c["exists"]:
        mark = "✓" if c["unresolved"] == 0 else f"{c['resolved']}/{c['total']}(未解决 {c['unresolved']})"
        print(f"  澄清      : {mark}")
    else:
        print(ui.dim("  澄清      : 未开始(psyclaw clarify;或各 loop 加 --skip-gates 显式跳过)"))

    lp = st["loop"]
    if lp["iteration"] or lp["completed"] or lp["skipped"]:
        print(f"  回路      : 迭代 {lp['iteration']} · 完成 {', '.join(lp['completed']) or '—'}"
              + (f" · 跳过 {', '.join(lp['skipped'])}" if lp["skipped"] else ""))
    if st.get("workflow_verdict"):
        print(f"  总验收    : {st['workflow_verdict']}")

    if st.get("decision_request"):
        print(ui.warn("\n  ⚠ 有决策等你(notes/decision_request.md):"))
        for ln in st["decision_request"].splitlines()[:10]:
            print(ui.dim(f"    {ln}"))
    if st.get("last_blocked"):
        print(ui.warn("\n  最近被阻塞:"))
        for ln in st["last_blocked"].splitlines()[:4]:
            print(ui.dim(f"    {ln}"))

    if st.get("recent_artifacts"):
        print("\n  最近产物  : " + " · ".join(st["recent_artifacts"]))

    nxt = st.get("next")
    if nxt:
        tag = "⚠ 被门禁拦" if nxt["blocker"] else "→ 建议下一步"
        print(ui.accent(f"\n  {tag}:{nxt['title']}") + ui.dim(f" — {nxt['reason']}"))
        print(ui.dim("    psyclaw auto-loop 一键推进" +
                     ("(或对应命令处理门禁)" if nxt["blocker"] else "")))
    else:
        print(ui.ok("\n  ✓ 无待办 — 所有可发现的研究阶段已完成或无输入(psyclaw guide 看上手)"))
