"""Skill enablement state: installed is distinct from enabled."""
from __future__ import annotations

import json
import re
from pathlib import Path

STATE_FILE = ".psyclaw/skill_state.json"
CORE_SKILLS = frozenset({"research-workflow", "paper-review-gates"})


def _path(project_dir: str, scope: str) -> Path:
    return ((Path(project_dir).resolve() if scope == "project" else Path.home()) /
            STATE_FILE)


def _empty() -> dict:
    return {"schema": 1, "enabled_skills": [], "disabled_skills": [],
            "enabled_packs": [], "disabled_packs": [], "installed_packs": [],
            "source_preferences": {}}


def _normalise_state(data: dict) -> dict:
    state = _empty()
    for key in ("enabled_skills", "disabled_skills", "enabled_packs",
                "disabled_packs", "installed_packs"):
        values = data.get(key, [])
        if not isinstance(values, list):
            values = []
        state[key] = sorted({str(value) for value in values
                             if isinstance(value, str)
                             and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", value)})
    preferences = data.get("source_preferences", {})
    if isinstance(preferences, dict):
        state["source_preferences"] = {
            str(name): str(path) for name, path in preferences.items()
            if isinstance(name, str) and isinstance(path, str) and path.strip()
        }
    return state


def load_state(project_dir: str = ".", scope: str = "global") -> dict:
    if scope not in {"global", "project"}:
        return _empty()
    try:
        data = json.loads(_path(project_dir, scope).read_text(encoding="utf-8"))
        return _normalise_state(data) if isinstance(data, dict) else _empty()
    except (OSError, ValueError):
        return _empty()


def _save(state: dict, project_dir: str, scope: str) -> dict:
    path = _path(project_dir, scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    tmp.replace(path)
    return {"ok": True, "path": str(path), "scope": scope}


def set_skill_enabled(name: str, enabled: bool, *, project_dir: str = ".",
                      scope: str = "global") -> dict:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name or ""):
        return {"ok": False, "status": "invalid_name", "name": name}
    if scope not in {"global", "project"}:
        return {"ok": False, "status": "invalid_scope"}
    if name in CORE_SKILLS and not enabled:
        return {"ok": False, "status": "locked_core", "name": name}
    state = load_state(project_dir, scope)
    yes, no = set(state["enabled_skills"]), set(state["disabled_skills"])
    (yes if enabled else no).add(name)
    (no if enabled else yes).discard(name)
    state["enabled_skills"], state["disabled_skills"] = sorted(yes), sorted(no)
    return {**_save(state, project_dir, scope), "status": "enabled" if enabled else "disabled",
            "name": name}


def set_pack_enabled(pack: str, enabled: bool, *, project_dir: str = ".",
                     scope: str = "global", locked: bool = False,
                     installed: bool = True) -> dict:
    if scope not in {"global", "project"}:
        return {"ok": False, "status": "invalid_scope"}
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", pack or ""):
        return {"ok": False, "status": "invalid_pack", "pack": pack}
    if locked and not enabled:
        return {"ok": False, "status": "locked_core", "pack": pack}
    state = load_state(project_dir, scope)
    yes, no = set(state["enabled_packs"]), set(state["disabled_packs"])
    (yes if enabled else no).add(pack)
    (no if enabled else yes).discard(pack)
    state["enabled_packs"], state["disabled_packs"] = sorted(yes), sorted(no)
    installed_packs = set(state.get("installed_packs", []))
    if installed:
        installed_packs.add(pack)
    state["installed_packs"] = sorted(installed_packs)
    return {**_save(state, project_dir, scope), "status": "enabled" if enabled else "disabled",
            "pack": pack}


def resolve_enabled(skill: dict, packs: list[dict], project_dir: str = ".") -> tuple[bool, str]:
    name = skill.get("name", "")
    if name in CORE_SKILLS:
        return True, "locked_core"
    project, global_ = load_state(project_dir, "project"), load_state(project_dir, "global")
    containing = [p["id"] for p in packs if name in p.get("skills", [])]
    for state, label in ((project, "project"), (global_, "global")):
        if name in state["disabled_skills"]:
            return False, f"{label}_disabled"
        if name in state["enabled_skills"]:
            return True, f"{label}_enabled"
        if any(p in state["disabled_packs"] for p in containing):
            return False, f"{label}_pack_disabled"
        if any(p in state["enabled_packs"] for p in containing):
            return True, f"{label}_pack_enabled"
    # Only required core Skills are active with the package. Other bundled
    # files are catalogued but require installing/enabling their domain pack.
    if skill.get("scope") == "builtin":
        required = next((p for p in packs if p.get("required") and name in p.get("skills", [])), None)
        if required:
            return True, "bundled_default"
    return False, "available"


def select_source(name: str, source: str, candidates: list[str], *, project_dir: str = ".",
                  scope: str = "project") -> dict:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name or ""):
        return {"ok": False, "status": "invalid_name", "name": name}
    if scope not in {"global", "project"}:
        return {"ok": False, "status": "invalid_scope"}
    resolved = str(Path(source).expanduser().resolve())
    allowed = {str(Path(item).expanduser().resolve()) for item in candidates}
    if resolved not in allowed:
        return {"ok": False, "status": "invalid_source", "name": name}
    state = load_state(project_dir, scope)
    state.setdefault("source_preferences", {})[name] = resolved
    return {**_save(state, project_dir, scope), "status": "selected",
            "name": name, "source": resolved}


def source_preference(name: str, project_dir: str = ".") -> str:
    selected = ""
    for scope in ("global", "project"):
        value = load_state(project_dir, scope).get("source_preferences", {}).get(name)
        if value:
            selected = str(value)
    return selected
