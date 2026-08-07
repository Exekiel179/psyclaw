"""DOCX render regression helpers.

LibreOffice provides full DOCX -> PDF -> PNG coverage in CI. On macOS,
Quick Look is an explicit first-page fallback so local checks remain useful
without pretending that a thumbnail is a full multi-page validation.
"""
from __future__ import annotations

import hashlib
import json
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render_docx(path: str | Path, output_dir: str | Path) -> dict:
    source = Path(path).resolve()
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if not source.is_file():
        return {"ok": False, "status": "missing", "note": f"文件不存在:{source}"}

    office = shutil.which("soffice") or shutil.which("libreoffice")
    pdftoppm = shutil.which("pdftoppm")
    pages: list[Path] = []
    backend = ""
    coverage = ""
    diagnostics: list[str] = []
    if office and pdftoppm:
        backend, coverage = "libreoffice+poppler", "full"
        with tempfile.TemporaryDirectory(prefix="psyclaw_lo_") as profile:
            cmd = [office, f"-env:UserInstallation=file://{profile}", "--headless",
                   "--convert-to", "pdf", "--outdir", str(out), str(source)]
            result = subprocess.run(cmd, text=True, capture_output=True, check=False)
        diagnostics.extend(x for x in (result.stdout.strip(), result.stderr.strip()) if x)
        pdf = out / f"{source.stem}.pdf"
        if result.returncode != 0 or not pdf.is_file():
            return {"ok": False, "status": "render_failed", "backend": backend,
                    "diagnostics": diagnostics, "note": "LibreOffice 未生成 PDF"}
        prefix = out / "page"
        result = subprocess.run([pdftoppm, "-png", "-r", "144", str(pdf), str(prefix)],
                                text=True, capture_output=True, check=False)
        diagnostics.extend(x for x in (result.stdout.strip(), result.stderr.strip()) if x)
        pages = sorted(out.glob("page-*.png"))
        if result.returncode != 0 or not pages:
            return {"ok": False, "status": "render_failed", "backend": backend,
                    "diagnostics": diagnostics, "note": "Poppler 未生成页面 PNG"}
    elif platform.system() == "Darwin" and shutil.which("qlmanage"):
        backend, coverage = "quicklook", "first_page"
        result = subprocess.run(["qlmanage", "-t", "-s", "1600", "-o", str(out), str(source)],
                                text=True, capture_output=True, check=False)
        diagnostics.extend(x for x in (result.stdout.strip(), result.stderr.strip()) if x)
        pages = sorted(out.glob(f"{source.name}*.png"))
        if result.returncode != 0 or not pages:
            return {"ok": False, "status": "render_failed", "backend": backend,
                    "diagnostics": diagnostics, "note": "Quick Look 未生成缩略图"}
    else:
        return {"ok": False, "status": "renderer_unavailable",
                "note": "需要 LibreOffice+pdftoppm；macOS 可用 Quick Look 做首页降级检查"}

    manifest = {"source": str(source), "source_sha256": _sha256(source),
                "backend": backend, "coverage": coverage,
                "pages": [{"name": p.name, "sha256": _sha256(p)} for p in pages],
                "diagnostics": diagnostics}
    manifest_path = out / "visual_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    return {"ok": True, "status": "rendered", "manifest": str(manifest_path), **manifest}


def compare_visual_manifests(current: dict, baseline: dict) -> dict:
    """Compare key-page render hashes and explain whether coverage also changed."""
    current_pages = {p["name"]: p["sha256"] for p in current.get("pages", [])}
    baseline_pages = {p["name"]: p["sha256"] for p in baseline.get("pages", [])}
    missing = sorted(set(baseline_pages) - set(current_pages))
    added = sorted(set(current_pages) - set(baseline_pages))
    changed = sorted(k for k in current_pages.keys() & baseline_pages
                     if current_pages[k] != baseline_pages[k])
    coverage_changed = current.get("coverage") != baseline.get("coverage")
    return {"ok": not (missing or added or changed or coverage_changed),
            "missing": missing, "added": added, "changed": changed,
            "coverage_changed": coverage_changed}
