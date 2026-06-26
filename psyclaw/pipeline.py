"""研究全流水线编排(一句话编排 / End-to-End Research Pipeline)。

把研究编排串成**一条命令**(`psyclaw research <topic>` / REPL `/research`):

  澄清门禁 → ① 文献 → ② 设计 → ③ 写作(APA-JARS)
          → ④ 评审(peer-review panel) → ⑤ 总验收(澄清 + 评审 → 判决)

统计已外移到成熟库/MCP——本编排不内置统计计算,只做研究流程编排。

与 run_loop(HITL planner→executor→critic 主干)的分工:
  - `research --freeform`(run_loop):通用 HITL 回路,planner 拆任务、critic 修复环。
  - `research`(run_pipeline,本模块):按研究流程组织,产出一篇结构完整的稿,
    末尾跑同行评审,给出机器可读的总验收(notes/pipeline_summary.json)。

复用既有积木,不重造轮子:
  loop._gen / _log / _ask_yn · review.summarize / run_review · clarify.check_card

机器可判定控制点(纯函数,可单测,fail-closed):
  pipeline_verdict(clarify_resolved, stat_gate, review_summary) -> 总验收 dict
  (stat_gate 现恒为 None——统计外移后无内置统计门禁)
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

# 研究编排阶段标识(顺序即执行顺序)。
PHASES = ["literature", "design", "writing", "review", "gates"]


# ---------------------------------------------------------------------------
# 机器可判定的总验收(纯函数,fail-closed,可单测;不依赖 LLM / IO)
# ---------------------------------------------------------------------------

def pipeline_verdict(clarify_resolved: bool, stat_gate: dict | None,
                     review_summary: dict | None) -> dict:
    """把各阶段产出汇总为机器可读的总验收。

    判定(fail-closed,任一维度不达标即不过):
      - clarify_resolved 必须为 True(澄清未完成,流水线根本不应抵达交付)。
      - 统计门禁:stat_gate 为 check_artifact 结果;None 表示无统计产出
        (理论/综述型研究,统计门禁不适用 → 记 'n/a',不阻断)。有结果则
        必须 passed(无 blocking)。
      - 同行评审:review_summary 为 review.summarize 结果;None 表示未评审
        (视为未通过,不能把"没评审"当作通过)。通过需**零 BLOCKING 行动项**
        且编辑决定 ∈ {ACCEPT, MINOR}(MAJOR/REJECT 不算过门禁)。

    返回 {overall_passed, clarify_ok, gates_ok, gates_status, review_ok,
          review_decision, n_blocking, reasons:[...]}。
    """
    reasons: list[str] = []

    clarify_ok = bool(clarify_resolved)
    if not clarify_ok:
        reasons.append("澄清卡未全部 resolved(CLARIFY.complete 未放行)")

    if stat_gate is None:
        gates_ok, gates_status = True, "n/a"
    else:
        gates_ok = bool(stat_gate.get("passed"))
        gates_status = "passed" if gates_ok else "blocked"
        if not gates_ok:
            n_blk = len(stat_gate.get("blocking", []))
            reasons.append(f"统计门禁阻断({n_blk} 项 blocking)")

    if review_summary is None:
        review_ok, review_decision, n_blocking = False, None, 0
        reasons.append("未跑同行评审(不能把'未评审'当作通过)")
    else:
        review_decision = review_summary.get("decision")
        n_blocking = int(review_summary.get("n_blocking", 0))
        review_ok = (review_decision in ("ACCEPT", "MINOR")) and n_blocking == 0
        if review_decision not in ("ACCEPT", "MINOR"):
            reasons.append(f"编辑决定 {review_decision}(需 ACCEPT/MINOR)")
        elif n_blocking:
            reasons.append(f"仍有 {n_blocking} 项 BLOCKING 修订未消")

    overall = clarify_ok and gates_ok and review_ok
    return {
        "overall_passed": overall,
        "clarify_ok": clarify_ok,
        "gates_ok": gates_ok,
        "gates_status": gates_status,
        "review_ok": review_ok,
        "review_decision": review_decision,
        "n_blocking": n_blocking,
        "reasons": reasons,
    }


# ---------------------------------------------------------------------------
# 阶段任务提示(executor/planner 角色复用 loop._gen 的 agent 定义 + 规范注入)
# ---------------------------------------------------------------------------

def _lit_task(goal: str) -> str:
    return (
        f"研究目标:{goal}\n"
        "产出**文献/背景综述草稿**(related work):围绕目标梳理核心构念、已有"
        "发现、争议与研究空白(gap),为假设提供理论铺垫。论断尽量标注可核验的"
        "出处占位 `[作者, 年]`。**不得编造具体数值或 DOI**。(回落占位:先跑 "
        "`psyclaw lit <检索式>` 可据真实检索命中合成有据综述,见 synthesize.py。)")


def _design_task(goal: str) -> str:
    return (
        f"研究目标:{goal}\n据背景综述产出**研究设计**:\n"
        "① 研究假设(区分确证/探索,标注方向);\n"
        "② 变量(IV/DV/协变量及操作化定义);\n"
        "③ 设计类型(被试间/内/混合/纵向/ESM 等);\n"
        "④ 功效分析与样本量依据(给出效应量先验与 α/power,提示发表偏倚"
        "易高估真实效应,先验宜保守);\n"
        "⑤ 主要分析计划(检验族 + 多重比较处理 + 探索/确证划分)。\n"
        "设计决策尽量给方法学依据(背书库见 `psyclaw cite`)。")



# ---------------------------------------------------------------------------
# 编排(依赖 provider / IO)
# ---------------------------------------------------------------------------

def _literature_stage(provider, goal: str, clar: str, project: Path) -> str:
    """① 文献:优先据 `/lit` 缓存的真实检索命中合成**有据综述**;无缓存则回落占位。

    无论走哪条分支,都只消耗**一次** provider 调用(综述叙事),保证编排时序稳定。
    `psyclaw lit <检索式>` 会把检索结果缓存到 notes/lit_search.json —— 跑过 lit 再跑
    research,本阶段即据真实题录(知识抽取 → 证据图谱 → 有据叙事)产出综述。
    """
    from psyclaw.loop import _gen

    cache = project / "notes" / "lit_search.json"
    papers = None
    if cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            papers = data.get("results") if isinstance(data, dict) else None
        except (json.JSONDecodeError, OSError):
            papers = None

    if papers:
        from psyclaw.psych import synthesize
        syn = synthesize.synthesize_review(goal, {"results": papers}, provider=provider)
        (project / "notes" / "evidence_map.json").write_text(
            json.dumps(syn["evidence_map"], ensure_ascii=False, indent=2),
            encoding="utf-8")
        from psyclaw import ui
        print(ui.dim(f"  据 /lit 缓存 {syn['n_papers']} 篇真实命中合成综述"
                     f"({'有据叙事' if syn['grounded'] else '确定性骨架'});"
                     f"证据图谱 → notes/evidence_map.json"))
        return syn["markdown"]

    from psyclaw import ui
    print(ui.dim("  无 /lit 检索缓存,产出占位综述;先跑 `psyclaw lit <检索式>` "
                 "可据真实文献合成有据综述。"))
    return _gen(provider, "executor", _lit_task(goal), clar)


def run_pipeline(topic: str | None = None, project_dir: str = ".",
                 auto: bool = False, revise: bool = False,
                 rounds: int = 3) -> int:
    """跑端到端研究流水线。

    返回:
      1 —— 硬阻断(澄清门禁未过 / 无研究目标 / 写作阶段未产出稿)。
      0 —— 流水线完整跑通(产出稿 + 跑完门禁与评审,总验收写入 summary)。
           总验收 PASS/BLOCK 见 notes/pipeline_summary.json 与终端报告;
           评审未达 ACCEPT/MINOR 不视为运行失败(交人工,符合 HITL 纪律)。
    """
    from psyclaw import config as cfg, ui
    from psyclaw.loop import _gen, _log, _read
    from psyclaw.providers import get_provider
    from psyclaw.psych.clarify import check_card
    from psyclaw.review import run_review, summarize
    from psyclaw.tasks import get_goal, set_goal

    project = Path(project_dir)
    for sub in ("notes", "outputs", "logs", "figures",
                "data/raw", "data/clean"):
        (project / sub).mkdir(parents=True, exist_ok=True)

    goal = topic or get_goal(project)
    if not goal:
        print(ui.err("没有研究目标:psyclaw research <目标>,或先 psyclaw goal <目标>。"))
        return 1
    if topic:
        set_goal(topic, project)

    print(ui.panel(
        "Research Pipeline — 一句话编排(文献→设计→写作→评审→总验收)",
        f"目标:{goal.splitlines()[0][:80]}"))

    # —— 门禁 0:澄清(硬规则,不澄清完不开工)——
    card = check_card(project_dir)
    if card["unresolved"]:
        print(ui.err(f"✗ CLARIFY.complete 拦截:澄清卡 {card['resolved']}/{card['total']},"
                     f"未解决 {len(card['unresolved'])} 项。"))
        print("  先运行 psyclaw clarify —— 不澄清完,不开工。")
        _write_summary(project, goal, pipeline_verdict(False, None, None),
                       {}, stopped="clarify")
        return 1
    print(ui.ok("✓ 澄清门禁通过"))

    conf = cfg.load_config()
    provider = get_provider(conf)
    clar = _read(project / "notes" / "clarification.md")
    _log(project, f"pipeline start · provider={provider.name} · goal={goal[:60]}")
    artifacts: dict[str, str] = {}

    # —— ① 文献 ——
    print("\n" + ui.accent("① 文献(背景综述)"))
    lit = _literature_stage(provider, goal, clar, project)
    (project / "notes" / "lit_review.md").write_text(lit, encoding="utf-8")
    artifacts["literature"] = "notes/lit_review.md"
    _log(project, "pipeline ① 文献 → notes/lit_review.md")
    print(ui.panel("notes/lit_review.md", lit[:700] + ("…" if len(lit) > 700 else "")))

    # —— ② 设计 ——
    print("\n" + ui.accent("② 设计(假设·变量·功效·样本量)"))
    design = _gen(provider, "planner", _design_task(goal),
                  f"# 背景综述\n{lit}\n\n# 澄清卡\n{clar}")
    (project / "notes" / "design.md").write_text(design, encoding="utf-8")
    artifacts["design"] = "notes/design.md"
    _log(project, "pipeline ② 设计 → notes/design.md")
    print(ui.panel("notes/design.md", design[:700] + ("…" if len(design) > 700 else "")))

    # —— ③ 写作(APA-JARS;统计已外移到成熟库/MCP,本编排不内置统计)——
    from psyclaw.output.writing_backend import BACKEND_ARS, detect_backend, write_paper

    writing_backend = detect_backend(project_dir)
    backend_label = "ARS插件" if writing_backend == BACKEND_ARS else "内置"
    print("\n" + ui.accent(f"③ 写作(APA-JARS 结构稿 · {backend_label}写作后端)"))
    write_ctx = f"# 背景综述\n{lit}\n\n# 研究设计\n{design}"
    report, write_meta = write_paper(goal, write_ctx, provider, project,
                                     backend=writing_backend)
    report_path = project / "outputs" / "report.md"
    if not report.strip():
        print(ui.err("✗ 写作阶段未产出稿(provider 返回空),硬停止。"))
        _log(project, "pipeline ④ 写作产出为空 → 硬停止")
        return 1
    artifacts["writing"] = "outputs/report.md"
    if write_meta.get("abstract", {}) and write_meta["abstract"].get("zh"):
        artifacts["abstract"] = "notes/abstract_bilingual.md"
        print(ui.ok("  ✓ 双语摘要 → notes/abstract_bilingual.md"))
    if write_meta.get("jars"):
        jars = write_meta["jars"]
        n_blk = len(jars.get("blocking", []))
        jars_label = "通过" if jars.get("passed") else f"阻断({n_blk}项)"
        print(ui.ok(f"  ✓ JARS 检查 {jars_label} → notes/jars_check.json"))
    _log(project, f"pipeline ④ 写作({backend_label}) → outputs/report.md")
    print(ui.panel("outputs/report.md", report[:700] + ("…" if len(report) > 700 else "")))

    # —— ④ 评审(peer-review panel;revise=True 闭合写作→评审→修复)——
    print("\n" + ui.accent("④ 评审(EIC + R1/R2/R3 + Devil's Advocate)"))
    run_review(draft=str(report_path), project_dir=project_dir,
               auto=auto, revise=revise, rounds=rounds)
    review_summary: dict | None = None
    rj = project / "notes" / "review_panel.json"
    if rj.exists():
        try:
            review_summary = json.loads(rj.read_text(encoding="utf-8"))
            artifacts["review"] = "notes/review_panel.{md,json}"
        except (json.JSONDecodeError, OSError):
            review_summary = summarize(
                _read(project / "notes" / "review_panel.md"))
    revised = project / "notes" / "revised_draft.md"
    final_draft = ("notes/revised_draft.md" if revise and revised.exists()
                   else "outputs/report.md")

    # —— ⑤ 总验收(澄清 + 评审 → 机器可读判决;统计已外移到成熟库/MCP)——
    print("\n" + ui.accent("⑤ 总验收"))
    verdict = pipeline_verdict(card["resolved"] == card["total"],
                               None, review_summary)
    verdict["final_draft"] = final_draft
    _write_summary(project, goal, verdict, artifacts)
    _log(project, f"pipeline ⑥ 总验收:{'PASS' if verdict['overall_passed'] else 'BLOCK'} "
                  f"(门禁{verdict['gates_status']} · 评审{verdict['review_decision']})")

    # —— 终态报告 ——
    status = ui.ok("✓ 总验收 PASS — 一篇过门禁的稿") if verdict["overall_passed"] \
        else ui.warn("△ 总验收 BLOCK — 尚未过门禁,交人工")
    print("\n" + status)
    if verdict["reasons"]:
        for r in verdict["reasons"]:
            print(ui.dim(f"    · {r}"))
    print(ui.ok("\n流水线产物:"))
    for f in ("notes/lit_review.md", "notes/design.md", final_draft,
              "notes/review_panel.md", "notes/pipeline_summary.json",
              "logs/run_log.md"):
        p = project / f
        if p.exists():
            print(f"    {p}")
    print(ui.dim("  下一步:psyclaw review --revise 继续闭环,或 psyclaw export 出 APA7。"))
    return 0


def _write_summary(project: Path, goal: str, verdict: dict,
                   artifacts: dict, stopped: str | None = None) -> None:
    """落机器可读的流水线总验收(单一真源,供 CI / 程序判定)。"""
    summary = {
        "goal": goal,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "phases": PHASES,
        "artifacts": artifacts,
        "stopped_at": stopped,
        **verdict,
    }
    (project / "notes").mkdir(parents=True, exist_ok=True)
    (project / "notes" / "pipeline_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def pipeline_cli(argv: list[str]) -> int:
    """薄入口:research <topic> [--revise] [--auto] [--rounds N]。"""
    topic_parts: list[str] = []
    revise = auto = False
    rounds = 3
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--revise", "-r"):
            revise = True
        elif a == "--auto":
            auto = True
        elif a == "--rounds":
            i += 1
            try:
                rounds = int(argv[i])
            except (IndexError, ValueError):
                rounds = 3
        elif not a.startswith("-"):
            topic_parts.append(a)
        i += 1
    topic = " ".join(topic_parts) or None
    return run_pipeline(topic=topic, revise=revise, auto=auto, rounds=rounds)
