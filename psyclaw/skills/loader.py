"""Skill 加载器（骨架，stdlib only）。

扫描 psyclaw/skills/*/SKILL.md，解析 frontmatter（name/description/category）。
agentskills.io 兼容；正式版直接复用 ARS 的 skills/loader.py + matcher.py。
"""

from __future__ import annotations

from pathlib import Path

SKILLS_DIR = Path(__file__).parent


def _parse_frontmatter(md: str) -> dict:
    meta: dict[str, str] = {}
    if not md.startswith("---"):
        return meta
    end = md.find("---", 3)
    if end == -1:
        return meta
    for line in md[3:end].splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta


def list_skills() -> list[dict]:
    out: list[dict] = []
    for skill_md in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        meta = _parse_frontmatter(skill_md.read_text(encoding="utf-8"))
        out.append({
            "name": meta.get("name", skill_md.parent.name),
            "category": meta.get("category", "domain"),
            "description": meta.get("description", ""),
        })
    return out
