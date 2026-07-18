# PsyClaw 一键安装(Windows PowerShell)——镜像感知,国内可用。
#
#   irm https://exekiel179.github.io/psyclaw/install.ps1 | iex
#
# 环境变量(都可选):
#   $env:PSYCLAW_VERSION = "v0.15.0"   指定版本 tag
#   $env:PSYCLAW_EXTRAS  = "[stats]"   附带 extra(本机跑统计:[stats];体验:[full])
#   $env:PSYCLAW_CN      = "1"         强制国内镜像(默认探测 GitHub 自动决定;"0" 强制官方)

$ErrorActionPreference = "Stop"
$Repo   = "Exekiel179/psyclaw"
$Tag    = if ($env:PSYCLAW_VERSION) { $env:PSYCLAW_VERSION } else { "v0.15.0" }
$Extras = if ($env:PSYCLAW_EXTRAS)  { $env:PSYCLAW_EXTRAS  } else { "" }
$Cn     = if ($env:PSYCLAW_CN)      { $env:PSYCLAW_CN      } else { "auto" }

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
  Say "使用国内镜像(gitclone.com + aliyun PyPI)"
  $GitUrl = "https://gitclone.com/github.com/$Repo.git"
  $env:UV_DEFAULT_INDEX = "https://mirrors.aliyun.com/pypi/simple/"
  if (-not $env:UV_PYTHON_INSTALL_MIRROR) {
    $env:UV_PYTHON_INSTALL_MIRROR = "https://ghproxy.net/https://github.com/astral-sh/python-build-standalone/releases/download"
  }
} else {
  $GitUrl = "https://github.com/$Repo.git"
  $env:UV_DEFAULT_INDEX = "https://pypi.org/simple"
}

# 2. 确保 uv
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Say "安装 uv ..."
  try { irm https://astral.sh/uv/install.ps1 | iex }
  catch {
    try { pip install -i $env:UV_DEFAULT_INDEX -q uv } catch { Die "uv 安装失败:请手动装 uv(https://docs.astral.sh/uv/)" }
  }
  $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
  if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { Die "uv 装完但不在 PATH:请重开 PowerShell 后重试" }
}
Ok "uv 就绪"

# 3. 安装 psyclaw(官方失败回退镜像)
function Build-Spec($url) {
  if ($Extras) { "psyclaw$Extras @ git+$url@$Tag" } else { "git+$url@$Tag" }
}
Say "安装 psyclaw $Tag $(if($Extras){"(extras: $Extras)"}) ..."
try {
  uv tool install --python 3.12 --force (Build-Spec $GitUrl)
  if ($LASTEXITCODE -ne 0) { throw "exit $LASTEXITCODE" }
} catch {
  if (-not $UseMirror) {
    Say "官方源失败,改用国内镜像重试 ..."
    $env:UV_DEFAULT_INDEX = "https://mirrors.aliyun.com/pypi/simple/"
    uv tool install --python 3.12 --force (Build-Spec "https://gitclone.com/github.com/$Repo.git")
    if ($LASTEXITCODE -ne 0) { Die "安装失败。可手动:uv tool install `"git+$GitUrl@$Tag`"" }
  } else { Die "安装失败。可手动:uv tool install `"git+$GitUrl@$Tag`"" }
}

Ok "PsyClaw $Tag 安装完成"
Write-Host "`n下一步:"
Write-Host "  psyclaw config        # 配 LLM provider / API key"
Write-Host "  psyclaw new 我的研究   # 建一个按文件夹组织的分析,cd 进去开聊"
Write-Host "  psyclaw --help"
if (-not (Get-Command psyclaw -ErrorAction SilentlyContinue)) {
  Write-Host "`n提示:psyclaw 不在当前 PATH,请运行 'uv tool update-shell' 或重开 PowerShell。" -ForegroundColor Yellow
}
