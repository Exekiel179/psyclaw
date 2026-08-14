# PsyClaw 一键安装(Windows PowerShell)——镜像感知,国内可用。
#
#   irm https://exekiel179.github.io/psyclaw/install.ps1 | iex
#
# 环境变量(都可选):
#   $env:PSYCLAW_VERSION = "v0.23.0"   指定版本 tag
#   $env:PSYCLAW_EXTRAS  = "[stats]"   附带 extra(默认值);设为空字符串可裸装,设 [full] 可更全
#   $env:PSYCLAW_CN      = "1"         强制国内镜像(默认探测 GitHub 自动决定;"0" 强制官方)

$ErrorActionPreference = "Stop"
$Repo   = "Exekiel179/psyclaw"
$Tag    = if ($env:PSYCLAW_VERSION) { $env:PSYCLAW_VERSION } else { "v0.23.0" }
$rawExtras = [System.Environment]::GetEnvironmentVariable("PSYCLAW_EXTRAS")
$Extras = if ($null -eq $rawExtras) { "[stats]" } else { $rawExtras }
$Cn     = if ($env:PSYCLAW_CN)      { $env:PSYCLAW_CN      } else { "auto" }
if (-not $env:UV_CACHE_DIR) {
  $env:UV_CACHE_DIR = Join-Path $env:LOCALAPPDATA "PsyClaw\uv-cache"
}

function Show-Banner {
  Write-Host ""
  Write-Host "  ██████"
  Write-Host "  ██  ██"
  Write-Host "  ████  ██"
  Write-Host "  ██    ██"
  Write-Host ""
  Write-Host "  PsyClaw Installer" -ForegroundColor Cyan
  Write-Host "  Your research workflow, with evidence at every step."
  Write-Host ""
}

function Show-Progress($label, [int]$step, [int]$total) {
  $width = 32
  $filled = [Math]::Min($width, [Math]::Max(0, [int](($step / $total) * $width)))
  $bar = ("#" * $filled) + ("-" * ($width - $filled))
  Write-Host ("  - {0} [{1}] {2}/{3}" -f $label, $bar, $step, $total) -ForegroundColor DarkCyan
}

Show-Banner
$specPreview = if ($Extras) {
  "psyclaw$Extras @ git+https://github.com/$Repo.git@$Tag"
} else {
  "git+https://github.com/$Repo.git@$Tag"
}
Write-Host "Install command:" -ForegroundColor DarkGray
Write-Host "  uv tool install --python >=3.11 --force `"$specPreview`"" -ForegroundColor Yellow
Write-Host ""
Write-Host "Choose an action:" -ForegroundColor Cyan
Write-Host ""
Write-Host "  y    Install PsyClaw (default)"
Write-Host "  n    Do nothing"
Write-Host ""

$nonInteractive = $env:PSYCLAW_YES -in @("1", "true", "yes", "y")
if (-not $nonInteractive) {
  $choice = Read-Host "Install PsyClaw? [Y/n]"
  if ($choice -and $choice.Trim().ToLowerInvariant() -notin @("y", "yes")) {
    Write-Host "Nothing changed." -ForegroundColor DarkGray
    exit 0
  }
}
Write-Host ""
Write-Host "Will install PsyClaw." -ForegroundColor Green
Write-Host "This may take a while. Dependencies are installed in an isolated uv tool environment."
Write-Host ""

function Say($m) { Write-Host "▸ $m" -ForegroundColor Cyan }
function Ok($m)  { Write-Host "✓ $m" -ForegroundColor Green }
function Die($m) { Write-Host "✗ $m" -ForegroundColor Red; exit 1 }

# 1. 官方源 vs 国内镜像
function Test-GitHub {
  try { Invoke-WebRequest -Uri "https://github.com" -Method Head -TimeoutSec 5 -UseBasicParsing | Out-Null; return $true }
  catch { return $false }
}
switch ($Cn) {
  "auto"  { $UseMirror = -not (Test-GitHub) }
  { $_ -in "1","true","yes" } { $UseMirror = $true }
  default { $UseMirror = $false }
}
if ($UseMirror) {
  Write-Host "▸ GitHub 不可达,改用第三方镜像 gitclone.com(非官方,代码完整性不保证);Python 依赖走 aliyun PyPI。" -ForegroundColor Yellow
  Write-Host "  不放心可 Ctrl-C,改用官方源手动装(见 README)。" -ForegroundColor Yellow
  $GitUrl = "https://gitclone.com/github.com/$Repo.git"
  $env:UV_DEFAULT_INDEX = "https://mirrors.aliyun.com/pypi/simple/"
  # 注:不自动把 uv 的 Python 下载改道任何第三方代理——经不可信代理执行 interpreter
  # 二进制是供应链风险。uv 拉不到 Python 时,自行装 Python 3.11+(见末尾提示)。
} else {
  $GitUrl = "https://github.com/$Repo.git"
  $env:UV_DEFAULT_INDEX = "https://pypi.org/simple"
}

# 2. 确保 uv
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Say "安装 uv ..."
  # 官方 uv 安装器(Astral 自有域名 https,与 rustup/Homebrew 同一信任模型)
  try { irm https://astral.sh/uv/install.ps1 | iex }
  catch {
    try { pip install -i $env:UV_DEFAULT_INDEX -q uv } catch { Die "uv 安装失败:请手动装 uv(https://docs.astral.sh/uv/)" }
  }
  $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
  if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { Die "uv 装完但不在 PATH:请重开 PowerShell 后重试" }
}
Ok "uv 就绪"
Show-Progress "uv ready" 1 4

# 3. 安装 psyclaw(官方失败回退镜像)
function Build-Spec($url) {
  if ($Extras) { "psyclaw$Extras @ git+$url@$Tag" } else { "git+$url@$Tag" }
}
# --python '>=3.11':优先复用本机已装的 3.11+,避免国内强制从 GitHub 拉 Python
$PyReq = ">=3.11"
Say "安装 psyclaw $Tag $(if($Extras){"(extras: $Extras)"}) ..."
try {
  uv tool install --python $PyReq --force (Build-Spec $GitUrl)
  if ($LASTEXITCODE -ne 0) { throw "exit $LASTEXITCODE" }
} catch {
  if (-not $UseMirror) {
    Write-Host "▸ 官方源失败,改用第三方镜像 gitclone.com(非官方,请自行评估信任)..." -ForegroundColor Yellow
    $env:UV_DEFAULT_INDEX = "https://mirrors.aliyun.com/pypi/simple/"
    uv tool install --python $PyReq --force (Build-Spec "https://gitclone.com/github.com/$Repo.git")
    if ($LASTEXITCODE -ne 0) { Die "安装失败。若缺 Python:先自行装 Python 3.11+(官网/winget),再重试;或手动 uv tool install `"git+$GitUrl@$Tag`"" }
  } else { Die "安装失败。若缺 Python:先自行装 Python 3.11+(官网/winget),再重试;或手动 uv tool install `"git+$GitUrl@$Tag`"" }
}
Show-Progress "resolving packages" 2 4

$toolBin = (& uv tool dir --bin 2>$null | Select-Object -Last 1).Trim()
$toolExe = Join-Path $toolBin "psyclaw.exe"
if (-not (Test-Path -LiteralPath $toolExe)) { Die "安装完成但找不到 psyclaw 命令:请运行 uv tool update-shell 后重试" }
Show-Progress "installing PsyClaw" 3 4
$versionText = (& $toolExe version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $versionText -notmatch [regex]::Escape($Tag.TrimStart("v"))) {
  Die "安装后版本校验失败: $versionText"
}
Ok "PsyClaw $Tag 安装完成 · 版本校验通过"
Show-Progress "verifying installation" 4 4
Write-Host "`n下一步:"
Write-Host "  psyclaw config        # 配 LLM provider / API key"
Write-Host "  psyclaw new 我的研究   # 建一个按文件夹组织的分析,cd 进去开聊"
Write-Host "  psyclaw --help"
if (-not (Get-Command psyclaw -ErrorAction SilentlyContinue)) {
  Write-Host "`n提示:psyclaw 不在当前 PATH,请运行 'uv tool update-shell' 或重开 PowerShell。" -ForegroundColor Yellow
}
