# PsyClaw installer for Windows PowerShell.
#
#   irm https://exekiel179.github.io/psyclaw/install.ps1 | iex
#
# Optional environment variables:
#   $env:PSYCLAW_VERSION = "0.29.4"
#   $env:PSYCLAW_REGISTRY = "https://registry.npmjs.org"
#   $env:PSYCLAW_CN = "1"  # use npmmirror; Windows already ships fd/rg in the package

$ErrorActionPreference = "Stop"
$Version = if ($env:PSYCLAW_VERSION) { $env:PSYCLAW_VERSION.TrimStart("v") } else { "0.29.20" }
if ($env:PSYCLAW_CN -eq "1" -or $env:PSYCLAW_CN -eq "true") {
  $Registry = if ($env:PSYCLAW_REGISTRY) { $env:PSYCLAW_REGISTRY } else { "https://registry.npmmirror.com" }
  $env:PSYCLAW_CN = "1"
} else {
  $Registry = if ($env:PSYCLAW_REGISTRY) { $env:PSYCLAW_REGISTRY } else { "https://registry.npmjs.org" }
}

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
if ($LASTEXITCODE -ne 0) {
  Stop-Install "npm install failed."
}

if (-not (Get-Command psyclaw -ErrorAction SilentlyContinue)) {
  Stop-Install "Installation completed but psyclaw is not on PATH."
}
$help = & psyclaw --help 2>&1 | Out-String
if ($help -notmatch [regex]::Escape("v$Version")) {
  Stop-Install "Installed command did not report PsyClaw v$Version."
}

Write-Host "OK PsyClaw v$Version installed." -ForegroundColor Green
if ($env:PSYCLAW_CN -eq "1" -or $Registry -match "npmmirror|taobao|aliyun|tencent") {
  Write-Host ""
  Write-Host "Mainland tip: keep registry on npmmirror (or set PSYCLAW_CN=1) so updates and recommended skill clones use CN-friendly routes. Windows ships fd/rg in-package."
  Write-Host 'Example: Add-Content $HOME\.npmrc "registry=https://registry.npmmirror.com"'
}
Write-Host ""
Write-Host "Next: run psyclaw, configure a provider, and initialize a research project."
