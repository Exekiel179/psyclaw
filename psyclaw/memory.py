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

def memory_prompt() -> str:
    """拼装注入 REPL system 提示的记忆段(空记忆返回空串)。"""
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
    # 强度高(被多次印证)的卡排前:[:10] 截断时优先保住最可靠的教训(feat-066)
    lessons = sorted(active_lessons(), key=lambda c: -int(c.get("strength", 1)))
    if lessons:
        parts.append("# 教训卡(经用户确认的历史教训)\n"
                     + "\n".join(f"- [{c['trigger']}] {c['lesson']}" for c in lessons[:10]))
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def memory_cli(argv: list) -> int:
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
