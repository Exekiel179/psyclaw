#!/usr/bin/env bash
# PsyClaw harness 初始化 / 验证入口 — 干净、可重启 (clean, restartable)。
# 用法: PSYCLAW_PYTHON=C:/Python314/python ./init.sh
# 注: 测试需装好统计栈的解释器 (scipy/pingouin/statsmodels/lifelines/factor_analyzer/semopy)；
#     本机用 C:\Python314\python，msys 默认 python 无统计栈会失败。
set -euo pipefail

PY="${PSYCLAW_PYTHON:-python}"
echo "=== PsyClaw Harness Init ==="
echo "解释器: $PY"

# 1. compile 静态检查 — 快速失败 (fail fast)
echo "--- compile 静态检查 ---"
"$PY" -m compileall -q psyclaw

# 2. 可选 lint / type 检查 (ruff 若已装)
if "$PY" -m ruff --version >/dev/null 2>&1; then
  echo "--- ruff lint ---"
  "$PY" -m ruff check psyclaw || true
fi

# 3. 测试 (pytest) — 统计数值对照 scipy/pingouin 校验
echo "--- pytest ---"
"$PY" -m pytest -q -p no:cacheprovider

# 4. 学术规范门禁自检
echo "--- gates 门禁 ---"
"$PY" -m psyclaw gates || true

echo "=== Verification Complete (clean state) ==="
echo ""
echo "Next steps (restartable — 每轮一任务一提交):"
echo "1. 读 feature_list.json 看各 feature 状态"
echo "2. 读 progress.md / session-handoff.md 接续上下文"
echo "3. 选 ONE 个 status != done 的 feature 动手 (one feature at a time)"
echo "4. 改完重跑 ./init.sh，全绿 + 记录 evidence 后才宣称 done"
