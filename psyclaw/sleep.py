"""睡眠整合(feat-116,蓝图 docs/MEMORY.md §四)——离线记忆固化。

触发三通道:手动 ``psyclaw sleep`` / **REPL 会话结束自动**(sleep_due 判定)/
auto 空闲阶段(留接口)。四步:

1. **重放**:扫描上次睡眠以来的情景轮次(archive 增量),LLM 蒸馏候选
   语义事实与程序教训——**产物一律 pending 待人工确认**(教训走既有
   pending 区,语义卡带 status=pending 不注入);无 LLM 如实跳过,不硬编;
2. **合并**:同触发词的教训聚类,簇 ≥3 且有 LLM 时蒸馏为一条原则卡
   (pending;成员卡不动,确认原则后可归档成员)——feat-112 手工合并的
   自动化;无 LLM 只报告可合并簇数,绝不机械拼接文本;
3. **衰减结算**:apply_decay(休眠/复活/删除,见 feat-115);
4. 状态落盘(last_turn_id / last_sleep),下次增量重放。

诚实纪律:每步产出如实计数;LLM 不可用就少做,绝不用规则硬造"蒸馏"。
"""

from __future__ import annotations

import json
import time

_REPLAY_CAP = 40          # 单次重放最多读的轮次数(控制 LLM 上下文)
_SLEEP_DUE_TURNS = 20     # 距上次睡眠新增 ≥N 轮才值得睡


def _state() -> dict:
    from psyclaw.memory import _load
    return _load("sleep_state")


def _save_state(st: dict) -> None:
    from psyclaw.memory import _save
    _save("sleep_state", st)


def _new_turns(project_dir: str, since_id: int, cap: int = _REPLAY_CAP) -> list[dict]:
    """archive 增量轮次(id > since_id),失败返回 []。"""
    try:
        from psyclaw.recall import ContextArchive
        db = ContextArchive(project_dir)._db()
        rows = db.execute(
            "SELECT id, user_text, reply_text FROM turns WHERE id > ? "
            "ORDER BY id LIMIT ?", (int(since_id), int(cap))).fetchall()
        return [{"id": r[0], "user": r[1] or "", "reply": r[2] or ""} for r in rows]
    except Exception:  # noqa: BLE001
        return []


def sleep_due(project_dir: str = ".", min_turns: int = _SLEEP_DUE_TURNS) -> bool:
    """自上次睡眠以来新增轮次 ≥ min_turns 才触发(会话结束的自动判定)。"""
    try:
        from psyclaw.recall import ContextArchive
        db = ContextArchive(project_dir)._db()
        max_id = db.execute("SELECT COALESCE(MAX(id), 0) FROM turns").fetchone()[0]
    except Exception:  # noqa: BLE001
        return False
    return (int(max_id) - int(_state().get("last_turn_id", 0))) >= min_turns


_REPLAY_TASK = (
    "你是记忆固化器。从下面的研究对话轮次里蒸馏两类**可跨会话复用**的记忆,"
    "输出 JSON(无其他文字):"
    '{"facts": [{"concept": "概念", "statement": "研究语境下的约定/事实"}],'
    ' "lessons": [{"trigger": "触发词", "lesson": "怎么做/别怎么做"}]}。'
    "只收高信号:明确的约定(如缺失码/变量口径/α 水平)、被验证的做法、踩过的坑;"
    "闲聊/一次性细节/不确定的内容一律不收;各最多 5 条;没有就给空列表。")


def _replay(turns: list[dict], provider) -> dict:
    """LLM 蒸馏候选记忆;无 provider/失败返回空(如实跳过,不硬编)。"""
    empty = {"facts": [], "lessons": []}
    if provider is None or not getattr(provider, "api_key", "") or not turns:
        return empty
    convo = "\n\n".join(f"[用户] {t['user'][:600]}\n[助手] {t['reply'][:600]}"
                        for t in turns)
    try:
        from psyclaw.loop import _gen
        raw = _gen(provider, "planner", _REPLAY_TASK, convo[:24000])
        data = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
        return {"facts": list(data.get("facts", []))[:5],
                "lessons": list(data.get("lessons", []))[:5]}
    except Exception:  # noqa: BLE001
        return empty


def _merge_clusters(provider) -> tuple[int, int]:
    """同触发词教训簇 ≥3 → LLM 蒸馏原则卡(pending)。返回 (簇数, 已蒸馏数)。"""
    from psyclaw.memory import _load, draft_lesson
    cards = _load("lessons").get("active", [])
    by_trigger: dict[str, list] = {}
    for c in cards:
        by_trigger.setdefault(c.get("trigger", "?"), []).append(c)
    clusters = {t: cs for t, cs in by_trigger.items() if len(cs) >= 3}
    if not clusters:
        return 0, 0
    if provider is None or not getattr(provider, "api_key", ""):
        return len(clusters), 0          # 无 LLM 只报数,绝不机械拼接
    merged = 0
    for trigger, cs in clusters.items():
        try:
            from psyclaw.loop import _gen
            body = "\n".join(f"- {c['lesson']}" for c in cs[:8])
            out = _gen(provider, "planner",
                       "把下面同主题的具体教训蒸馏成**一条**更通用的原则"
                       "(一句话,不丢关键约束,不要开场白):", body)
            principle = (out or "").strip().splitlines()[0][:200]
            if principle:
                draft_lesson(trigger, f"[睡眠合并原则] {principle}", "sleep")
                merged += 1
        except Exception:  # noqa: BLE001
            continue
    return len(clusters), merged


def run_sleep(project_dir: str = ".", provider=None) -> dict:
    """执行一次睡眠整合,返回诚实报告(每步实际计数)。"""
    from psyclaw.memory import apply_decay, draft_lesson, record_fact
    st = _state()
    turns = _new_turns(project_dir, int(st.get("last_turn_id", 0)))
    distilled = _replay(turns, provider)
    n_facts = 0
    from psyclaw.memory import _load, _save
    for f in distilled["facts"]:
        try:
            concept = str(f.get("concept", ""))
            r = record_fact(concept, str(f.get("statement", "")),
                            source="sleep-replay", confidence=0.5)
            if r["status"] in ("created", "conflict"):
                data = _load("facts")                # 重新载入后按概念定位再标记
                for c in data.get("facts", []):
                    if c.get("concept", "").lower() == concept.lower() \
                            and c.get("source") == "sleep-replay":
                        c["status"] = "pending"      # 待确认,不注入
                _save("facts", data)
                n_facts += 1
        except Exception:  # noqa: BLE001
            continue
    n_lessons = 0
    for le in distilled["lessons"]:
        try:
            draft_lesson(str(le.get("trigger", "sleep")), str(le.get("lesson", "")),
                         source="sleep-replay")      # 进 pending 区,既有 HITL
            n_lessons += 1
        except Exception:  # noqa: BLE001
            continue
    clusters, merged = _merge_clusters(provider)
    decay = apply_decay()
    if turns:
        st["last_turn_id"] = max(t["id"] for t in turns)
    st["last_sleep"] = int(time.time())
    _save_state(st)
    return {"replayed_turns": len(turns), "fact_candidates": n_facts,
            "lesson_candidates": n_lessons, "merge_clusters": clusters,
            "merged": merged, "decay": decay,
            "llm": bool(provider and getattr(provider, "api_key", ""))}


def render_report(rep: dict) -> str:
    d = rep["decay"]
    return ("🌙 睡眠整合:重放 {rt} 轮 → 候选语义 {fc} · 候选教训 {lc}(均待确认);"
            "可合并簇 {mc}(已蒸馏 {m});衰减:休眠 {ld}+{fd} · 清除 {lp}+{fp}"
            "{llm}").format(
        rt=rep["replayed_turns"], fc=rep["fact_candidates"],
        lc=rep["lesson_candidates"], mc=rep["merge_clusters"], m=rep["merged"],
        ld=d["lessons_dormant"], fd=d["facts_dormant"],
        lp=d["lessons_purged"], fp=d["facts_purged"],
        llm="" if rep["llm"] else "(无 LLM:重放/合并已如实跳过)")
