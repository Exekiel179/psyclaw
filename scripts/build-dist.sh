#!/bin/sh
# Cross-platform release builder. Python performs the archive work so the same
# release inputs can be generated on macOS, Linux, or Windows (via PowerShell).
set -eu
cd "$(dirname "$0")/.."
exec "${PYTHON:-python3}" scripts/build_dist.py "$@"
