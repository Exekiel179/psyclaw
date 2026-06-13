"""对话审计 — auditor agent 逐轮评估回答质量(fail-closed)。

- 每轮(可选开启)把「用户问题 + 助手回答」交给 auditor agent 打分;
- 行首标记机器解析:`SCORE: <0-100>` + `AUDIT_VERDICT: PASS|IMPROVE`,
  解析不到一律按 IMPROVE 处理(与 critic 的 VERDICT 同款纪律);
- 审计记录追加 `.psyclaw/audits/audit_log.md`;
- SCORE < 80 时把首条改进建议草拟成教训卡(psyclaw.memory.draft_lesson,
  待人工 confirm 后才进入长期记忆)。

注意:开启逐轮审计意味着每轮多一次 LLM 调用(成本约翻倍),
因此 REPL 默认关,用 /audit on 显式开启。
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from psyclaw import ui

SCORE_RE = re.compile(r"(?m)^\s*SCORE\s*[::]\s*(\d{1,3})")
VERDICT_RE = re.compile(r"(?m)^\s*AUDIT_VERDICT\s*[::]\s*(PASS|IMPROVE)",
                        re.IGNORECASE)
IMPROVE_LINE_RE = re.compile(r"(?m)^改进\s*[::]?\s*(.+)$")
PASS_SCORE = 80


def parse_audit(text: str) -> tuple[int | None, str]:
    """解析 (score, verdict)。fail-closed:解析不到 → (None, IMPROVE)。"""
    m_score = None
    for m in SCORE_RE.finditer(text or ""):
        m_score = m
    score = min(int(m_score.group(1)), 100) if m_score else None
    m_verdict = None
    for m in VERDICT_RE.finditer(text or ""):
        m_verdict = m
    verdict = m_verdict.group(1).upper() if m_verdict else "IMPROVE"
    return score, verdict


def run_audit(provider, question: str, reply: str,
              project_dir: str | Path = ".") -> dict:
    """跑一轮审计并落盘。返回 {score, verdict, text}。"""
    from psyclaw.loop import _agent_prompt
    msgs = [{"role": "user", "content":
             f"# 用户问题\n{question}\n\n# 助手回答\n{reply}\n\n按格式审计。"}]
    try:
        text = "".join(provider.chat(msgs, system=_agent_prompt("auditor")))
    except Exception as exc:  # noqa: BLE001
        text = f"[审计失败] {exc}"
    score, verdict = parse_audit(text)

    log = Path(project_dir) / ".psyclaw" / "audits" / "audit_log.md"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        f.write(f"\n## {datetime.now().isoformat(timespec='seconds')}"
                f" · SCORE={score if score is not None else '未解析'}"
                f" · {verdict}\n\n"
                f"**问**:{question[:200]}\n\n{text}\n")

    if verdict == "IMPROVE":
        first = IMPROVE_LINE_RE.search(text or "")
        try:
            from psyclaw.memory import draft_lesson
            draft_lesson("audit-improve",
                         (first.group(1) if first else text[:120])[:120],
                         "auditor")
        except Exception:  # noqa: BLE001
            pass
    return {"score": score, "verdict": verdict, "text": text}


def render_verdict(result: dict) -> str:
    """一行审计结论(REPL 展示)。"""
    score = result["score"]
    s = f"{score}/100" if score is not None else "未解析(按 IMPROVE)"
    line = f"  ⚖ 审计:{s} · {result['verdict']}(详见 .psyclaw/audits/audit_log.md)"
    return ui.ok(line) if result["verdict"] == "PASS" else ui.warn(line)
