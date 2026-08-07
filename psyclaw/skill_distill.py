"""Evidence-first trajectory-to-skill staging.

Staging is deliberately separate from bundled prompts: one successful run is
never promoted automatically, and every promotion records replay evidence.
"""
from __future__ import annotations

import json
from pathlib import Path


def stage_lesson(path: str | Path, *, source: str, lesson: str,
                 passed: bool, evidence: list[str] | None = None) -> dict:
    record = {"source": source, "lesson": lesson.strip(), "passed": bool(passed),
              "evidence": list(evidence or []), "status": "pending"}
    if not record["lesson"]:
        raise ValueError("lesson 不能为空")
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def promote_lesson(path: str | Path, *, source: str, replay_passed: bool,
                   reviewer: str = "human") -> dict:
    """Promote exactly one staged source after an explicit replay/review."""
    p = Path(path)
    if not p.exists():
        return {"ok": False, "note": "没有候选教训"}
    lines = p.read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines if line.strip()]
    target = next((r for r in records if r.get("source") == source and r.get("status") == "pending"), None)
    if target is None:
        return {"ok": False, "note": "未找到待确认候选"}
    target["status"] = "promoted" if replay_passed else "rejected"
    target["reviewer"] = reviewer
    target["replay_passed"] = bool(replay_passed)
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")
    return {"ok": bool(replay_passed), "record": target}
