"""Compile a material directory into a navigable, evidence-aware Skill draft."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from psyclaw.materials import convert_to_markdown
from psyclaw.evidence import normalize_claim

SUPPORTED = {".md", ".markdown", ".txt", ".text", ".html", ".htm", ".json", ".csv", ".tsv",
             ".pdf", ".docx", ".pptx", ".xlsx"}
VALIDATION_KINDS = {"known", "forward", "contrast", "boundary"}


def _slug(text: str) -> str:
    value = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", text.strip().lower()).strip("-")
    return value or "material"


def _summary(text: str, limit: int = 240) -> str:
    lines = [re.sub(r"^#+\s*", "", line).strip() for line in text.splitlines()]
    body = " ".join(line for line in lines if line and not line.startswith("|") and not line.startswith("---"))
    return body[:limit] + ("..." if len(body) > limit else "")


def compile_materials(source_dir: str | Path, output_dir: str | Path,
                      *, skill_name: str = "Compiled Research Skill") -> dict:
    """Convert local materials and write a replayable navigation bundle."""
    source = Path(source_dir)
    out = Path(output_dir)
    if not source.is_dir():
        return {"ok": False, "status": "missing", "note": f"资料目录不存在:{source}"}
    out_resolved = out.resolve()
    files = sorted(p for p in source.rglob("*")
                   if p.is_file() and p.suffix.lower() in SUPPORTED
                   and not p.resolve().is_relative_to(out_resolved))
    if not files:
        return {"ok": False, "status": "empty", "note": f"未找到可转换资料:{source}"}

    materials_dir = out / "materials"
    materials_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    used_names: set[str] = set()
    for path in files:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        stem = _slug(path.stem)
        name = stem
        suffix = 2
        while name in used_names:
            name = f"{stem}-{suffix}"
            suffix += 1
        used_names.add(name)
        destination = materials_dir / f"{name}.md"
        result = convert_to_markdown(path, destination)
        record = {
            "id": name,
            "source": str(path.resolve()),
            "source_sha256": digest,
            "path": str(destination.relative_to(out)),
            "status": result.get("status", "conversion_failed"),
            "backend": result.get("backend", ""),
            "chars": result.get("chars", 0),
            "summary": _summary(destination.read_text(encoding="utf-8")) if result.get("ok") else "",
        }
        records.append(record)

    successful = [r for r in records if r["status"] == "converted"]
    index = [f"# {skill_name} · Material Index", "", "> Generated deterministically by `psyclaw compile`; verify claims before promotion.", ""]
    for record in records:
        index.extend([
            f"## {record['id']}", "",
            f"- Source: `{record['source']}`",
            f"- SHA-256: `{record['source_sha256']}`",
            f"- Status: `{record['status']}` / backend `{record['backend'] or 'n/a'}`",
            f"- Material: [{record['id']}]({record['path']})",
            f"- Summary: {record['summary'] or '(conversion failed; no summary)' }", "",
        ])
    (out / "INDEX.md").write_text("\n".join(index), encoding="utf-8")

    skill = "\n".join([
        "---", f"name: {_slug(skill_name)}",
        f"description: Evidence-aware Skill compiled from {len(records)} local materials.",
        "status: staged", "evidence_level: v0", "---", "", f"# {skill_name}", "",
        "This is a staging scaffold, not an assertion that the source materials support every rule below.",
        "Promote only after claim-level review and forward-task validation.", "",
        "## Knowledge", "", "- Start with [INDEX.md](INDEX.md) and open only the relevant material.", "",
        "## Taste", "", "- Candidate patterns must cite a material ID and locator before promotion.", "",
        "## Heuristics", "", "- Separate direct evidence, synthesis, inference, and unknowns.", "",
        "## Workflows", "", "1. Route the task to the relevant material in `INDEX.md`.",
        "2. Record claims in a Claim-Evidence ledger.", "3. Run known, forward, contrast, and boundary checks.",
        "4. Keep this Skill at `staged` until a reviewer promotes it.", "",
        "## Anti-patterns", "", "- Do not treat a summary, metadata, or topic match as proof.",
        "- Do not infer a person's private beliefs from public material.", "",
        "## Boundaries", "", f"- Source coverage: {len(successful)}/{len(records)} materials converted successfully.",
        "- Evidence level: v0 (structure only); no rule is promoted automatically.", "",
    ])
    (out / "SKILL.md").write_text(skill, encoding="utf-8")
    (out / "claims.json").write_text("[]\n", encoding="utf-8")
    validation = {kind: {"status": "pending", "evidence": [], "notes": ""}
                  for kind in sorted(VALIDATION_KINDS)}
    (out / "validation.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {"format": "psyclaw-material-compile-v1", "skill_name": skill_name,
                "source_dir": str(source.resolve()), "output_dir": str(out.resolve()),
                "materials": records, "counts": {"total": len(records), "converted": len(successful)}}
    manifest_path = out / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    status = "compiled" if len(successful) == len(records) else "partial"
    return {"ok": True, "status": status, "manifest": str(manifest_path),
            "index": str(out / "INDEX.md"), "skill": str(out / "SKILL.md"), **manifest["counts"]}


def record_validation(bundle_dir: str | Path, *, kind: str, passed: bool,
                      evidence: list[str] | None = None, notes: str = "") -> dict:
    kind = kind.strip().lower()
    if kind not in VALIDATION_KINDS:
        return {"ok": False, "status": "invalid_kind", "note": f"验证类型须为:{', '.join(sorted(VALIDATION_KINDS))}"}
    path = Path(bundle_dir) / "validation.json"
    if not path.is_file():
        return {"ok": False, "status": "missing", "note": f"缺少验证清单:{path}"}
    data = json.loads(path.read_text(encoding="utf-8"))
    data[kind] = {"status": "passed" if passed else "failed",
                  "evidence": [str(x) for x in (evidence or [])], "notes": notes.strip()}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"ok": bool(passed), "status": data[kind]["status"], "kind": kind, "path": str(path)}


def append_claim(bundle_dir: str | Path, *, claim: str, source: str,
                 status: str = "unverified", locator: str = "") -> dict:
    path = Path(bundle_dir) / "claims.json"
    if not path.is_file():
        return {"ok": False, "status": "missing", "note": f"缺少 Claim-Evidence 账本:{path}"}
    item = normalize_claim({"claim": claim, "source": source, "status": status, "locator": locator})
    data = json.loads(path.read_text(encoding="utf-8"))
    if item not in data:
        data.append(item)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "status": "recorded", "claim": item, "path": str(path)}


def promote_compiled_skill(bundle_dir: str | Path, *, reviewer: str) -> dict:
    """Promote only a fully validated bundle with at least one verified claim."""
    bundle = Path(bundle_dir)
    validation_path = bundle / "validation.json"
    claims_path = bundle / "claims.json"
    skill_path = bundle / "SKILL.md"
    missing = [str(p) for p in (validation_path, claims_path, skill_path) if not p.is_file()]
    if missing:
        return {"ok": False, "status": "missing", "missing": missing}
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    incomplete = sorted(kind for kind in VALIDATION_KINDS
                        if validation.get(kind, {}).get("status") != "passed")
    claims = json.loads(claims_path.read_text(encoding="utf-8"))
    verified = [c for c in claims if c.get("status") == "verified" and c.get("source")]
    if incomplete or not verified:
        return {"ok": False, "status": "not_ready", "incomplete_checks": incomplete,
                "verified_claims": len(verified),
                "note": "四类验证须全部通过，且至少有一条带来源的 verified claim"}
    text = skill_path.read_text(encoding="utf-8")
    text = re.sub(r"^status:\s*staged$", "status: promoted", text, count=1, flags=re.M)
    text = re.sub(r"^evidence_level:\s*v0$", "evidence_level: v3", text, count=1, flags=re.M)
    text += f"\n## Promotion\n\n- Reviewer: {reviewer}\n- Verified claims: {len(verified)}\n"
    skill_path.write_text(text, encoding="utf-8")
    return {"ok": True, "status": "promoted", "evidence_level": "v3",
            "verified_claims": len(verified), "skill": str(skill_path)}
