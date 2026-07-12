"""Research Loop — HITL 多智能体研究回路(真实现)。

planner → [人工确认计划] → executor → critic → 修复环 → [审批门] → 交付

落盘到项目结构(吸收 psycho-vibe 纪律):
  notes/plan.md · review.md · decision_request.md · repro_manifest.md
  scripts/ · outputs/ · logs/run_log.md

机制(v0.2 收紧):
- critic 裁决 **fail-closed**:必须末行输出 `VERDICT: PASS|BLOCK`,
  解析不到一律按 BLOCK 处理 —— 不再用关键词猜。
- DECISION_REQUEST 用**行首标记**机器识别;auto 模式遇到一律硬失败
  (数据操作必须人工批准,DATA.careless 不允许 CI 自动判定为通过)。
- 自动分析只在研究准备清单能**明确对应**到数据列时才跑,绝不猜列名
  (rigor.md:信息不足就停,先问再算)。
- data/raw 只读不再是口头约定:回路前后做 SHA-256 快照比对,
  被改动 → 阻断交付。repro_manifest 写真实指纹,不写占位文案。
- 程序化质量检查(gates.checker)结果作为客观依据注入 critic 上下文。
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path

from psyclaw import ui
from psyclaw.tasks import TaskStore

VERDICT_RE = re.compile(r"VERDICT\s*[::]\s*(PASS|BLOCK)", re.IGNORECASE)
DECISION_RE = re.compile(r"(?m)^\s*DECISION_REQUEST\b")
MAX_REVIEW_ROUNDS = 3


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _agent_prompt(role: str) -> str:
    """读取 planner/executor/critic 的 agent 定义作为 system 提示。"""
    p = Path(__file__).parent / "agents" / f"{role}.md"
    base = _read(p)
    rigor = _read(Path(__file__).parent / "gates" / "rigor.md")
    spec = _read(Path(__file__).parent / "gates" / "PSYCLAW.md")
    return f"{base}\n\n# 严谨性协议\n{rigor}\n\n# 学术规范\n{spec}"


def _ask_yn(prompt: str, default: bool = True) -> bool:
    d = "Y/n" if default else "y/N"
    # readline 安全提示:彩色码用 \001..\002 包裹,否则回显光标错位、y 与命令串行(用户实测)
    from psyclaw.ui_input import safe_prompt
    try:
        v = input(safe_prompt(ui.warn(f"  ⏸ {prompt} [{d}]: "))).strip().lower()
    except EOFError:
        return default
    return default if not v else v.startswith("y")


def _log(project: Path, line: str) -> None:
    logp = project / "logs" / "run_log.md"
    logp.parent.mkdir(parents=True, exist_ok=True)
    with logp.open("a", encoding="utf-8") as f:
        f.write(f"- {datetime.now().isoformat(timespec='seconds')} {line}\n")


def _gen(provider, role: str, task: str, context: str = "") -> str:
    """让 provider 以某角色生成内容。"""
    msgs = [{"role": "user", "content": f"{task}\n\n{context}".strip()}]
    try:
        return "".join(provider.chat(msgs, system=_agent_prompt(role)))
    except Exception as exc:  # noqa: BLE001
        return f"[{role} 生成失败] {exc}"


# ---------------------------------------------------------------------------
# 机器可判定的控制点(纯函数,可单测)
# ---------------------------------------------------------------------------

def parse_verdict(review: str) -> str:
    """critic 裁决解析,fail-closed:取最后一个 VERDICT;没有 → BLOCK。"""
    last = None
    for m in VERDICT_RE.finditer(review or ""):
        last = m
    return last.group(1).upper() if last else "BLOCK"


def has_decision_request(text: str) -> bool:
    """只认行首 DECISION_REQUEST 标记;提及该词不算(降低误触发)。"""
    return bool(DECISION_RE.search(text or ""))


def snapshot_raw(project: Path) -> dict:
    """data/raw 全量 SHA-256 快照(只读约束的机器证据)。"""
    out: dict = {}
    raw = project / "data" / "raw"
    if raw.exists():
        for f in sorted(raw.rglob("*")):
            if f.is_file():
                out[str(f.relative_to(project))] = \
                    hashlib.sha256(f.read_bytes()).hexdigest()[:16]
    return out


def _planner_task(goal: str) -> str:
    return (f"研究目标:{goal}\n据研究准备清单产出可审计执行计划"
            "(任务/输入输出/依赖/审批节点/停止条件/最小可交付),Markdown 表格。"
            "计划末尾必须有单独的 `## TASKS` 章节:`- [ ] 任务` 复选框列表,"
            "每行一条、动词开头、可独立验收(机器自动抽取为任务看板)。")


def _sync_tasks(project: Path, plan: str) -> TaskStore:
    """计划落盘后自动写任务(auto-write task),返回 store 供后续进度追踪。"""
    store = TaskStore(project)
    n = store.sync_from_plan(plan)
    _, total = store.progress()
    if n:
        print(ui.ok(f"  ✓ 自动写入 {n} 条新任务(共 {total} 条)→ notes/tasks.md"))
        _log(project, f"plan → 自动抽取 {n} 条任务")
    elif not total:
        print(ui.warn("  计划里没有可抽取的 TASKS 复选框,任务看板未更新"
                      "(可手改 plan.md 后 psyclaw tasks sync)。"))
    return store


def run_plan(topic: str | None = None, project_dir: str = ".",
             auto: bool = False) -> int:
    """单独跑规划阶段:planner → notes/plan.md → 自动写任务。

    与 run_loop 的 ① 等价,但不进入执行;适合「先规划、人改完计划再开工」。
    """
    from psyclaw import config as cfg
    from psyclaw.providers import get_provider
    from psyclaw.tasks import get_goal, set_goal

    project = Path(project_dir)
    (project / "notes").mkdir(parents=True, exist_ok=True)
    goal = topic or get_goal(project)
    if not goal:
        print(ui.err("没有研究目标:psyclaw plan <目标>,或先 psyclaw goal <目标>。"))
        return 1
    if topic:
        set_goal(topic, project)
    conf = cfg.load_config()
    provider = get_provider(conf)
    clar = _read(project / "notes" / "clarification.md")
    print(ui.panel("Plan — 规划(planner)",
                   f"目标:{goal.splitlines()[0][:80]}\nprovider:{provider.name}"))
    plan = _gen(provider, "planner", _planner_task(goal), clar)
    (project / "notes" / "plan.md").write_text(plan, encoding="utf-8")
    _log(project, f"plan(独立) → notes/plan.md · goal={goal[:60]}")
    print(ui.panel("notes/plan.md", plan[:1200] + ("…" if len(plan) > 1200 else "")))
    store = _sync_tasks(project, plan)
    if store.tasks:
        print(store.board())
    if not auto and not _ask_yn("计划是否通过?(否则可手改 plan.md 再 psyclaw tasks sync)"):
        print(ui.dim("已停在规划阶段。计划已存 notes/plan.md。"))
    return 0


def _gates_report(project: Path) -> str:
    """对最新 stat sidecar 跑程序化质量检查,作为 critic 的客观依据。"""
    js = sorted((project / "outputs").glob("result_*.json"))
    if not js:
        return "(无结构化统计产出,未触发质量检查)"
    from psyclaw.gates.checker import check_artifact, format_report
    res = check_artifact(str(js[-1]), "stat")
    return f"对象:{js[-1].name}\n{format_report(res)}"


# ---------------------------------------------------------------------------
# 主回路
# ---------------------------------------------------------------------------

def run_loop(topic: str | None = None, project_dir: str = ".",
             auto: bool = False) -> int:
    """跑完整 HITL 研究回路。auto=True 跳过确认,但**绝不**自动批准数据操作。"""
    from psyclaw import config as cfg
    from psyclaw.providers import get_provider
    from psyclaw.psych.clarify import check_card

    project = Path(project_dir)
    for sub in ("notes", "scripts", "outputs", "logs", "figures",
                "data/raw", "data/clean", "data/temp"):
        (project / sub).mkdir(parents=True, exist_ok=True)

    print(ui.panel("Research Loop — HITL 多智能体研究回路",
                   "planner → 确认 → executor → critic → 修复环 → 审批门 → 交付"))

    # —— 前置检查 0:澄清 ——
    card = check_card(project_dir)
    if card["unresolved"]:
        print(ui.err(f"✗ 前置检查 CLARIFY.complete 未通过：研究准备项 {card['resolved']}/{card['total']}，"
                     f"未解决 {len(card['unresolved'])} 项。"))
        print("  先运行 psyclaw prepare —— 研究准备未完成前不启动正式流程。")
        return 1
    print(ui.ok("✓ 研究准备检查通过"))

    # —— 前置检查 0.5:data/raw 只读快照(交付前比对)——
    raw_snapshot = snapshot_raw(project)
    if raw_snapshot:
        print(ui.dim(f"  data/raw 快照:{len(raw_snapshot)} 个文件已记录 SHA-256"))

    conf = cfg.load_config()
    provider = get_provider(conf)
    clar = _read(project / "notes" / "clarification.md")
    goal = topic or _read(project / "notes" / "goal.md") or "(见研究准备清单)"
    _log(project, f"loop start · provider={provider.name} · topic={goal[:60]}")

    # —— 1. planner ——
    print("\n" + ui.accent("① 规划(planner)"))
    plan = _gen(provider, "planner", _planner_task(goal), clar)
    (project / "notes" / "plan.md").write_text(plan, encoding="utf-8")
    print(ui.panel("notes/plan.md", plan[:1200] + ("…" if len(plan) > 1200 else "")))
    _log(project, "planner → notes/plan.md")
    store = _sync_tasks(project, plan)

    if not auto and not _ask_yn("计划是否通过?(否则停止,你可手改 plan.md 再重跑)"):
        print(ui.dim("已停在规划阶段。计划已存 notes/plan.md。"))
        return 0

    # —— 2. executor ——
    print("\n" + ui.accent("② 执行(executor)"))
    execed = _gen(provider, "executor",
                  "按 plan.md 产出第一阶段分析脚本(数据质量+描述统计)。"
                  "脚本写法遵循严谨性协议;若需删除/重编码数据,不要执行,"
                  "改为**单独一行、行首**以 `DECISION_REQUEST:` 开头说明理由"
                  "(机器按行首标记识别)。"
                  "完成计划 `## TASKS` 中的某条任务时,**单独一行、行首**输出 "
                  "`TASK_DONE: <任务标题>`(机器据此更新任务进度;"
                  "不标记不更新,不要虚报未验证的完成)。",
                  plan)
    (project / "notes" / "step1_outline.md").write_text(execed, encoding="utf-8")
    _log(project, "executor → notes/step1_outline.md")
    print(ui.panel("executor 产出", execed[:900] + ("…" if len(execed) > 900 else "")))

    # —— 审批门:行首 DECISION_REQUEST ——
    if has_decision_request(execed):
        dr = ("# 决策请求\n\nexecutor 在执行中遇到需人工批准的数据操作"
              "(删除/重编码/剔异常值)。详见下述理由,批准前流程暂停。\n\n" + execed)
        (project / "notes" / "decision_request.md").write_text(dr, encoding="utf-8")
        _log(project, "执行触发 decision_request,暂停等待人工批准")
        print(ui.warn("\n⏸ 触发数据操作审批门 → notes/decision_request.md"))
        if auto:
            # 数据操作没有"自动批准"这条路(DATA.careless:须人工批准)
            print(ui.err("auto 模式遇 DECISION_REQUEST:数据操作必须人工批准,"
                         "硬停止(退出码 1)。"))
            _log(project, "auto 模式遇 decision_request → 硬停止")
            return 1
        if not _ask_yn("批准该数据操作?"):
            print(ui.dim("未批准。流程停在执行阶段,符合 HITL 纪律。"))
            return 0
        _log(project, "decision_request 已获人工批准")

    # —— 3. critic(含修复环)——
    print("\n" + ui.accent("③ 审查(critic)+ 修复环"))
    gates_report = _gates_report(project)
    review = ""
    for rnd in range(1, MAX_REVIEW_ROUNDS + 1):
        review = _gen(provider, "critic",
                      f"审查以下计划与执行产出(第 {rnd} 轮)。按 Blocking / Warning / "
                      "Approved 三段输出;逐条核对严谨性协议第四节常见错误。"
                      "程序化质量检查结果已附,作为客观依据。"
                      "**最后必须单独一行输出裁决:`VERDICT: PASS`(零 Blocking)"
                      "或 `VERDICT: BLOCK`。未按格式输出将按 BLOCK 处理。**",
                      f"# GATES(程序化校验,客观依据)\n{gates_report}\n\n"
                      f"# PLAN\n{plan}\n\n# EXEC\n{execed}")
        (project / "notes" / "review.md").write_text(review, encoding="utf-8")
        _log(project, f"critic 第{rnd}轮 → notes/review.md")
        verdict = parse_verdict(review)
        print(ui.panel(f"critic 第 {rnd} 轮(裁决:{verdict})",
                       review[:900] + ("…" if len(review) > 900 else "")))
        if verdict == "PASS":
            print(ui.ok(f"✓ 第 {rnd} 轮:VERDICT: PASS,审查通过"))
            break
        if not VERDICT_RE.search(review):
            print(ui.warn("  critic 未输出 VERDICT,按 BLOCK 处理(fail-closed)"))
        if rnd < MAX_REVIEW_ROUNDS:
            print(ui.warn(f"  第 {rnd} 轮 BLOCK,executor 修复后重审…"))
            execed = _gen(provider, "executor",
                          "仅修复 critic 指出的 Blocking,其余保持不变。"
                          "输出修复后的**完整版本**(全文替换,不要引用或附加旧稿)。",
                          f"# REVIEW\n{review}\n\n# 当前版本\n{execed}")
            (project / "notes" / "step1_outline.md").write_text(execed, encoding="utf-8")
            # 把 critic 的 blocking 草拟成教训卡(待人工确认)
            try:
                from psyclaw.memory import draft_lesson
                draft_lesson("critic-blocking", review.split("\n")[0][:120], "critic")
            except Exception:  # noqa: BLE001
                pass
        else:
            print(ui.err("  达最大修复轮次仍 BLOCK,停止并通知人工(紧急停止条件)。"))
            return 1

    # —— 3.4 任务进度:TASK_DONE 标记在 critic PASS 后才生效(未过审不算完成)——
    done_hits = store.mark_done_from(execed)
    if done_hits:
        d, t = store.progress()
        print(ui.ok(f"  ✓ 任务进度更新 {d}/{t}:"
                    + "、".join(h["title"][:24] for h in done_hits)))
        _log(project, f"TASK_DONE × {len(done_hits)}(critic PASS 后生效)→ {d}/{t}")

    # —— 3.5 交付前完整性核查:data/raw 未被改动 ——
    if raw_snapshot:
        now_snapshot = snapshot_raw(project)
        if now_snapshot != raw_snapshot:
            changed = {k for k in set(raw_snapshot) | set(now_snapshot)
                       if raw_snapshot.get(k) != now_snapshot.get(k)}
            print(ui.err(f"✗ data/raw 在回路中被改动({len(changed)} 处):"
                         f"{', '.join(sorted(changed)[:5])}"))
            print(ui.err("  违反只读硬规则,阻断交付(紧急停止条件)。"))
            _log(project, f"data/raw 完整性校验失败:{sorted(changed)[:5]}")
            return 1
        print(ui.ok("✓ data/raw 完整性校验通过(回路前后哈希一致)"))

    # —— 4. 交付 ——
    print("\n" + ui.accent("④ 交付"))
    report = _gen(provider, "executor",
                  "整理最终分析报告(只引用 outputs/ 中存在的表图;"
                  "解释用限定性措辞,效应量+CI 优先)。", f"{plan}\n{review}")
    (project / "outputs" / "report.md").write_text(report, encoding="utf-8")
    fp_lines = ([f"  - {k}: {v}" for k, v in sorted(raw_snapshot.items())]
                if raw_snapshot else ["  - (data/raw 为空)"])
    manifest = "\n".join([
        "# 复现清单",
        "",
        f"- 时间:{datetime.now().isoformat(timespec='seconds')}",
        f"- provider:{provider.name}",
        f"- 研究目标:{goal}",
        "- 随机性:ARS-Stat bootstrap 固定种子 12345;"
        "其余脚本须在脚本内固定种子并写入 logs/run_log.md",
        "- 运行顺序:scripts/step*.py(见 plan.md)",
        "- 数据指纹(SHA-256 前16,回路前后已比对一致):",
        *fp_lines,
        "- 产物:outputs/report.md, outputs/result_*.{md,json}, "
        "outputs/repro_*.py, figures/",
        "- 复现:逐个运行 outputs/repro_*.py,指纹或统计量不符会以退出码 1 报错",
    ]) + "\n"
    (project / "notes" / "repro_manifest.md").write_text(manifest, encoding="utf-8")
    _log(project, "交付 → outputs/report.md + notes/repro_manifest.md")

    print(ui.ok("\n✓ 回路完成。产物:"))
    for f in ("notes/plan.md", "notes/tasks.md", "notes/review.md",
              "outputs/report.md", "notes/repro_manifest.md", "logs/run_log.md"):
        print(f"    {project / f}")
    if store.tasks:
        print()
        print(store.board())
        d, t = store.progress()
        if d < t:
            print(ui.dim("  剩余任务用 psyclaw tasks done <编号> 人工核销,"
                         "或下一轮回路继续。"))
    if not auto:
        try:
            from psyclaw.output.apa7 import export_cli  # noqa: F401
            if _ask_yn("把报告导出为 APA7 Word?"):
                from psyclaw.output.apa7 import export_cli as _ex
                _ex([str(project / "outputs" / "report.md")])
        except Exception:  # noqa: BLE001
            pass
    return 0
