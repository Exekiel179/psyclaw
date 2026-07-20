#!/usr/bin/env bash
# plan.sh — PsyClaw 规划轮 (Opus 4.8)。plan.ps1 的 bash 等价版。
# 只规划、refine TODO.md，不写功能代码。
# 用法:  ./plan.sh           # 默认 1 轮
#        ./plan.sh 3         # 连跑 3 轮
# 规划完用 ./nostop.sh (Sonnet) 去实现。

set -uo pipefail
cd "$(dirname "$0")/.."   # 脚本在 dev/,切回仓库根执行
mkdir -p logs

ROUNDS="${1:-1}"
MODEL="claude-opus-4-8"      # 规划用 Opus 4.8(想得深)
MAX_TURNS=40

command -v format-claude-stream >/dev/null 2>&1 && HAVE_FMT=1 || HAVE_FMT=0
PROMPT="$(cat dev/PLAN_PROMPT.md)"

for i in $(seq 1 "$ROUNDS"); do
  STAMP=$(date +%Y%m%d_%H%M%S)
  if [ "$HAVE_FMT" = 1 ]; then LOG="logs/plan_$STAMP.jsonl"; else LOG="logs/plan_$STAMP.log"; fi
  echo "═══════════════════════════════════════════════════════"
  echo "  规划轮(Opus) · 第 $i/$ROUNDS 轮 · $(date '+%H:%M:%S')"
  echo "═══════════════════════════════════════════════════════"

  ARGS=(--permission-mode acceptEdits -p "$PROMPT" --model "$MODEL" --max-turns "$MAX_TURNS")
  if [ "$HAVE_FMT" = 1 ]; then
    claude "${ARGS[@]}" --output-format stream-json --verbose 2>&1 | tee "$LOG" | format-claude-stream
  else
    claude "${ARGS[@]}" 2>&1 | tee "$LOG"
  fi
  sleep 2
done

echo "✅ 规划完成。接下来用 ./nostop.sh (Sonnet) 实现这些任务。"
