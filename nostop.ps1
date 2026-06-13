# nostop.ps1 — PsyClaw 过夜自主循环 (Windows / PowerShell)
# 基于 Ralph Wiggum 循环 + 唐巧《让 Claude Code 在你睡觉时持续运行》手册。
# 一直迭代到【额度耗尽】才停；每轮选 TODO.md 一个任务→实现→测试→提交。
#
# 用法:  cd F:\Projects\psyclaw ;  .\nostop.ps1
# 停止:  Ctrl-C；或额度跑完 claude 连续失败后自动退出。
# 首次若禁止运行脚本:  Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

# ─── 可调参数 ────────────────────────────────────────────────
# 权限模式:
#   "acceptEdits" = 安全默认。自动接受文件编辑，bash 仍受 .claude/settings.json
#                   的 allow/deny 约束(deny 里的 rm -rf / git push 等被拦)。
#                   建议配合 cc-safe-setup 的 No-Ask-Human hook，避免遇到未授权
#                   命令时挂起等人(见 README 安装步骤)。
#   "auto"        = Sonnet 分类器自动批准安全操作、拦截高风险；headless 下超限自动终止。
#   "skip"        = --dangerously-skip-permissions。永不挂起，但【绕过】settings.json
#                   所有防护。仅在容器/VM 里用，不要在真实机器上长期裸跑。
$Mode      = "acceptEdits"
$Model     = "sonnet"     # 过夜推荐 sonnet(便宜~1.7x)；复杂推理可 "opus"
$MaxTurns  = 50           # 单轮上限，防止一轮失控；循环本身不受此限
$MaxFails  = 5            # 连续失败这么多次 ≈ 额度耗尽，自动退出
$Cooldown  = 30           # 失败后退避秒数(指数退避，封顶 300s)
# ─────────────────────────────────────────────────────────────

$ErrorActionPreference = "Continue"
Set-Location -Path $PSScriptRoot
New-Item -ItemType Directory -Force -Path ".\logs" | Out-Null

switch ($Mode) {
    "skip" { $permArgs = @("--dangerously-skip-permissions") }
    "auto" { $permArgs = @("--permission-mode","auto") }
    default { $permArgs = @("--permission-mode","acceptEdits") }
}

# 若装了 @khanacademy/format-claude-stream，则美化流式输出
$haveFmt = $null -ne (Get-Command format-claude-stream -ErrorAction SilentlyContinue)

$prompt = Get-Content -Path ".\PROMPT.md" -Raw
$iter = 0; $fails = 0

while ($true) {
    $iter++
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $log   = ".\logs\$stamp.jsonl"
    Write-Host "═══════════════════════════════════════════════════════"
    Write-Host ("  nostop · 第 {0} 轮 · {1} · 模式={2} 模型={3} · 失败 {4}/{5}" -f `
        $iter, (Get-Date -Format "HH:mm:ss"), $Mode, $Model, $fails, $MaxFails)
    Write-Host "═══════════════════════════════════════════════════════"

    $args = $permArgs + @(
        "-p", $prompt,
        "--model", $Model,
        "--max-turns", "$MaxTurns",
        "--output-format", "stream-json", "--verbose"
    )

    if ($haveFmt) {
        claude @args 2>&1 | Tee-Object -FilePath $log | format-claude-stream
    } else {
        claude @args 2>&1 | Tee-Object -FilePath $log
    }
    $rc = $LASTEXITCODE

    if ($rc -eq 0) {
        $fails = 0
        Start-Sleep -Seconds 2
    } else {
        $fails++
        Write-Host ("⚠️  本轮退出码 {0}（连续失败 {1}）。可能额度耗尽/限流/网络。" -f $rc, $fails)
        if ($fails -ge $MaxFails) {
            Write-Host ("🛑 连续 {0} 次失败，判定额度耗尽，循环退出。共 {1} 轮。" -f $MaxFails, $iter)
            break
        }
        $wait = [Math]::Min($Cooldown * [Math]::Pow(2, $fails - 1), 300)
        Write-Host ("   等待 {0}s 后重试…" -f $wait)
        Start-Sleep -Seconds $wait
    }
}
