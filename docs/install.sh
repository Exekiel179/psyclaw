#!/bin/sh
# PsyClaw installer for macOS and Linux.
#
#   curl -fsSL https://exekiel179.github.io/psyclaw/install.sh | sh
#
# Optional environment variables:
#   PSYCLAW_VERSION=0.24.0
#   PSYCLAW_REGISTRY=https://registry.npmjs.org
set -eu

VERSION="${PSYCLAW_VERSION:-0.24.0}"
VERSION="${VERSION#v}"
REGISTRY="${PSYCLAW_REGISTRY:-https://registry.npmjs.org}"

say() { printf '\033[36m>\033[0m %s\n' "$1"; }
ok()  { printf '\033[32mOK\033[0m %s\n' "$1"; }
die() { printf '\033[31mERROR\033[0m %s\n' "$1" >&2; exit 1; }

command -v node >/dev/null 2>&1 || die "Node.js >=22.19.0 is required: https://nodejs.org/"
command -v npm >/dev/null 2>&1 || die "npm is required and normally ships with Node.js."
node -e 'const [major,minor]=process.versions.node.split(".").map(Number);process.exit(major>22||(major===22&&minor>=19)?0:1)' \
  || die "Node.js >=22.19.0 is required; found $(node --version)."

say "Installing psyclaw@$VERSION from $REGISTRY ..."
npm install --global --registry "$REGISTRY" "psyclaw@$VERSION"

command -v psyclaw >/dev/null 2>&1 || die "Installation completed but psyclaw is not on PATH."
VERSION_TEXT="$(psyclaw --help 2>&1)"
printf '%s' "$VERSION_TEXT" | grep -F "v$VERSION" >/dev/null \
  || die "Installed command did not report PsyClaw v$VERSION."

ok "PsyClaw v$VERSION installed."
printf '\nNext: run psyclaw, configure a provider, and initialize a research project.\n'
