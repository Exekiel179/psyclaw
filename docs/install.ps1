# PsyClaw 一键安装(Windows PowerShell)——镜像感知,国内可用。
#
#   irm https://exekiel179.github.io/psyclaw/install.ps1 | iex
#
# 环境变量(都可选):
#   $env:PSYCLAW_VERSION = "v0.18.1"   指定版本 tag
#   $env:PSYCLAW_EXTRAS  = "[stats]"   附带 extra(本机跑统计:[stats];体验:[full])
#   $env:PSYCLAW_CN      = "1"         强制国内镜像(默认探测 GitHub 自动决定;"0" 强制官方)

$ErrorActionPreference = "Stop"
$Repo   = "Exekiel179/psyclaw"
$Tag    = if ($env:PSYCLAW_VERSION) { $env:PSYCLAW_VERSION } else { "v0.18.1" }
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

Ok "PsyClaw $Tag 安装完成"
Write-Host "`n下一步:"
Write-Host "  psyclaw config        # 配 LLM provider / API key"
Write-Host "  psyclaw new 我的研究   # 建一个按文件夹组织的分析,cd 进去开聊"
Write-Host "  psyclaw --help"
if (-not (Get-Command psyclaw -ErrorAction SilentlyContinue)) {
  Write-Host "`n提示:psyclaw 不在当前 PATH,请运行 'uv tool update-shell' 或重开 PowerShell。" -ForegroundColor Yellow
}
