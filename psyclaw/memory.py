"""PsyClaw 三层自进化记忆 — 独特设计。

记忆不是聊天记录,是**方法学偏好的蒸馏**。三层结构:

1. 研究者画像(profile)— 显式、用户可编辑
   领域/语言/软件栈/统计立场。注入每次对话的 system 提示。

2. 决策惯性(habits)— 隐式、自动学习、带半衰期
   每次研究准备/分析选择都计数:{"two_groups_test": {"welch": 5, "classic": 0}}。
   下次同类决策出现时,惯性作为**预填默认**呈现(置信度 = n/(n+2)),
   但永远显示来源、永远可推翻 — 惯性是省力,不是枷锁。
   90 天半衰期衰减:很久不用的偏好自动降权,避免过时立场固化。

3. 教训卡(lessons)— 半自动、HITL 确认
   critic 的 blocking issue 和用户的纠正先进"待确认区",
   用户 /memory confirm 后才生效 — 记忆写入也需要人工确认。
   每张卡:{触发情境, 教训, 来源, 强度}。被再次印证则强度+1,被推翻则归档。

隐私红线:只存方法学偏好,绝不存数据值/被试信息。
存储:~/.psyclaw/memory/{profile,habits,lessons}.json(纯文本,用户可直接审计)。
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

MEM_DIR = Path.home() / ".psyclaw" / "memory"
HALF_LIFE_DAYS = 90.0


def _load(name: str) -> dict:
    p = MEM_DIR / f"{name}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save(name: str, data: dict) -> None:
    MEM_DIR.mkdir(parents=True, exist_ok=True)
    (MEM_DIR / f"{name}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. 画像
# ---------------------------------------------------------------------------

def get_profile() -> dict:
    return _load("profile")


def set_profile(key: str, value: str) -> None:
    prof = get_profile()
    prof[key] = value
    _save("profile", prof)


# ---------------------------------------------------------------------------
# 2. 决策惯性(带半衰期)
# ---------------------------------------------------------------------------

def record_choice(topic: str, choice: str) -> None:
    habits = _load("habits")
    entry = habits.setdefault(topic, {"counts": {}, "last_used": 0})
    entry["counts"][choice] = entry["counts"].get(choice, 0) + 1
    entry["last_used"] = int(time.time())
    _save("habits", habits)


def _decayed(count: float, last_used: int) -> float:
    days = max(0.0, (time.time() - last_used) / 86400.0)
    return count * math.pow(0.5, days / HALF_LIFE_DAYS)


def suggest(topic: str) -> dict | None:
    """返回 {choice, confidence, raw_count} 或 None。confidence = n/(n+2)(衰减后)。"""
    habits = _load("habits")
    entry = habits.get(topic)
    if not entry or not entry["counts"]:
        return None
    best_choice, best_n = max(entry["counts"].items(), key=lambda kv: kv[1])
    n = _decayed(best_n, entry.get("last_used", 0))
    if n < 0.5:
        return None  # 衰减殆尽,不再预填
    return {"choice": best_choice, "confidence": n / (n + 2.0), "raw_count": best_n}


# ---------------------------------------------------------------------------
# 3. 教训卡(HITL 确认)
# ---------------------------------------------------------------------------

def draft_lesson(trigger: str, lesson: str, source: str, kind: str | None = None) -> None:
    """写入待确认区(critic/用户纠正自动调用)。同内容不重复建卡,但**再现即加固**:

    - 已生效(active)的同卡:强度 +1、记 reinforced_ts——兑现「被再次印证则强度 +1」
      (v0.12 feat-066)。同一坑跨会话再踩,说明教训真实且仍成立,注入排序更靠前。
    - 待确认(pending)的同卡:hits +1——确认时用户可见「已再现 n 次」,证据更足。
    - 都没有 → 新建待确认卡。

    kind(可选):环境教训的类别(cmd|module|attr),供「自动失效」再验证时选对探测方式。
    """
    data = _load("lessons")
    for c in data.get("active", []):
        if c.get("trigger") == trigger and c.get("lesson") == lesson:
            c["strength"] = int(c.get("strength", 1)) + 1
            c["reinforced_ts"] = int(time.time())
            _save("lessons", data)
            return
    for c in data.get("pending", []):
        if c.get("trigger") == trigger and c.get("lesson") == lesson:
            c["hits"] = int(c.get("hits", 1)) + 1
            _save("lessons", data)
            return
    card = {"trigger": trigger, "lesson": lesson, "source": source,
            "ts": int(time.time())}
    if kind:
        card["kind"] = kind
    data.setdefault("pending", []).append(card)
    _save("lessons", data)


def draft_lessons(lessons: list) -> int:
    """批量落待确认教训卡,返回**实际落卡数**(feat-087,评审修复)。

    单卡失败跳过继续,不中断批次——此前 CLI agent 路径首卡失败即 break,
    剩余教训全部静默丢失,还按全量报数「N 条已落卡」。REPL 与 CLI 共用本函数,
    落卡语义不再分叉。
    """
    ok = 0
    for le in lessons or []:
        try:
            draft_lesson(le["trigger"], le["lesson"], source="error",
                         kind=le.get("kind"))
            ok += 1
        except Exception:  # noqa: BLE001 — 单卡失败不拖垮批次
            continue
    return ok


def archive_lesson(trigger: str, lesson: str, reason: str = "") -> bool:
    """把一张生效卡归档(active → archived,不删除,可审计/可复原)。

    实现文档承诺的「被推翻则归档」:环境事实过时(如装上了原本缺的库)时自动调用。
    精确按 trigger+lesson 匹配,避免误伤同触发词的其他卡。返回是否命中。
    """
    data = _load("lessons")
    active = data.get("active", [])
    moved = None
    keep = []
    for c in active:
        if moved is None and c.get("trigger") == trigger and c.get("lesson") == lesson:
            moved = c
        else:
            keep.append(c)
    if moved is None:
        return False
    moved["archived_ts"] = int(time.time())
    moved["archived_reason"] = reason
    data["active"] = keep
    data.setdefault("archived", []).append(moved)
    _save("lessons", data)
    return True


def confirm_lesson(index: int) -> bool:
    data = _load("lessons")
    pending = data.get("pending", [])
    if not (0 <= index < len(pending)):
        return False
    card = pending.pop(index)
    # feat-083(评审修复):确认前累计的再现次数(hits)转为初始强度——
    # 此前无条件置 1,再现 5 次的教训确认后反而排在偶发教训后面,
    # 与 feat-066「被再次印证则强度+1」的意图相反。
    try:
        card["strength"] = max(1, int(card.pop("hits", 1)))
    except (TypeError, ValueError):
        card["strength"] = 1
    data.setdefault("active", []).append(card)
    _save("lessons", data)
    return True


def active_lessons(context: str = "") -> list:
    """返回生效教训卡;给了 context 则按触发词过滤。"""
    data = _load("lessons")
    cards = data.get("active", [])
    if not context:
        return cards
    ctx = context.lower()
    return [c for c in cards
            if any(w and w in ctx for w in c["trigger"].lower().split())]


# ---------------------------------------------------------------------------
# system 提示注入
# ---------------------------------------------------------------------------

def memory_prompt(include_lessons: bool = True) -> str:
    """拼装注入 REPL system 提示的记忆段(空记忆返回空串)。

    feat-111:REPL 改为逐消息按相关性注入教训(relevant_lessons),调用方传
    include_lessons=False 剥离静态全量注入;默认 True 保持 memory CLI 等
    旧消费方行为不变。
    """
    parts = []
    prof = get_profile()
    if prof:
        parts.append("# 研究者画像(用户长期偏好,可被本次对话覆盖)\n"
                     + "\n".join(f"- {k}: {v}" for k, v in prof.items()))
    habits = _load("habits")
    strong = []
    for topic, entry in habits.items():
        s = suggest(topic)
        if s and s["confidence"] >= 0.6:
            strong.append(f"- {topic} → 惯性偏好 {s['choice']}"
                          f"(置信 {s['confidence']:.0%},可推翻)")
    if strong:
        parts.append("# 决策惯性(自动学习,呈现为默认而非强制)\n" + "\n".join(strong))
    if include_lessons:
        # 强度高(被多次印证)的卡排前:[:10] 截断时优先保住最可靠的教训(feat-066)
        lessons = sorted(active_lessons(), key=lambda c: -int(c.get("strength", 1)))
        if lessons:
            parts.append("# 教训卡(经用户确认的历史教训)\n"
                         + "\n".join(f"- [{c['trigger']}] {c['lesson']}"
                                     for c in lessons[:10]))
    return "\n\n".join(parts)


def relevant_lessons(query: str, top_k: int = 4, always_top: int = 2) -> list[dict]:
    """按当前消息挑教训卡(feat-111:全量注入改相关性检索,治上下文膨胀)。

    - 强度最高的 always_top 张**无条件保底**(python→python3 这类普适环境坑,
      任何任务都可能踩);
    - 其余卡按与 query 的关键词覆盖打分,命中 >0 者取 top_k;
    - 空 query / 无法取关键词 → 回落强度排序前 always_top+top_k 张
      (与旧行为同构但上限更低)。
    """
    cards = sorted(active_lessons(), key=lambda c: -int(c.get("strength", 1)))
    if not cards:
        return []
    base = cards[:always_top]
    rest = cards[always_top:]
    if not (query or "").strip() or not rest:
        return (base + rest)[:always_top + top_k]
    q_kws = _mem_tokens(query)          # feat-114:拉丁+中文二元组,中文不再全盲
    if not q_kws:
        return (base + rest)[:always_top + top_k]
    scored = []
    for c in rest:
        hit = len(q_kws & _mem_tokens(f"{c.get('trigger', '')} {c.get('lesson', '')}"))
        if hit:
            scored.append((hit, c))
    scored.sort(key=lambda x: (-x[0], -int(x[1].get("strength", 1))))
    return base + [c for _, c in scored[:top_k]]


def render_lesson_block(cards: list[dict]) -> str:
    """教训卡 → system 注入块;空列表返回空串。"""
    if not cards:
        return ""
    return ("# 教训卡(历史教训,按相关性检索注入)\n"
            + "\n".join(f"- [{c.get('trigger', '?')}] {c.get('lesson', '')}"
                        for c in cards))


# ---------------------------------------------------------------------------
# 语义记忆(feat-114,蓝图 docs/MEMORY.md)——研究语境下的概念/约定/事实。
# 与情景(archive 原文)、程序(lessons 坑)三分;每张卡 source 指回情景,
# 冲突时回底片裁决。协议:绝不静默覆盖,绝不静默丢弃。
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


def _mem_tokens(s: str) -> set:
    """记忆检索用分词:拉丁关键词 + 中文二元组。

    feat-114 实测:recall.extract_keywords 对纯中文提取为空——教训/语义
    检索对中文查询全盲。CJK 连续段切 bigram 补上(仅记忆层局部,不动
    archive 的 FTS 通道)。"""
    import re as _re
    toks: set = set()
    try:
        from psyclaw.recall import extract_keywords
        toks |= set(extract_keywords(s))
    except Exception:  # noqa: BLE001
        pass
    for run in _re.findall(r"[一-鿿]{2,}", s or ""):
        toks |= {run[i:i + 2] for i in range(len(run) - 1)}
    return toks


def _norm_stmt(s: str) -> str:
    return " ".join((s or "").split())


def record_fact(concept: str, statement: str, scope: str = "project",
                source: str = "", confidence: float = 0.7) -> dict:
    """记一条语义事实。冲突协议(docs/MEMORY.md §六):

    - 同概念同陈述再现 → 强化(strength+1,置信小步上调)——频率是编码信号;
    - 同概念不同陈述 → **时近优先生效但降置信**,旧说法进 history 不删,
      卡标 conflicted(注入时如实带出「曾有不同说法」);
    - 新概念 → 建卡。返回 {status: created|reinforced|conflict, card}。
    """
    concept = (concept or "").strip()
    if not concept or not _norm_stmt(statement):
        return {"status": "rejected", "reason": "概念/陈述为空"}
    data = _load("facts")
    cards = data.setdefault("facts", [])
    key = concept.lower()
    for c in cards:
        if c.get("concept", "").lower() == key and c.get("scope") == scope:
            if _norm_stmt(c.get("statement")) == _norm_stmt(statement):
                c["strength"] = int(c.get("strength", 1)) + 1
                c["confidence"] = min(0.95, float(c.get("confidence", 0.7)) + 0.05)
                c["last_used"] = _now_iso()
                _save("facts", data)
                return {"status": "reinforced", "card": c}
            c.setdefault("history", []).append({
                "statement": c.get("statement"),
                "confidence": c.get("confidence", 0.7),
                "recorded": c.get("recorded", "?")})
            c.update({"statement": statement.strip(),
                      "confidence": min(float(confidence), 0.6),   # 冲突降置信
                      "conflicted": True, "recorded": _now_iso(),
                      "source": source or c.get("source", "")})
            _save("facts", data)
            return {"status": "conflict", "card": c}
    card = {"concept": concept, "statement": statement.strip(), "scope": scope,
            "source": source, "confidence": float(confidence),
            "strength": 1, "use_count": 0, "conflicted": False,
            "recorded": _now_iso(), "last_used": _now_iso(), "history": []}
    cards.append(card)
    _save("facts", data)
    return {"status": "created", "card": card}


def recall_facts(query: str, top_k: int = 4) -> list[dict]:
    """按当前消息检索语义卡(关键词覆盖,与教训卡同方);命中即取用刷新。"""
    data = _load("facts")
    cards = data.get("facts", [])
    if not cards or not (query or "").strip():
        return []
    q_kws = _mem_tokens(query)
    if not q_kws:
        return []
    scored = []
    for c in cards:
        hit = len(q_kws & _mem_tokens(f"{c.get('concept', '')} {c.get('statement', '')}"))
        if hit:
            scored.append((hit, c))
    scored.sort(key=lambda x: (-x[0], -float(x[1].get("confidence", 0))))
    hits = [c for _, c in scored[:top_k]]
    if hits:                                   # 取用即强化(遗忘机制的输入信号)
        now = _now_iso()
        for c in hits:
            c["use_count"] = int(c.get("use_count", 0)) + 1
            c["last_used"] = now
        _save("facts", data)
    return hits


def render_fact_block(cards: list[dict]) -> str:
    """语义卡 → system 注入块;冲突卡如实带出旧说法(知情权衡,不静默)。"""
    if not cards:
        return ""
    lines = ["# 研究语境记忆(语义卡,按相关性检索注入)"]
    for c in cards:
        lines.append(f"- {c['concept']}:{c['statement']}"
                     f"(置信 {float(c.get('confidence', 0.7)):.0%})")
        if c.get("conflicted") and c.get("history"):
            old = c["history"][-1]
            lines.append(f"  ⚠ 曾有不同说法:「{old['statement']}」"
                         "——如与当前任务相关,请向用户确认后以确认为准")
    return "\n".join(lines)


def resolve_fact(concept: str, scope: str = "project") -> bool:
    """人工裁决:接受当前陈述,清除冲突标记(历史保留可追溯)。"""
    data = _load("facts")
    for c in data.get("facts", []):
        if c.get("concept", "").lower() == (concept or "").lower() \
                and c.get("scope") == scope and c.get("conflicted"):
            c["conflicted"] = False
            c["confidence"] = max(float(c.get("confidence", 0.6)), 0.7)
            _save("facts", data)
            return True
    return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def memory_cli(argv: list) -> int:
    if argv and argv[0] == "fact" and len(argv) >= 3:      # feat-114:记语义事实
        r = record_fact(argv[1], " ".join(argv[2:]))
        marks = {"created": "✓ 已记", "reinforced": "✓ 再现强化",
                 "conflict": "⚠ 与既有说法冲突(时近生效已降置信,旧说法保留;"
                             "psyclaw memory resolve <概念> 裁决)"}
        print(f"  {marks.get(r['status'], r['status'])}:"
              f"{argv[1]} → {' '.join(argv[2:])[:60]}")
        return 0
    if argv and argv[0] == "facts":
        cards = _load("facts").get("facts", [])
        if not cards:
            print("  (无语义卡。psyclaw memory fact <概念> <陈述> 记一条)")
        for c in cards:
            flag = " ⚠冲突" if c.get("conflicted") else ""
            print(f"  [{c['scope']}] {c['concept']}:{c['statement'][:70]}"
                  f"(置信 {float(c.get('confidence', 0.7)):.0%},"
                  f"用过 {c.get('use_count', 0)} 次){flag}")
        return 0
    if argv and argv[0] == "conflicts":
        cards = [c for c in _load("facts").get("facts", []) if c.get("conflicted")]
        if not cards:
            print("  (无冲突卡)")
        for c in cards:
            print(f"  ⚠ {c['concept']}:现「{c['statement'][:50]}」")
            for h in c.get("history", [])[-3:]:
                print(f"     曾「{h['statement'][:50]}」({h.get('recorded', '?')})")
            print(f"     裁决:psyclaw memory resolve {c['concept']}(接受现行)")
        return 0
    if argv and argv[0] == "resolve" and len(argv) >= 2:
        ok = resolve_fact(argv[1])
        print("  ✓ 已裁决(接受现行陈述,历史保留)" if ok
              else "  (无该概念的冲突卡)")
        return 0
    if not argv or argv[0] == "list":
        prof = get_profile()
        habits = _load("habits")
        data = _load("lessons")
        print("  ── 画像 ──")
        if prof:
            for k, v in prof.items():
                print(f"    {k}: {v}")
        else:
            print("    (空。psyclaw memory set 领域 发展心理学)")
        print("  ── 决策惯性 ──")
        if habits:
            for topic in habits:
                s = suggest(topic)
                if s:
                    print(f"    {topic}: {s['choice']}(置信 {s['confidence']:.0%},累计 {s['raw_count']} 次)")
        else:
            print("    (空。研究准备与分析选择会自动累积)")
        print("  ── 教训卡 ──")
        for i, c in enumerate(data.get("pending", [])):
            hits = int(c.get("hits", 1))
            tag = f",已再现 {hits} 次" if hits > 1 else ""
            print(f"    [待确认 {i}] ({c['source']}{tag}) {c['lesson']}")
        for c in data.get("active", []):
            print(f"    [生效] [{c['trigger']}] {c['lesson']} (强度 {c.get('strength', 1)})")
        arch = data.get("archived", [])
        if arch:
            print(f"  ── 已归档教训({len(arch)},自动失效/被推翻)──")
            for c in arch[-5:]:
                why = c.get("archived_reason", "")
                print(f"    [归档] [{c['trigger']}] {c['lesson']}" + (f" — {why}" if why else ""))
        if not data.get("pending") and not data.get("active"):
            print("    (空。critic 审查与用户纠正会生成待确认卡)")
        print("\n  存储:~/.psyclaw/memory/(纯 JSON,可直接审计;只存方法学偏好,不存数据)")
        return 0
    if argv[0] == "set" and len(argv) >= 3:
        set_profile(argv[1], " ".join(argv[2:]))
        print(f"  画像已更新:{argv[1]} = {' '.join(argv[2:])}")
        return 0
    if argv[0] == "confirm" and len(argv) >= 2 and argv[1].isdigit():
        ok = confirm_lesson(int(argv[1]))
        print("  教训卡已确认生效。" if ok else "  无此待确认卡。")
        return 0 if ok else 1
    if argv[0] == "lesson" and len(argv) >= 3:
        draft_lesson(argv[1], " ".join(argv[2:]), source="user")
        print("  已写入待确认区(psyclaw memory confirm <序号> 后生效)。")
        return 0
    print("  用法:psyclaw memory [list] | set <键> <值> | lesson <触发词> <教训> | confirm <序号>")
    return 1
