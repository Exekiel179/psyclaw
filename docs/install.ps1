# PsyClaw installer for Windows PowerShell.
#
#   irm https://exekiel179.github.io/psyclaw/install.ps1 | iex
#
# Optional environment variables:
#   $env:PSYCLAW_VERSION = "0.24.0"
#   $env:PSYCLAW_REGISTRY = "https://registry.npmjs.org"

$ErrorActionPreference = "Stop"
$Version = if ($env:PSYCLAW_VERSION) { $env:PSYCLAW_VERSION.TrimStart("v") } else { "0.24.0" }
$Registry = if ($env:PSYCLAW_REGISTRY) { $env:PSYCLAW_REGISTRY } else { "https://registry.npmjs.org" }

function Stop-Install([string]$Message) {
  Write-Host "ERROR $Message" -ForegroundColor Red
  exit 1
}

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
  Stop-Install "Node.js >=22.19.0 is required: https://nodejs.org/"
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
  Stop-Install "npm is required and normally ships with Node.js."
}

node -e 'const [major,minor]=process.versions.node.split(".").map(Number);process.exit(major>22||(major===22&&minor>=19)?0:1)'
if ($LASTEXITCODE -ne 0) {
  Stop-Install "Node.js >=22.19.0 is required; found $(node --version)."
}

Write-Host "Installing psyclaw@$Version from $Registry ..." -ForegroundColor Cyan
npm install --global --registry $Registry "psyclaw@$Version"
if ($LASTEXITCODE -ne 0) { Stop-Install "npm installation failed." }

if (-not (Get-Command psyclaw -ErrorAction SilentlyContinue)) {
  Stop-Install "Installation completed but psyclaw is not on PATH."
}
$VersionText = (& psyclaw --help 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or $VersionText -notmatch [regex]::Escape("v$Version")) {
  Stop-Install "Installed command did not report PsyClaw v$Version."
}

Write-Host "OK PsyClaw v$Version installed." -ForegroundColor Green
Write-Host "Next: run psyclaw, configure a provider, and initialize a research project."
