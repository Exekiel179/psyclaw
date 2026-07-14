"""任务中间状态外存(feat-135,蓝图 docs/MEMORY.md)——步骤级快照,便于后期召回。

workflow 引擎已有 .psyclaw/workflows/<id>.json 的 checkpoint;本模块把同一
「中间状态外存」能力推广给 chat/agent 的多步任务:每完成一个可命名步骤,
把关键产物/决策快照落 .psyclaw/state/<task>.jsonl(追加,不覆盖历史),
可按 task 召回、可跨会话查阅。

设计:纯 stdlib JSON,append-only(每步一行,保留完整轨迹);快照只存
可序列化的**摘要**(路径/数值/决策),不存原始数据/密钥;fail-safe(写不了不抛)。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

STATE_DIR = ".psyclaw/state"


def _state_path(project_dir: str, task: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (task or "task"))
    return Path(project_dir) / STATE_DIR / f"{safe[:60]}.jsonl"


def _summ(v) -> object:
    """值摘要:长字符串截断,dict/list 递归浅摘——不落原始数据/密钥。"""
    if isinstance(v, str):
        return v if len(v) <= 200 else v[:200] + f"…(+{len(v) - 200})"
    if isinstance(v, dict):
        return {k: _summ(x) for k, x in list(v.items())[:20]}
    if isinstance(v, (list, tuple)):
        return [_summ(x) for x in list(v)[:20]]
    if isinstance(v, (int, float, bool)) or v is None:
        return v
    return str(v)[:200]


def save_step(task: str, step: str, data: dict | None = None,
              project_dir: str = ".", status: str = "done") -> bool:
    """追加一条步骤快照。返回是否写成功(fail-safe)。"""
    try:
        p = _state_path(project_dir, task)
        p.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "task": task,
               "step": step, "status": status,
               "data": {k: _summ(v) for k, v in (data or {}).items()}}
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return True
    except Exception:  # noqa: BLE001
        return False


def load_steps(task: str, project_dir: str = ".") -> list[dict]:
    """读某任务的全部步骤快照(时序);无则空列表。"""
    p = _state_path(project_dir, task)
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def list_tasks(project_dir: str = ".") -> list[dict]:
    """列出有中间状态的任务(名/步数/最后时间/最后步骤),供召回选择。"""
    d = Path(project_dir) / STATE_DIR
    if not d.is_dir():
        return []
    tasks = []
    for f in sorted(d.glob("*.jsonl")):
        steps = load_steps(f.stem, project_dir)
        if steps:
            tasks.append({"task": steps[-1].get("task", f.stem),
                          "n_steps": len(steps), "last_ts": steps[-1].get("ts"),
                          "last_step": steps[-1].get("step")})
    return tasks


def recall_task(task: str, project_dir: str = ".") -> str:
    """把某任务的中间状态渲染成可注入上下文的摘要(便于续做/复盘)。"""
    steps = load_steps(task, project_dir)
    if not steps:
        return ""
    lines = [f"# 任务中间状态回顾:{task}(共 {len(steps)} 步)"]
    for s in steps:
        d = s.get("data") or {}
        kv = "; ".join(f"{k}={v}" for k, v in d.items())
        lines.append(f"- [{s.get('status', '?')}] {s.get('step', '?')}"
                     + (f" — {kv[:160]}" if kv else ""))
    return "\n".join(lines)
