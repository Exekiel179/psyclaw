"""Install, enable and update curated Skill domain packs."""
from __future__ import annotations

import subprocess
from pathlib import Path

import json
import os
import re
import urllib.request
from urllib.parse import urlparse

from psyclaw.skills.state import set_pack_enabled
from psyclaw.skills.install import install_skill_repo, repo_name

PACKS_PATH = Path(__file__).with_name("packs.json")
DEFAULT_CATALOG_URL = "https://raw.githubusercontent.com/Exekiel179/psyclaw/main/psyclaw/skills/packs.json"
_PACK_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}$")
_REF = re.compile(r"[A-Za-z0-9._/-]{1,128}$")
_SPARSE_PART = re.compile(r"[A-Za-z0-9._/-]{1,128}$")


def _valid_source(source: object) -> tuple[bool, str]:
    if not isinstance(source, dict):
        return False, "source 必须是对象"
    parsed = urlparse(str(source.get("url") or ""))
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        return False, "source 必须是 https://github.com URL"
    ref = str(source.get("ref") or "main")
    if not _REF.fullmatch(ref):
        return False, "source ref 无效"
    subdir = str(source.get("subdir") or "").strip("/")
    if subdir and (".." in subdir.split("/") or not _SPARSE_PART.fullmatch(subdir)):
        return False, "source subdir 无效"
    skills = source.get("skills")
    if skills is not None and (not isinstance(skills, list)
                               or not all(_PACK_ID.fullmatch(str(name) or "") for name in skills)):
        return False, "source skills 无效"
    return True, ""


def _valid_pack(pack: object, *, remote: bool) -> tuple[bool, str]:
    if not isinstance(pack, dict):
        return False, "pack 必须是对象"
    if not _PACK_ID.fullmatch(str(pack.get("id") or "")):
        return False, "无效 pack id"
    if remote and (pack.get("required") or pack.get("bundled")):
        return False, "远程 catalog 不得声明 bundled/required"
    skills = pack.get("skills", [])
    if not isinstance(skills, list) or not all(_PACK_ID.fullmatch(str(name) or "") for name in skills):
        return False, "pack skills 无效"
    sources = pack.get("sources", [])
    if not isinstance(sources, list):
        return False, "pack sources 必须是列表"
    for source in sources:
        valid, note = _valid_source(source)
        if not valid:
            return False, note
    return True, ""


def _source_sparse_paths(pack: dict, source: dict) -> list[str]:
    subdir = str(source.get("subdir") or "").strip("/")
    names = source.get("skills", pack.get("skills", []))
    return [f"{subdir}/{name}" if subdir else str(name) for name in names]


def catalog_cache_path() -> Path:
    return Path.home() / ".psyclaw" / "skill-packs" / "catalog.json"


def _read_catalog(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"schema": 1, "packs": []}
    except (OSError, ValueError):
        return {"schema": 1, "packs": []}


def load_pack_catalog() -> dict:
    local = _read_catalog(PACKS_PATH)
    cached = _read_catalog(catalog_cache_path())
    local_packs = local.get("packs", []) if isinstance(local.get("packs"), list) else []
    cached_packs = cached.get("packs", []) if isinstance(cached.get("packs"), list) else []
    merged = {p.get("id"): dict(p) for p in local_packs
              if _valid_pack(p, remote=False)[0]}
    for pack in cached_packs:
        if not _valid_pack(pack, remote=True)[0]:
            continue
        pack_id = pack.get("id")
        # The remotely synchronized catalog cannot replace locked package core.
        if pack_id and not merged.get(pack_id, {}).get("required"):
            merged[pack_id] = dict(pack)
    return {"schema": max(local.get("schema", 1), cached.get("schema", 1)),
            "packs": list(merged.values())}


def sync_pack_catalog(url: str | None = None, *, opener=None) -> dict:
    source = (url or os.environ.get("PSYCLAW_SKILL_PACK_CATALOG") or DEFAULT_CATALOG_URL).strip()
    if not source.startswith("https://"):
        return {"ok": False, "status": "denied", "note": "catalog 只接受 HTTPS"}
    opener = opener or urllib.request.urlopen
    try:
        with opener(source, timeout=20) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            return {"ok": False, "status": "too_large"}
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": "download_error", "note": str(exc)}
    packs = data.get("packs", []) if isinstance(data, dict) else []
    if not isinstance(packs, list):
        return {"ok": False, "status": "invalid_catalog", "note": "packs 必须是列表"}
    for pack in packs:
        valid, note = _valid_pack(pack, remote=True)
        if not valid:
            return {"ok": False, "status": "invalid_catalog", "note": note}
    path = catalog_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    tmp.replace(path)
    return {"ok": True, "status": "synced", "path": str(path),
            "url": source, "count": len(packs)}


def list_packs(project_dir: str = ".") -> list[dict]:
    from psyclaw.skills.state import load_state
    project, global_ = load_state(project_dir, "project"), load_state(project_dir, "global")
    out = []
    for pack in load_pack_catalog().get("packs", []):
        item = dict(pack)
        pack_id = item["id"]
        installed = bool(item.get("bundled")) or pack_id in global_.get("installed_packs", []) or pack_id in project.get("installed_packs", [])
        enabled = bool(item.get("required"))
        reason = "required_core" if enabled else "bundled_default" if item.get("bundled") else "available"
        if item.get("bundled") and not item.get("required"):
            enabled = True
        for state, label in ((global_, "global"), (project, "project")):
            if pack_id in state.get("enabled_packs", []):
                enabled, reason = True, f"{label}_enabled"
            if pack_id in state.get("disabled_packs", []) and not item.get("required"):
                enabled, reason = False, f"{label}_disabled"
        item.update({"installed": installed, "enabled": enabled, "enable_reason": reason,
                     "skill_count": len(item.get("skills", []))})
        out.append(item)
    return out


def _pack(pack_id: str) -> dict | None:
    return next((p for p in load_pack_catalog().get("packs", []) if p.get("id") == pack_id), None)


def pack_root(pack_id: str, project_dir: str = ".", scope: str = "global") -> Path:
    import os
    configured = os.environ.get("PSYCLAW_SKILL_PACK_HOME", "").strip()
    if configured:
        return Path(configured).expanduser().resolve() / pack_id / "skills"
    base = Path.home() if scope == "global" else Path(project_dir).resolve()
    return base / ".psyclaw" / "skill-packs" / pack_id / "skills"


def pack_skill_roots(project_dir: str = ".") -> list[Path]:
    """Return installed non-bundled pack roots for the standard Skill loader."""
    roots: list[Path] = []
    for pack in list_packs(project_dir):
        if not pack.get("installed") or pack.get("bundled"):
            continue
        for scope in ("project", "global"):
            root = pack_root(pack["id"], project_dir, scope)
            if root.is_dir() and root not in roots:
                roots.append(root)
    return roots


def install_pack(pack_id: str, *, project_dir: str = ".", scope: str = "global",
                 mirror: bool | None = None, runner=None, dry_run: bool = False) -> dict:
    if scope not in {"global", "project"}:
        return {"ok": False, "status": "invalid_scope", "scope": scope}
    pack = _pack(pack_id)
    if pack is None:
        return {"ok": False, "status": "not_found", "pack": pack_id}
    results = []
    target = pack_root(pack_id, project_dir, scope)
    if target.parents[1] == Path(target.anchor):
        return {"ok": False, "status": "denied", "pack": pack_id,
                "note": "pack home 不得是文件系统根目录"}
    if target.is_symlink():
        return {"ok": False, "status": "denied", "pack": pack_id,
                "note": "拒绝写入 symlink pack 目录"}
    if dry_run:
        return {"ok": True, "status": "would_install", "pack": pack_id,
                "scope": scope, "bundled": bool(pack.get("bundled")),
                "skills": pack.get("skills", []), "target": str(target)}
    if pack.get("required") and pack.get("bundled"):
        return {"ok": True, "status": "bundled", "pack": pack_id,
                "scope": scope, "enabled": True, "installed": True,
                "skills": pack.get("skills", []), "sources": []}
    for source in pack.get("sources", []):
        url = str(source.get("url") or "")
        result = install_skill_repo(
            url, dest_dir=str(target), mirror=mirror, runner=runner,
            ref=str(source.get("ref") or "main"),
            sparse_paths=_source_sparse_paths(pack, source),
        )
        results.append(result)
    ok = all(item.get("ok") for item in results)
    if not ok:
        return {"ok": False, "status": "partial", "pack": pack_id,
                "scope": scope, "bundled": bool(pack.get("bundled")),
                "enabled": False, "installed": False,
                "skills": pack.get("skills", []), "sources": results}
    activation = set_pack_enabled(pack_id, True, project_dir=project_dir,
                                  scope=scope, installed=ok,
                                  locked=bool(pack.get("required")))
    ok = activation.get("ok", False)
    return {"ok": ok, "status": "installed" if ok else "partial",
            "pack": pack_id, "scope": scope, "bundled": bool(pack.get("bundled")),
            "enabled": bool(activation.get("ok") and activation.get("status") == "enabled"),
            "installed": ok,
            "skills": pack.get("skills", []), "sources": results,
            "activation": activation}


def update_pack(pack_id: str, *, project_dir: str = ".", scope: str = "global",
                dry_run: bool = False, runner=None) -> dict:
    if scope not in {"global", "project"}:
        return {"ok": False, "status": "invalid_scope", "scope": scope}
    pack = _pack(pack_id)
    if pack is None:
        return {"ok": False, "status": "not_found", "pack": pack_id}
    runner = runner or subprocess.run
    results = []
    root = pack_root(pack_id, project_dir, scope)
    for source in pack.get("sources", []):
        url = str(source.get("url") or "")
        target = root / repo_name(url)
        if target.is_symlink():
            results.append({"ok": False, "name": repo_name(url), "status": "symlink_denied"})
            continue
        if not target.is_dir() or not (target / ".git").exists():
            results.append({"ok": False, "name": repo_name(url), "status": "not_installed"})
            continue
        if dry_run:
            results.append({"ok": True, "name": repo_name(url), "status": "would_update"})
            continue
        try:
            ref = str(source.get("ref") or "main")
            fetch = runner(["git", "-C", str(target), "fetch", "--depth", "1", "origin", ref],
                           capture_output=True, text=True, timeout=300)
            if fetch.returncode != 0:
                results.append({"ok": False, "name": repo_name(url), "status": "error",
                                "note": (fetch.stderr or fetch.stdout)[:300]})
                continue
            checkout = runner(["git", "-C", str(target), "checkout", "--detach", "FETCH_HEAD"],
                              capture_output=True, text=True, timeout=300)
            results.append({"ok": checkout.returncode == 0, "name": repo_name(url),
                            "status": "updated" if checkout.returncode == 0 else "error",
                            "note": (checkout.stderr or checkout.stdout)[:300]})
        except (OSError, subprocess.SubprocessError) as exc:
            results.append({"ok": False, "name": repo_name(url), "status": "error",
                            "note": str(exc)})
    # Bundled-only packs update with the PsyClaw package itself.
    if not pack.get("sources"):
        results.append({"ok": True, "name": pack_id,
                        "status": "bundled" if pack.get("bundled") else "catalog_only",
                        "note": ("随 PsyClaw 包更新" if pack.get("bundled")
                                 else "当前领域包由包内目录声明，无远程 source")})
    return {"ok": all(item.get("ok") for item in results), "status": "checked",
            "pack": pack_id, "scope": scope, "results": results}
