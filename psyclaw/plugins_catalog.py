"""Read-only inventory of Claude Code/Codex/cc-switch installed plugins."""
from __future__ import annotations

import json
from pathlib import Path


def _count_files(root: Path, name: str) -> int:
    try:
        return sum(1 for _ in root.rglob(name))
    except OSError:
        return 0


def _claude_plugins() -> list[dict]:
    path = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for plugin_id, installs in (data.get("plugins") or {}).items():
        if not isinstance(installs, list):
            installs = [installs]
        for item in installs:
            if not isinstance(item, dict):
                continue
            root = Path(str(item.get("installPath") or ""))
            if not root.is_dir():
                continue
            out.append({"id": plugin_id, "name": plugin_id.split("@", 1)[0],
                        "host": "claude-code", "scope": item.get("scope", "user"),
                        "path": str(root), "version": item.get("version", ""),
                        "skills": _count_files(root, "SKILL.md"),
                        "commands": _count_files(root, "*.md")})
    return out


def _cc_switch() -> list[dict]:
    root = Path.home() / ".cc-switch"
    if not root.is_dir():
        return []
    skills = root / "skills"
    return [{"id": "cc-switch", "name": "cc-switch", "host": "cc-switch",
             "scope": "global", "path": str(root), "version": "",
             "skills": _count_files(skills, "SKILL.md"),
             "commands": 0,
             "skill_storage": str(skills) if skills.is_dir() else ""}]


def _codex_plugins() -> list[dict]:
    roots = [Path.home() / ".codex" / ".tmp" / "marketplaces",
             Path.home() / ".codex" / "plugins"]
    out = []
    seen: set[str] = set()
    for base in roots:
        if not base.is_dir():
            continue
        try:
            dirs = sorted(p for p in base.iterdir() if p.is_dir())
        except OSError:
            continue
        for root in dirs:
            if str(root) in seen or root.name.startswith("."):
                continue
            if not (root / "skills").is_dir() and not (root / ".codex-plugin").exists():
                continue
            seen.add(str(root))
            out.append({"id": root.name, "name": root.name, "host": "codex",
                        "scope": "global", "path": str(root), "version": "",
                        "skills": _count_files(root, "SKILL.md"), "commands": 0})
    return out


def discover_plugins(project_dir: str = ".") -> list[dict]:
    """Return plugin metadata only; never imports plugin code."""
    return _claude_plugins() + _codex_plugins() + _cc_switch()
