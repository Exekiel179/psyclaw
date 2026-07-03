"""Bundled skill upstream sync.

Bundled PsyClaw skills may include an ``upstream.json`` manifest. The manifest
keeps the adapter SKILL.md small while preserving the original upstream project
layout under ``<skill>/upstream``.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from psyclaw.skills.loader import SKILLS_DIR


MANIFEST = "upstream.json"


@dataclass
class SyncableSkill:
    name: str
    path: Path
    repo: str
    ref: str
    target: Path


def _read_manifest(skill_dir: Path) -> dict | None:
    manifest = skill_dir / MANIFEST
    if not manifest.exists():
        return None
    try:
        return json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def list_syncable_skills(root: Path = SKILLS_DIR) -> list[SyncableSkill]:
    """Return bundled skills with upstream sync manifests."""
    out: list[SyncableSkill] = []
    for skill_md in sorted(root.glob("*/SKILL.md")):
        skill_dir = skill_md.parent
        data = _read_manifest(skill_dir)
        if not data:
            continue
        repo = str(data.get("repo", "")).strip()
        if not repo:
            continue
        ref = str(data.get("ref", "main")).strip() or "main"
        upstream_dir = str(data.get("upstream_dir", "upstream")).strip() or "upstream"
        target = (skill_dir / upstream_dir).resolve()
        base = skill_dir.resolve()
        if base != target and base not in target.parents:
            continue
        out.append(SyncableSkill(
            name=str(data.get("name") or skill_dir.name),
            path=skill_dir,
            repo=repo,
            ref=ref,
            target=target,
        ))
    return out


def _git(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _sync_one(skill: SyncableSkill, dry_run: bool = False) -> dict:
    action = "update" if skill.target.exists() else "clone"
    if dry_run:
        return {"name": skill.name, "ok": True, "action": action,
                "target": str(skill.target), "note": "dry-run"}

    if skill.target.exists() and not (skill.target / ".git").is_dir():
        return {"name": skill.name, "ok": False, "action": action,
                "target": str(skill.target),
                "note": "target exists but is not a git checkout"}

    if not skill.target.exists():
        skill.target.parent.mkdir(parents=True, exist_ok=True)
        res = _git(["clone", "--depth", "1", "--branch", skill.ref,
                    skill.repo, str(skill.target)])
        return {"name": skill.name, "ok": res.returncode == 0, "action": action,
                "target": str(skill.target),
                "note": (res.stderr or res.stdout).strip()}

    # Existing checkout: keep the original project structure, just fast-refresh.
    fetch = _git(["fetch", "--depth", "1", "origin", skill.ref], cwd=skill.target)
    if fetch.returncode != 0:
        return {"name": skill.name, "ok": False, "action": action,
                "target": str(skill.target),
                "note": (fetch.stderr or fetch.stdout).strip()}
    checkout = _git(["checkout", "--detach", "FETCH_HEAD"], cwd=skill.target)
    if checkout.returncode != 0:
        return {"name": skill.name, "ok": False, "action": action,
                "target": str(skill.target),
                "note": (checkout.stderr or checkout.stdout).strip()}
    return {"name": skill.name, "ok": True, "action": action,
            "target": str(skill.target),
            "note": (checkout.stderr or checkout.stdout).strip()}


def sync_skills(name: str | None = None, dry_run: bool = False,
                root: Path = SKILLS_DIR) -> list[dict]:
    """Sync one or all bundled skills that declare ``upstream.json``."""
    syncable = list_syncable_skills(root)
    if name:
        syncable = [s for s in syncable if s.name == name or s.path.name == name]
    return [_sync_one(s, dry_run=dry_run) for s in syncable]
