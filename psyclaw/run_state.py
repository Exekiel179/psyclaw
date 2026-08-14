"""统一的可审计运行状态与证据索引（stdlib only）。"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RunState:
    """把目标、上下文、事实、工具回执、产物和待办动作放在一个真源中。"""

    def __init__(self, project_dir: str | Path = ".", data: dict | None = None):
        self.project = Path(project_dir)
        self.path = self.project / ".psyclaw" / "run_state.json"
        self.evidence_path = self.project / ".psyclaw" / "evidence_index.jsonl"
        self.data = data or {
            "schema": "psyclaw-run-state/v1", "run_id": uuid4().hex,
            "updated_at": _now(), "goal": "", "conversation": [],
            "confirmed_facts": [], "tool_receipts": [], "artifacts": [],
            "pending_actions": [],
        }

    @classmethod
    def load(cls, project_dir: str | Path = ".", goal: str = "",
             conversation: list[dict] | None = None) -> "RunState":
        obj = cls(project_dir)
        if obj.path.exists():
            try:
                obj.data = json.loads(obj.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        if goal:
            obj.data["goal"] = goal
        if conversation is not None:
            obj.data["conversation"] = [
                {"role": str(m.get("role", "user")),
                 "content": str(m.get("content", ""))[-4000:]}
                for m in conversation[-8:]
            ]
        obj.save()
        return obj

    def save(self) -> None:
        with _LOCK:
            self.data["updated_at"] = _now()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)

    def record_receipt(self, receipt: dict) -> dict:
        item = dict(receipt)
        item.setdefault("receipt_id", uuid4().hex)
        item.setdefault("timestamp", _now())
        with _LOCK:
            self.data.setdefault("tool_receipts", []).append(item)
            self.save()
            self.evidence_path.parent.mkdir(parents=True, exist_ok=True)
            with self.evidence_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        return item

    def add_artifacts(self, paths: list[str] | tuple[str, ...]) -> None:
        with _LOCK:
            current = self.data.setdefault("artifacts", [])
            for path in paths:
                if path and path not in current:
                    current.append(path)
            self.save()

    def add_pending(self, action: str) -> None:
        with _LOCK:
            pending = self.data.setdefault("pending_actions", [])
            if action and action not in pending:
                pending.append(action)
            self.save()


def infer_artifacts(output: str, project_dir: str | Path = ".") -> list[str]:
    """从工具回执中提取项目内明显的文件路径，供完成契约和审计使用。"""
    root = Path(project_dir).resolve()
    found: list[str] = []
    for token in str(output or "").replace("\n", " ").split():
        token = token.strip("`'\"()[],:;")
        if "/" not in token and "\\" not in token:
            continue
        p = Path(token)
        candidate = p if p.is_absolute() else root / p
        try:
            if candidate.exists() and candidate.resolve().is_relative_to(root):
                found.append(candidate.resolve().relative_to(root).as_posix())
        except OSError:
            continue
    return list(dict.fromkeys(found))
