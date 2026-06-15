#!/usr/bin/env bash
# nostop.sh — PsyClaw 过夜自主循环 (macOS / Linux)。nostop.ps1 的 bash 等价版。
# 编码轮：每轮选 TODO.md 一个任务→实现→测试→提交，跑到额度耗尽才停。
# 用法:  cd ~/psyclaw && ./nostop.sh        (首次需 chmod +x nostop.sh)
# 停止:  Ctrl-C；或额度跑完连续失败后自动退出。
# 建议在 tmux 里跑，Mac 防休眠见文末注释。

set -o pipefail   # 不用 set -u：macOS 自带 bash 3.2 在失败分支会误报 unbound variable 打死整个循环
cd "$(dirname "$0")"
mkdir -p logs

# ─── 可调参数（对应 nostop.ps1）────────────────────────────────
MODE="acceptEdits"          # acceptEdits(安全默认) | auto | skip(危险,仅容器内)
MODEL="claude-opus-4-8"     # 改用 Opus 4.8（更强推理；订阅额度消耗更快）
FALLBACK="sonnet"           # 过载自动降级；置空字符串关闭
MAX_TURNS=150               # 单轮上限，防失控；循环本身不受限（80 对大任务偏紧）
MAX_FAILS=5                 # 连续失败这么多次≈额度耗尽，自动退出
COOLDOWN=30                 # 失败后退避秒数(指数退避，封顶 300s)
# ───────────────────────────────────────────────────────────────

case "$MODE" in
  skip) PERM=(--dangerously-skip-permissions) ;;
  auto) PERM=(--permission-mode auto) ;;
  *)    PERM=(--permission-mode acceptEdits) ;;
esac

command -v format-claude-stream >/dev/null 2>&1 && HAVE_FMT=1 || HAVE_FMT=0
PROMPT="$(cat PROMPT.md)"
ITER=0; FAILS=0

while true; do
  ITER=$((ITER+1))
  STAMP=$(date +%Y%m%d_%H%M%S)
  if [ "$HAVE_FMT" = 1 ]; then LOG="logs/$STAMP.jsonl"; else LOG="logs/$STAMP.log"; fi
  echo "═══════════════════════════════════════════════════════"
  echo "  nostop · 第 $ITER 轮 · $(date '+%H:%M:%S') · 模式=$MODE 模型=$MODEL · 失败 $FAILS/$MAX_FAILS"
  echo "═══════════════════════════════════════════════════════"

  ARGS=("${PERM[@]}" -p "$PROMPT" --model "$MODEL" --max-turns "$MAX_TURNS")
  [ -n "$FALLBACK" ] && ARGS+=(--fallback-model "$FALLBACK")

  if [ "$HAVE_FMT" = 1 ]; then
    claude "${ARGS[@]}" --output-format stream-json --verbose 2>&1 | tee "$LOG" | format-claude-stream
    grep -q '"is_error":false' "$LOG" && OK=1 || OK=0
  else
    claude "${ARGS[@]}" 2>&1 | tee "$LOG"
    rc=${PIPESTATUS[0]}                       # 紧跟管道取退出码，别放进 $() 子shell(老 bash 会丢)
    if [ "${rc:-1}" -eq 0 ]; then OK=1; else OK=0; fi
  fi

  if [ "$OK" = 1 ]; then
    FAILS=0; sleep 2
  else
    FAILS=$((FAILS+1))
    echo "⚠️  本轮未正常完成（连续失败 $FAILS）。可能额度耗尽/限流/网络。"
    if [ "$FAILS" -ge "$MAX_FAILS" ]; then
      echo "🛑 连续 $MAX_FAILS 次失败，判定额度耗尽，循环退出。共 $ITER 轮。"; break
    fi
    WAIT=$(( COOLDOWN * 2 ** (FAILS-1) )); [ "$WAIT" -gt 300 ] && WAIT=300
    echo "   等待 ${WAIT}s 后重试…"; sleep "$WAIT"
  fi
done

# Mac 整夜运行防休眠：用 caffeinate 包住本脚本——
#   caffeinate -i ./nostop.sh
# 或在 tmux 里：tmux new -s psyclaw  →  caffeinate -i ./nostop.sh  →  Ctrl-B D 分离
