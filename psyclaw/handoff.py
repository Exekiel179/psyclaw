"""Write a compact, verifiable project handoff for the next session."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def write_handoff(project_dir: str | Path, *, goal: str,
                  next_steps: list[str], completed: list[str] | None = None,
                  blockers: list[str] | None = None, output: str | Path | None = None,
                  generated_at: str | None = None) -> dict:
    root = Path(project_dir).resolve()
    destination = Path(output) if output else root / "HANDOFF.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    timestamp = generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    completed = [str(x).strip() for x in (completed or []) if str(x).strip()]
    next_steps = [str(x).strip() for x in next_steps if str(x).strip()]
    blockers = [str(x).strip() for x in (blockers or []) if str(x).strip()]
    lines = ["# PsyClaw Session Handoff", "", f"- Generated: `{timestamp}`", f"- Project: `{root}`", "",
             "## Goal", "", goal.strip() or "(未填写)", "", "## Completed", ""]
    lines += [f"- {item}" for item in completed] or ["- (none recorded)"]
    lines += ["", "## Next Steps", ""]
    lines += [f"1. {item}" for item in next_steps] or ["1. (none recorded)"]
    lines += ["", "## Blockers", ""]
    lines += [f"- {item}" for item in blockers] or ["- (none recorded)"]
    lines += ["", "## Verification Contract", "",
              "The next session must reread this file, inspect the worktree, and rerun relevant tests before editing.", ""]
    destination.write_text("\n".join(lines), encoding="utf-8")
    manifest = {"format": "psyclaw-handoff-v1", "path": str(destination),
                "project": str(root), "generated": timestamp,
                "goal": goal.strip(), "completed": completed,
                "next_steps": next_steps, "blockers": blockers}
    sidecar = destination.with_suffix(destination.suffix + ".json")
    sidecar.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, **manifest, "sidecar": str(sidecar)}
