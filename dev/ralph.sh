#!/usr/bin/env bash
# Ralph Wiggum 循环 —— 持续向 Claude 喂 PROMPT.md，永不主动停止。
# 设计目标：一直迭代新功能/加固，直到【额度耗尽】才停。
# 用法：bash ralph.sh   （建议在 tmux/screen 里跑，可整夜/多日运行）
# 停止：Ctrl-C 手动停；或额度跑完后 claude 连续失败，脚本自动退出。

set -uo pipefail
cd "$(dirname "$0")/.."   # 脚本在 dev/,切回仓库根执行

ITER=0
FAILS=0
MAX_FAILS=5          # 连续失败这么多次 ≈ 额度耗尽/服务不可用，自动退出
COOLDOWN=30          # 失败后退避秒数（指数退避上限）

while true; do
  ITER=$((ITER + 1))
  echo "═══════════════════════════════════════════════════════"
  echo "  Ralph 循环 · 第 $ITER 轮 · $(date '+%Y-%m-%d %H:%M:%S')  (累计失败 $FAILS/$MAX_FAILS)"
  echo "═══════════════════════════════════════════════════════"

  # 跑一轮；输出同时落盘便于事后回看。捕获退出码判断是否额度耗尽。
  claude --dangerously-skip-permissions -p "$(cat dev/PROMPT.md)" 2>&1 | tee -a ralph.log
  RC=${PIPESTATUS[0]}

  if [ "$RC" -eq 0 ]; then
    FAILS=0                       # 成功一轮就清零失败计数
    sleep 1
  else
    FAILS=$((FAILS + 1))
    echo "⚠️  本轮 claude 退出码 $RC（第 $FAILS 次连续失败）。可能是额度耗尽/限流/网络。"
    if [ "$FAILS" -ge "$MAX_FAILS" ]; then
      echo "🛑 连续 $MAX_FAILS 次失败，判定额度已耗尽，循环退出。共跑 $ITER 轮。"
      break
    fi
    # 指数退避，给限流/额度恢复留窗口（封顶 5 分钟）
    WAIT=$(( COOLDOWN * 2 ** (FAILS - 1) ))
    [ "$WAIT" -gt 300 ] && WAIT=300
    echo "   等待 ${WAIT}s 后重试…"
    sleep "$WAIT"
  fi
done
