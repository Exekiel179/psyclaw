# Ralph Wiggum 循环 (PowerShell 版) —— 持续向 Claude 喂 PROMPT.md，永不主动停止。
# 设计目标：一直迭代新功能/加固，直到【额度耗尽】才停。
# 用法：在 PowerShell 里  cd F:\Projects\psyclaw ;  .\ralph.ps1
# 停止：Ctrl-C 手动停；或额度跑完后 claude 连续失败，脚本自动退出。
#
# 首次若报"无法加载脚本，因为在此系统上禁止运行脚本"，先执行一次：
#   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

$ErrorActionPreference = "Continue"
Set-Location -Path $PSScriptRoot

$iter      = 0
$fails     = 0
$maxFails  = 5        # 连续失败这么多次 ≈ 额度耗尽/服务不可用，自动退出
$cooldown  = 30       # 失败后退避秒数（指数退避，封顶 300s）

$prompt = Get-Content -Path ".\PROMPT.md" -Raw

while ($true) {
    $iter++
    Write-Host "═══════════════════════════════════════════════════════"
    Write-Host ("  Ralph 循环 · 第 {0} 轮 · {1}  (累计失败 {2}/{3})" -f `
        $iter, (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $fails, $maxFails)
    Write-Host "═══════════════════════════════════════════════════════"

    # 跑一轮；输出同时落盘 ralph.log 便于事后回看
    claude --dangerously-skip-permissions -p $prompt 2>&1 | Tee-Object -FilePath ".\ralph.log" -Append
    $rc = $LASTEXITCODE

    if ($rc -eq 0) {
        $fails = 0                      # 成功一轮就清零失败计数
        Start-Sleep -Seconds 1
    }
    else {
        $fails++
        Write-Host ("⚠️  本轮 claude 退出码 {0}（第 {1} 次连续失败）。可能是额度耗尽/限流/网络。" -f $rc, $fails)
        if ($fails -ge $maxFails) {
            Write-Host ("🛑 连续 {0} 次失败，判定额度已耗尽，循环退出。共跑 {1} 轮。" -f $maxFails, $iter)
            break
        }
        $wait = [Math]::Min($cooldown * [Math]::Pow(2, $fails - 1), 300)
        Write-Host ("   等待 {0}s 后重试…" -f $wait)
        Start-Sleep -Seconds $wait
    }
}
