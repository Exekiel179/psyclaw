"""Build PsyClaw source distributions and platform-specific offline bundles."""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
INDEX = "https://mirrors.aliyun.com/pypi/simple/"

MAC_INSTALL = """#!/bin/sh
# PsyClaw offline installer for macOS. Uses bundled wheels only.
set -eu
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
"$PY" -c 'import sys;sys.exit(0 if sys.version_info>=(3,11) else 1)' 2>/dev/null \\
  || { echo "Python 3.11+ is required." >&2; exit 1; }
"$PY" -m pip install --no-index --find-links wheels psyclaw
echo "PsyClaw installed. Run: psyclaw doctor"
"""

WINDOWS_INSTALL = r"""# PsyClaw offline installer for Windows. Uses bundled wheels only.
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$candidates = @()
if ($env:PYTHON) {
    $candidates += [pscustomobject]@{ Exe = $env:PYTHON; Prefix = @() }
}
$candidates += @(
    [pscustomobject]@{ Exe = 'py'; Prefix = @('-3') }
    [pscustomobject]@{ Exe = 'python'; Prefix = @() }
    [pscustomobject]@{ Exe = 'python3'; Prefix = @() }
)
$python = $null
foreach ($candidate in $candidates) {
    $exe = $candidate.Exe
    $prefix = @($candidate.Prefix)
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
    & $exe @prefix -c 'import sys;sys.exit(0 if sys.version_info>=(3,11) else 1)'
    if ($LASTEXITCODE -eq 0) { $python = $candidate; break }
}
if (-not $python) { throw 'Python 3.11+ is required. Install it from python.org first.' }
$exe = $python.Exe
$prefix = @($python.Prefix)
& $exe @prefix -m pip install --no-index --find-links wheels psyclaw
if ($LASTEXITCODE -ne 0) { throw "pip install failed with exit code $LASTEXITCODE" }
Write-Host 'PsyClaw installed. Run: psyclaw doctor' -ForegroundColor Green
"""


def version() -> str:
    init_text = (ROOT / "psyclaw" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', init_text)
    if not match:
        raise RuntimeError("Cannot find psyclaw.__version__")
    value = match.group(1)
    project_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    if f'version = "{value}"' not in project_text:
        raise RuntimeError("pyproject.toml and psyclaw.__version__ disagree")
    return value


def run(argv: list[str]) -> None:
    print("+", " ".join(argv), flush=True)
    subprocess.run(argv, cwd=ROOT, check=True)


def build_python_packages(ver: str) -> Path:
    DIST.mkdir(exist_ok=True)
    run(["uv", "build", "--out-dir", str(DIST)])
    wheel = DIST / f"psyclaw-{ver}-py3-none-any.whl"
    if not wheel.is_file():
        raise RuntimeError(f"Wheel was not generated: {wheel}")
    with zipfile.ZipFile(wheel) as package:
        data_files = [name for name in package.namelist()
                      if Path(name).suffix.lower() in {".md", ".json", ".yaml", ".yml"}]
    if len(data_files) < 25:
        raise RuntimeError(f"Wheel contains only {len(data_files)} data files")
    print(f"Wheel verified: {len(data_files)} packaged data files")
    return wheel


def download_dependencies(target: Path, index: str) -> None:
    target.mkdir(parents=True, exist_ok=True)
    command = [
        "uv", "run", "--python", "3.12", "--with", "pip", "python", "-m", "pip",
        "download", "-q", "--only-binary=:all:", "-i", index, "-d", str(target),
        "prompt_toolkit>=3.0",
    ]
    try:
        run(command)
    except (subprocess.CalledProcessError, FileNotFoundError):
        run([sys.executable, "-m", "pip", "download", "-q", "--only-binary=:all:",
             "-i", index, "-d", str(target), "prompt_toolkit>=3.0"])
    names = [path.name.lower() for path in target.glob("*.whl")]
    if not any(name.startswith("prompt_toolkit-") for name in names):
        raise RuntimeError("Offline bundle is missing prompt_toolkit")


def stage_bundle(stage: Path, wheel: Path, dependencies: Path, platform: str, ver: str) -> None:
    wheels = stage / "wheels"
    wheels.mkdir(parents=True)
    shutil.copy2(wheel, wheels / wheel.name)
    for dependency in dependencies.glob("*.whl"):
        shutil.copy2(dependency, wheels / dependency.name)
    if platform == "macos":
        installer = stage / "install.sh"
        installer.write_text(MAC_INSTALL, encoding="utf-8", newline="\n")
        installer.chmod(0o755)
        instructions = (
            f"PsyClaw {ver} for macOS (Apple Silicon and Intel)\n\n"
            "Requires Python 3.11+. Extract, then run: sh install.sh\n"
        )
    else:
        (stage / "install.ps1").write_text(
            WINDOWS_INSTALL, encoding="utf-8-sig", newline="\r\n")
        instructions = (
            f"PsyClaw {ver} for Windows 10/11\n\n"
            "Requires Python 3.11+. Extract, right-click install.ps1, and choose Run with PowerShell.\n"
        )
    (stage / "README.txt").write_text(instructions, encoding="utf-8", newline="\n")


def make_archives(wheel: Path, ver: str, index: str) -> tuple[Path, Path]:
    mac_archive = DIST / f"psyclaw-macos-{ver}.tar.gz"
    win_archive = DIST / f"psyclaw-windows-{ver}.zip"
    for archive in (mac_archive, win_archive):
        archive.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="psyclaw-build-") as temp:
        temp_path = Path(temp)
        dependencies = temp_path / "dependencies"
        download_dependencies(dependencies, index)
        mac_stage = temp_path / f"psyclaw-macos-{ver}"
        win_stage = temp_path / f"psyclaw-windows-{ver}"
        stage_bundle(mac_stage, wheel, dependencies, "macos", ver)
        stage_bundle(win_stage, wheel, dependencies, "windows", ver)

        def mac_mode(info: tarfile.TarInfo) -> tarfile.TarInfo:
            if info.name.endswith("/install.sh"):
                info.mode = 0o755
            elif info.isdir():
                info.mode = 0o755
            else:
                info.mode = 0o644
            return info

        with tarfile.open(mac_archive, "w:gz") as archive:
            archive.add(mac_stage, arcname=mac_stage.name, filter=mac_mode)
        with zipfile.ZipFile(win_archive, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in win_stage.rglob("*"):
                if path.is_file():
                    archive.write(path, (Path(win_stage.name) / path.relative_to(win_stage)).as_posix())
    return mac_archive, win_archive


def verify_archives(mac_archive: Path, win_archive: Path, ver: str) -> None:
    with tarfile.open(mac_archive) as archive:
        mac_names = set(archive.getnames())
        mac_installer = archive.getmember(f"psyclaw-macos-{ver}/install.sh")
    with zipfile.ZipFile(win_archive) as archive:
        win_names = set(archive.namelist())
    mac_root = f"psyclaw-macos-{ver}"
    win_root = f"psyclaw-windows-{ver}"
    required_mac = {f"{mac_root}/install.sh", f"{mac_root}/README.txt"}
    required_win = {f"{win_root}/install.ps1", f"{win_root}/README.txt"}
    if not required_mac.issubset(mac_names) or not any("/wheels/psyclaw-" in n for n in mac_names):
        raise RuntimeError("macOS archive verification failed")
    if not mac_installer.mode & 0o111:
        raise RuntimeError("macOS installer is not executable")
    if not required_win.issubset(win_names) or not any("/wheels/psyclaw-" in n for n in win_names):
        raise RuntimeError("Windows archive verification failed")
    print(f"Created {mac_archive.name} ({mac_archive.stat().st_size:,} bytes)")
    print(f"Created {win_archive.name} ({win_archive.stat().st_size:,} bytes)")


def write_checksums(paths: list[Path]) -> Path:
    target = DIST / "SHA256SUMS.txt"
    lines = []
    for path in paths:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.name}")
    target.write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")
    print(f"Created {target.name}")
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", default=INDEX, help="Python package index for bundled wheels")
    args = parser.parse_args()
    ver = version()
    wheel = build_python_packages(ver)
    mac_archive, win_archive = make_archives(wheel, ver, args.index)
    verify_archives(mac_archive, win_archive, ver)
    write_checksums([
        wheel,
        DIST / f"psyclaw-{ver}.tar.gz",
        mac_archive,
        win_archive,
    ])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
