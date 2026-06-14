# plan.ps1 — PsyClaw 规划轮 (Opus 4.8)。只规划、refine TODO.md，不写功能代码。
# 用法:  cd F:\Projects\psyclaw ;  .\plan.ps1            # 默认跑 1 轮规划
#        .\plan.ps1 -Rounds 3                            # 连跑 3 轮
# 何时用: 新建任务/重排路线/里程碑后。规划完用 nostop.ps1(Sonnet) 去实现。

param(
    [int]$Rounds = 1
)

$ErrorActionPreference = "Continue"
Set-Location -Path $PSScriptRoot
New-Item -ItemType Directory -Force -Path ".\logs" | Out-Null
# 防止 PowerShell 给 format-claude-stream 注入 UTF-8 BOM
$OutputEncoding = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false

$Model    = "claude-opus-4-8"   # 规划用 Opus 4.8(想得深)
$MaxTurns = 40

$haveFmt = $null -ne (Get-Command format-claude-stream -ErrorAction SilentlyContinue)
$prompt  = Get-Content -Path ".\PLAN_PROMPT.md" -Raw

for ($i = 1; $i -le $Rounds; $i++) {
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $ext   = if ($haveFmt) { "jsonl" } else { "log" }
    $log   = ".\logs\plan_$stamp.$ext"
    Write-Host "═══════════════════════════════════════════════════════"
    Write-Host ("  规划轮(Opus) · 第 {0}/{1} 轮 · {2}" -f $i, $Rounds, (Get-Date -Format "HH:mm:ss"))
    Write-Host "═══════════════════════════════════════════════════════"

    $args = @(
        "--permission-mode","acceptEdits",
        "-p", $prompt,
        "--model", $Model,
        "--max-turns", "$MaxTurns"
    )

    if ($haveFmt) {
        claude @args --output-format stream-json --verbose 2>&1 | Tee-Object -FilePath $log | format-claude-stream
    } else {
        claude @args 2>&1 | Tee-Object -FilePath $log
    }
    Start-Sleep -Seconds 2
}

Write-Host "✅ 规划完成。接下来用 .\nostop.ps1 (Sonnet) 实现这些任务。"
