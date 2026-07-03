"""Auto-Loop — 自主科研回路(Ralph 式自循环,驱动既有 <type>-loop 流程)。

定位:`loop` 是「一个任务」的通用 HITL 编排器,`<type>-loop` 是「一类研究」的预置流程;
**`auto-loop` 是其上的自驱动元回路**——自己发现要做什么、派发给对应流程、独立验收、
记状态、决定下一步,直到无事可做 / 被门禁挡住 / 到达迭代上限。

每一轮(iteration)严格走五步,正是「自循环系统」的五个职责:
  ① 感知/发现需求(sense)   discover_backlog —— 从仓库状态重新推导待办(模型会忘,仓库不会)
  ② 派发任务(dispatch)      select_next + _dispatch —— 路由到对应 workflow(实现 sub-agent)
  ③ 检查成果(verify)        verify_result —— 读落盘的总验收 + 产物,**独立于执行**(验收 sub-agent)
  ④ 记录状态(record)        record_iteration + save_state —— 写 notes/autoloop_state.json(外部记忆)
  ⑤ 决定下一步(decide)       decide —— 停止条件:backlog 空 / 门禁 blocker / 迭代上限 / 已跳过

设计纪律:
- **状态在仓库,不在模型**:每轮都 discover_backlog(重新从磁盘推导),不依赖上一轮的记忆;
  loop 自己的进度落 notes/autoloop_state.json,压缩/重启都能续。
- **实现与验收分离**:派发的 workflow 负责"干",verify_result 另读落盘产物独立判"成"——
  不信执行返回码,只信仓库里真实存在的 workflow_summary.json + 产物(一个干、一个验)。
- **fail-closed + 不空转**:澄清未完 = 硬 blocker(写 decision_request 后停,要人来跑 clarify);
  某流程验收不过 = 标记跳过 + 写 notes/blocked.md,**换下一个任务**,不在一个坑里重试空烧。
- **只读 data/clean 与根目录**:自动发现绝不读 data/raw(原始数据受保护、只读哈希守卫);
  分类 CSV 只读表头(元数据级),不载入数据值。
- 控制流全确定性(纯函数 discover/select/verify/decide,可单测);LLM 只在被派发的 workflow 内部。

统计仍整体外移:被派发的 meta-loop/analysis-loop 只生成委托 statsmodels/pingouin 的脚本,本回路不算统计。
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

# 行动(action)→ workflow id(供派发与独立验收对账)
_ACTION_WF = {
    "lit-loop": "lit-review",
    "meta-loop": "meta",
    "analysis-loop": "analysis",
    "qual-loop": "qualitative",
}

# 每类流程的「已完成」标志产物(用于幂等收敛:产物在 = 该阶段已做,不重复发现)
_ACTION_ARTIFACT = {
    "lit-loop": "notes/lit_review.md",
    "meta-loop": "outputs/meta_analysis.py",
    "analysis-loop": "outputs/analysis.py",
    "qual-loop": "notes/thematic_analysis.md",
}

TEXT_SUFFIX = (".txt", ".md")

# 效应量表识别列名(把 CSV 路由到 meta vs analysis)。效应量列沿用标准惯用名(含 d/g/r/z——
# 这些就是 Cohen's d / Hedges' g / 相关 r 的常见列名);但**研究标签**与**方差**列刻意收紧、
# 不含 id/name/label/v 等在普通数据表里也常见的泛化名——否则像 `id,d,v` 这种数据表会被误判成
# 效应量表、误路由到 meta-loop(validate_effects 随后失败,该 CSV 反而漏掉了 analysis-loop)。
# 宁可把模糊表当数据表(analysis-loop 的 profile_data 能吃任意 CSV),也不把数据表误当效应量表。
_EFFECT_COLS = ("yi", "effect", "effect_size", "effectsize", "es", "smd", "d",
                "cohen_d", "cohens_d", "hedges_g", "hedges", "g", "r", "z",
                "lnor", "logor", "log_or")
_VAR_COLS = ("vi", "var", "variance")           # 刻意去掉泛化的 "v"
_SE_COLS = ("se", "sei", "std", "stderr", "standard_error", "se_effect")
_CILOW_COLS = ("ci_low", "ci_lower", "cilow", "lci", "ci_l")    # 去掉泛化的 lower/ll
_CIHIGH_COLS = ("ci_high", "ci_upper", "cihigh", "uci", "ci_u")  # 去掉泛化的 upper/ul
_STUDY_COLS = ("study", "author", "authors", "citation",        # 去掉泛化的 id/name/label
               "study_id", "study_label")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


# ---------------------------------------------------------------------------
# 输入探测(只读 data/clean 与根目录;绝不读 data/raw)
# ---------------------------------------------------------------------------

def _find_csvs(project: Path) -> list[str]:
    """收集可分析的 CSV:项目根 + data/clean(刻意不含 data/raw —— 原始数据受保护)。"""
    out: list[str] = []
    seen: set[str] = set()
    for d in (project, project / "data" / "clean"):
        if d.is_dir():
            for p in sorted(d.glob("*.csv")):
                s = str(p)
                if s not in seen:
                    seen.add(s)
                    out.append(s)
    return out


def classify_csv(path: str) -> str:
    """只读表头分类 CSV → 'effects'(效应量表,走 meta)或 'data'(数据表,走 analysis)。

    判定保守:效应量列 + 方差来源(variance/se/CI 上下界) + 研究标签 三者**精确**齐备,
    才算效应量表;研究标签/方差列用收紧的列名集(不含 id/name/v),避免普通数据表(如 id,d,v)
    被误路由到元分析。否则一律当数据表(analysis-loop 能处理任意 CSV)。
    只读首行表头(元数据级),不载入任何数据值——尊重原始数据敏感性。
    """
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            header = next(csv.reader(f), [])
    except (OSError, StopIteration):
        return "data"
    low = {h.lower().strip() for h in header}
    has = lambda cands: any(c in low for c in cands)  # noqa: E731 精确匹配
    has_effect = has(_EFFECT_COLS)
    has_var = has(_VAR_COLS) or has(_SE_COLS) or (has(_CILOW_COLS) and has(_CIHIGH_COLS))
    has_study = has(_STUDY_COLS)
    return "effects" if (has_effect and has_var and has_study) else "data"


def _find_transcripts(project: Path) -> Path | None:
    """探测质性转录稿:transcripts/ 或 interviews/ 目录,或 data/clean 下的 .txt/.md。

    刻意不扫项目根的 .md(避免 README/notes 被误当转录稿)。
    """
    for name in ("transcripts", "interviews"):
        d = project / name
        if d.is_dir() and any(
                p.suffix.lower() in TEXT_SUFFIX for p in d.iterdir() if p.is_file()):
            return d
    clean = project / "data" / "clean"
    if clean.is_dir() and any(
            p.suffix.lower() in TEXT_SUFFIX for p in clean.iterdir() if p.is_file()):
        return clean
    return None


# ---------------------------------------------------------------------------
# ① 感知 / 发现需求(纯函数,可单测)
# ---------------------------------------------------------------------------

def discover_backlog(project_dir: str = ".",
                     done_actions: frozenset = frozenset()) -> list[dict]:
    """从仓库状态重新推导待办研究流程,按优先级排序。

    返回 backlog(list[dict]),每项:{id, action, title, priority, reason, seed, blocker}。
    收敛规则:① done_actions(loop 已完成/已跳过)里的行动剔除;② 标志产物已在磁盘 → 视为已做剔除。
    澄清门禁:若有任何研究流程可做但澄清卡未完 → 短路返回单个 clarify **blocker**
    (不澄清完不开工,所有流程都被它拦着)。无任何可发现的研究输入 → 返回 []。
    """
    project = Path(project_dir)
    notes = project / "notes"

    goal = _read(notes / "goal.md").strip()
    csvs = _find_csvs(project)
    effects = [c for c in csvs if classify_csv(c) == "effects"]
    datas = [c for c in csvs if classify_csv(c) == "data"]
    transcripts = _find_transcripts(project)

    cand: list[dict] = []
    if goal:
        cand.append({"id": "lit", "action": "lit-loop", "priority": 1,
                     "title": "文献综述(lit-loop)",
                     "reason": "已设研究目标但尚无 notes/lit_review.md", "seed": None})
    if effects:
        cand.append({"id": "meta", "action": "meta-loop", "priority": 2,
                     "title": f"元分析(meta-loop · {Path(effects[0]).name})",
                     "reason": f"发现效应量表 {Path(effects[0]).name}",
                     "seed": {"effects_csv": effects[0]}})
    if datas:
        cand.append({"id": "analysis", "action": "analysis-loop", "priority": 2,
                     "title": f"实证分析(analysis-loop · {Path(datas[0]).name})",
                     "reason": f"发现数据表 {Path(datas[0]).name}",
                     "seed": {"data_csv": datas[0]}})
    if transcripts:
        cand.append({"id": "qual", "action": "qual-loop", "priority": 2,
                     "title": f"质性研究(qual-loop · {transcripts.name}/)",
                     "reason": f"发现转录稿目录 {transcripts.name}/",
                     "seed": {"transcripts": str(transcripts)}})

    # 收敛:剔除已完成/已跳过 + 标志产物已存在的
    backlog = [
        c for c in cand
        if c["action"] not in done_actions
        and not (project / _ACTION_ARTIFACT[c["action"]]).exists()
    ]
    if not backlog:
        return []

    # 澄清门禁:有事可做却没澄清完 → 全被 clarify blocker 拦着
    if _clarify_incomplete(project):
        card = _clarify_card(project)
        return [{
            "id": "clarify", "action": "clarify", "priority": 0, "seed": None,
            "blocker": True, "title": "完成研究澄清(clarify)",
            "reason": (f"澄清卡 {card['resolved']}/{card['total']},"
                       f"未解决 {len(card['unresolved'])} 项 —— 不澄清完不开工"),
        }]

    backlog.sort(key=lambda c: c["priority"])
    for c in backlog:
        c.setdefault("blocker", False)
    return backlog


def _clarify_card(project: Path) -> dict:
    from psyclaw.psych.clarify import check_card
    try:
        return check_card(str(project))
    except Exception:  # noqa: BLE001  硬门禁 fail-closed:澄清卡损坏/不可读 → 当作未完成,宁可拦也不放行
        return {"unresolved": ["<card-unreadable>"], "resolved": 0, "total": 0}


def _clarify_incomplete(project: Path) -> bool:
    return bool(_clarify_card(project).get("unresolved"))


# ---------------------------------------------------------------------------
# ② 选择(纯函数)
# ---------------------------------------------------------------------------

def select_next(backlog: list[dict]) -> dict | None:
    """选下一个任务:backlog 已按优先级排序,取第一个(blocker 已被 discover 排到最前)。"""
    return backlog[0] if backlog else None


# ---------------------------------------------------------------------------
# ③ 检查成果 / 独立验收(纯函数 —— 只读落盘产物,不信执行返回码)
# ---------------------------------------------------------------------------

def verify_result(project_dir: str, action: str) -> dict:
    """独立验收被派发流程的产物:读 notes/workflow_summary.json + 标志产物是否落盘。

    返回 {passed, reasons, workflow}。与执行解耦——验收 sub-agent 只认仓库里真实存在的东西:
    ① 总验收对象必须是本行动对应的 workflow;② overall_passed 为真;③ 标志产物文件确实存在。
    """
    project = Path(project_dir)
    want_wf = _ACTION_WF.get(action)
    summary_p = project / "notes" / "workflow_summary.json"
    if not summary_p.exists():
        return {"passed": False, "workflow": None,
                "reasons": ["无 notes/workflow_summary.json(执行未落盘总验收)"]}
    try:
        summary = json.loads(summary_p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"passed": False, "workflow": None,
                "reasons": [f"总验收无法解析:{exc}"]}

    got_wf = summary.get("workflow")
    if want_wf and got_wf != want_wf:
        return {"passed": False, "workflow": got_wf,
                "reasons": [f"验收对象不符:期望 {want_wf},落盘是 {got_wf}"]}

    verdict = summary.get("verdict", {})
    reasons = list(verdict.get("reasons", []))
    artifact = _ACTION_ARTIFACT.get(action)
    artifact_ok = bool(artifact) and (project / artifact).exists()
    if not artifact_ok:
        reasons.append(f"标志产物缺失:{artifact}")
    passed = bool(verdict.get("overall_passed")) and artifact_ok
    return {"passed": passed, "workflow": got_wf, "reasons": reasons}


# ---------------------------------------------------------------------------
# ⑤ 决定下一步(纯函数)
# ---------------------------------------------------------------------------

def decide(state: dict, backlog: list[dict], max_iters: int) -> tuple[str, str]:
    """停止条件判定。返回 ('continue'|'stop', 原因)。"""
    if state.get("iteration", 0) >= max_iters:
        return "stop", f"达到迭代上限 {max_iters}(可 --max-iters 调高)"
    if not backlog:
        return "stop", "backlog 已空——所有可发现的研究阶段都已完成或跳过"
    top = backlog[0]
    if top.get("blocker"):
        return "stop", f"被门禁拦截:{top['reason']}"
    return "continue", top["title"]


# ---------------------------------------------------------------------------
# ④ 状态(外部记忆 —— notes/autoloop_state.json)
# ---------------------------------------------------------------------------

def state_path(project_dir: str = ".") -> Path:
    return Path(project_dir) / "notes" / "autoloop_state.json"


def _fresh_state() -> dict:
    return {"iteration": 0, "started": _now(), "updated": _now(),
            "completed_actions": [], "skipped": [], "history": []}


def load_state(project_dir: str = ".") -> dict:
    p = state_path(project_dir)
    if p.exists():
        try:
            st = json.loads(p.read_text(encoding="utf-8"))
            for k, v in _fresh_state().items():
                st.setdefault(k, v)
            return st
        except (json.JSONDecodeError, OSError):
            pass
    return _fresh_state()


def save_state(state: dict, project_dir: str = ".") -> Path:
    state["updated"] = _now()
    p = state_path(project_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def record_iteration(state: dict, item: dict, verdict: dict) -> dict:
    """把一轮结果写进状态:history 追加,passed→completed_actions,否则→skipped。"""
    status = "done" if verdict["passed"] else "failed"
    state["history"].append({
        "iter": state.get("iteration", 0) + 1, "action": item["action"],
        "title": item["title"], "status": status, "verdict": verdict, "ts": _now(),
    })
    bucket = "completed_actions" if verdict["passed"] else "skipped"
    if item["action"] not in state[bucket]:
        state[bucket].append(item["action"])
    state["iteration"] = state.get("iteration", 0) + 1
    return state


# ---------------------------------------------------------------------------
# 派发(实现 sub-agent —— 路由到既有 workflow)
# ---------------------------------------------------------------------------

def _derive_topic(item: dict) -> str | None:
    """数据驱动流程在无 goal.md 时,据输入文件名派生一个主题(对齐 cmd_meta/cmd_analysis)。"""
    seed = item.get("seed") or {}
    if "effects_csv" in seed:
        return f"针对 {Path(seed['effects_csv']).stem} 的随机效应元分析"
    if "data_csv" in seed:
        return f"针对 {Path(seed['data_csv']).stem} 的实证分析"
    if "transcripts" in seed:
        return f"针对 {Path(seed['transcripts']).name} 的质性研究"
    return None


def _dispatch(item: dict, project_dir: str) -> int:
    """把任务派发给对应 workflow。被派发的流程内部恒 auto=True 跑到底
    (任务级批准在 auto-loop 层已做;澄清等硬门禁仍在 workflow 内生效,不被绕过)。

    主题:已有 goal.md 优先;否则据输入文件名派生(数据驱动流程不因缺目标而硬停)。
    派生标签**不固化**成研究目标:引擎会据 topic 写 goal.md,但若本来没有人工目标,
    跑完即清掉——否则下一轮 discover 会据这个文件名派生串误触发 lit-loop(发现应保持纯粹)。
    """
    from psyclaw.tasks import get_goal, goal_path
    from psyclaw.workflows import get_workflow, run_workflow
    wf_id = _ACTION_WF.get(item["action"])
    if not wf_id:
        return 1
    goal_before = get_goal(project_dir)
    topic = goal_before or _derive_topic(item)
    rc = run_workflow(get_workflow(wf_id), topic=topic, project_dir=project_dir,
                      auto=True, seed=item.get("seed"))
    if not goal_before:                       # 本无人工目标 → 清掉引擎落下的派生 goal.md
        gp = goal_path(project_dir)
        try:                                  # 仅清理:失败也不应影响本轮验收结论
            if gp.exists():
                gp.unlink()
        except OSError:
            pass
    return rc


# ---------------------------------------------------------------------------
# 主回路(驱动:sense → dispatch → verify → record → decide)
# ---------------------------------------------------------------------------

def _write_decision_request(project: Path, item: dict) -> None:
    body = ("# 决策请求 — auto-loop 被门禁拦截\n\n"
            f"- 时间:{_now()}\n- 拦截项:{item['title']}\n- 原因:{item['reason']}\n\n"
            "auto-loop 不能替你跨过这道门禁。请人工处理后重跑 `psyclaw auto-loop`:\n"
            "- 澄清未完 → 先 `psyclaw clarify`(把 17 槽位补全)。\n")
    (project / "notes" / "decision_request.md").write_text(body, encoding="utf-8")


def _write_blocked(project: Path, item: dict, verdict: dict) -> None:
    p = project / "notes" / "blocked.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    entry = (f"\n## {_now()} — {item['title']} 验收未过(已跳过,换下一个任务)\n"
             f"- 行动:{item['action']}\n"
             f"- 原因:{'; '.join(verdict.get('reasons') or ['未知']) }\n")
    with p.open("a", encoding="utf-8") as f:
        f.write(entry)


def skill_hints(action: str, project_dir: str = ".",
                skills: list | None = None, top_k: int = 3) -> list[str]:
    """给某待办 action 匹配相关**外部技能包**名(AcademicForge/AJS 等已装的)。

    纯指路:auto-loop 派发的是仓内 workflow,这些 Agent Skill 是给宿主 Agent 读的 markdown,
    本函数只把「装了哪些相关技能包」呈现给人,不改派发/验收。无相关/未装 → 返回 []。
    """
    try:
        from psyclaw.skills.recommend import recommend_skills
        recs = recommend_skills(action, skills=skills, project_dir=project_dir,
                                top_k=top_k)
    except Exception:  # noqa: BLE001  # 推荐失败不影响感知主流程
        return []
    return [r["name"] for r in recs]


def _print_sense(backlog: list[dict], state: dict, project_dir: str = ".") -> None:
    from psyclaw import ui
    done = state.get("completed_actions", [])
    skip = state.get("skipped", [])
    line = f"已完成 {len(done)} · 已跳过 {len(skip)} · 迭代 {state.get('iteration', 0)}"
    if not backlog:
        print(ui.dim(f"  ① 感知:无待办({line})"))
        return
    print(ui.accent(f"  ① 感知 — 发现 {len(backlog)} 项待办({line})"))
    # 一次性取外部技能池,避免每个待办各扫一遍 .claude/skills。
    pool: list = []
    try:
        from psyclaw.skills.loader import list_skills
        pool = list_skills(project_dir)
    except Exception:  # noqa: BLE001
        pool = []
    for c in backlog:
        mark = ui.warn("⚠ blocker") if c.get("blocker") else ui.dim(f"P{c['priority']}")
        print(f"     {mark}  {c['title']} — {c['reason']}")
        if not c.get("blocker"):
            hints = skill_hints(c["action"], project_dir, skills=pool)
            if hints:
                print(ui.dim(f"        ↳ 相关技能包:{' · '.join(hints)}"
                             "(psyclaw skills --for 看详情)"))


def run_autoloop(project_dir: str = ".", max_iters: int = 6,
                 auto: bool = False) -> int:
    """跑自主科研回路。

    非 auto:每轮在**任务级**征求确认(派发哪条流程),确认后该流程跑到底;
    auto:全程无人值守。返回 0=正常收敛/到上限;1=被门禁硬停(需人工)。
    """
    from psyclaw import ui
    from psyclaw.loop import _ask_yn, _log

    project = Path(project_dir)
    for sub in ("notes", "outputs", "logs"):
        (project / sub).mkdir(parents=True, exist_ok=True)

    print(ui.panel(
        "Auto-Loop — 自主科研回路(Ralph 式)",
        "每轮:① 感知发现 → ② 派发流程 → ③ 独立验收 → ④ 记状态 → ⑤ 决定下一步\n"
        f"迭代上限 {max_iters} · 模式 {'自动(无人值守)' if auto else 'HITL(任务级确认)'}"))
    state = load_state(project_dir)
    _log(project, f"auto-loop start · max_iters={max_iters} · auto={auto}")

    rc = 0
    while True:
        done_actions = frozenset(state["completed_actions"]) | frozenset(state["skipped"])
        backlog = discover_backlog(project_dir, done_actions)
        print()
        _print_sense(backlog, state, project_dir)

        decision, reason = decide(state, backlog, max_iters)
        if decision == "stop":
            # 仅当确实「因 blocker 而停」(未先撞迭代上限)才写决策请求 + rc=1;
            # decide 优先判 max_iters,故撞上限时即便 backlog 顶是 blocker 也按普通停止收尾。
            if (backlog and backlog[0].get("blocker")
                    and state.get("iteration", 0) < max_iters):
                _write_decision_request(project, backlog[0])
                print(ui.err(f"  ⑤ 停止:{reason}"))
                print(ui.dim("     已写 notes/decision_request.md;处理后重跑 psyclaw auto-loop。"))
                _log(project, f"auto-loop blocked: {reason}")
                rc = 1
            else:
                print(ui.ok(f"  ⑤ 停止:{reason}"))
                _log(project, f"auto-loop stop: {reason}")
            break

        item = select_next(backlog)
        print(ui.accent(f"  ② 派发 — {item['title']}"))
        if not auto and not _ask_yn(f"派发「{item['title']}」并跑到底?"):
            print(ui.dim("  已在派发前暂停。状态已保存,下次 psyclaw auto-loop 从此处续。"))
            break

        _log(project, f"auto-loop dispatch · {item['action']} · {item['title']}")
        # 派发/验收异常不应炸掉整个回路:记为失败、写 blocked、换下一个任务(不空转)。
        try:
            _dispatch(item, project_dir)
            verdict = verify_result(project_dir, item["action"])
        except Exception as exc:  # noqa: BLE001
            verdict = {"passed": False, "workflow": None,
                       "reasons": [f"派发异常:{exc}"]}

        if verdict["passed"]:
            print(ui.ok(f"  ③ 验收通过 — {item['action']}(独立核对落盘产物)"))
        else:
            print(ui.warn(f"  ③ 验收未过 — {'; '.join(verdict['reasons'][:2]) or '未知'}"))
            _write_blocked(project, item, verdict)

        record_iteration(state, item, verdict)
        save_state(state, project_dir)
        print(ui.dim(f"  ④ 记状态 → {state_path(project_dir)}"
                     f"(完成 {len(state['completed_actions'])} · 跳过 {len(state['skipped'])})"))

    _print_final(state, project)
    return rc


def _print_final(state: dict, project: Path) -> None:
    from psyclaw import ui
    print("\n" + ui.accent("Auto-Loop 收尾"))
    done = state.get("completed_actions", [])
    skip = state.get("skipped", [])
    print(f"  完成 {len(done)}:{', '.join(done) or '—'}")
    if skip:
        print(ui.warn(f"  跳过 {len(skip)}:{', '.join(skip)}(详见 notes/blocked.md)"))
    print(ui.dim(f"  状态真源:{state_path(str(project))}  ·  迭代 {state.get('iteration', 0)}"))
