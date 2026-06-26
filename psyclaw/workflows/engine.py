"""Workflow 引擎 — 按声明式 Step 列表跑研究流程,带 harness 门禁 + HITL + 机器可读总验收。

一个 workflow = 有序 Step 列表(纯数据,可被高级用户自由拼装/拆解)。
  Step.gate(ctx) -> (ok, reason)   前置门禁;不过 → fail-closed(除非 optional 则跳过)
  Step.run(ctx)  -> dict           干活;约定把产物路径写进 ctx.artifacts[step.id]

引擎对每个 Step:① 跑 gate(harness 约束)② 跑 run ③ 记 artifact/evidence
④ 非 auto 模式可在步间征求人工确认(HITL)。末尾产机器可读总验收 workflow_summary.json。

设计纪律:引擎只负责"按顺序、带门禁、可中断地跑步骤 + 记状态",不含任何领域逻辑;
领域逻辑全在各 Step 里,Step 又只是薄壳——委托既有命令 / skill / MCP(见 steps.py)。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


@dataclass
class Step:
    """workflow 的一个步骤。run/gate 都接收 WorkflowContext。

    id:       机器标识(进 artifacts/summary)
    title:    人读标题(进终端 + 进度)
    run:      (ctx) -> dict  干活函数;产物路径写进 ctx.artifacts[id]
    gate:     (ctx) -> (bool, str)  前置门禁;None=无门禁
    optional: True 时门禁不过/出错只跳过该步,不阻断整条流程
    """

    id: str
    title: str
    run: Callable[["WorkflowContext"], dict]
    gate: Callable[["WorkflowContext"], tuple[bool, str]] | None = None
    optional: bool = False


@dataclass
class WorkflowContext:
    """贯穿一次 workflow 运行的状态。Step 之间通过 ctx.data 传中间结果。"""

    topic: str
    project: Path
    provider: Any
    auto: bool = False
    clar: str = ""
    artifacts: dict[str, str] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)

    def log(self, line: str) -> None:
        from psyclaw.loop import _log
        _log(self.project, line)


def _ask_continue(ctx: WorkflowContext, step: Step) -> bool:
    """步间 HITL:非 auto 模式询问是否继续。auto 模式恒继续。"""
    if ctx.auto:
        return True
    from psyclaw.loop import _ask_yn
    return _ask_yn(f"「{step.title}」已完成,继续下一步?")


def run_workflow(workflow: dict, topic: str | None = None,
                 project_dir: str = ".", auto: bool = False,
                 seed: dict | None = None) -> int:
    """按 workflow 定义跑研究流程。

    workflow: {"id", "name", "research_type", "steps": [Step, ...]}
    seed:     预填 ctx.data 的输入(如 {"effects_csv": "..."}),供需要数据文件的流程用。
    返回 0=跑通(总验收落 notes/workflow_summary.json);1=fail-closed 中断(门禁未过 / 无目标 / 步骤硬失败)。
    """
    from psyclaw import config as cfg, ui
    from psyclaw.providers import get_provider
    from psyclaw.tasks import get_goal, set_goal

    project = Path(project_dir)
    for sub in ("notes", "outputs", "logs", "figures", "data/raw", "data/clean"):
        (project / sub).mkdir(parents=True, exist_ok=True)

    goal = topic or get_goal(project)
    if not goal:
        print(ui.err("没有研究目标:把主题作为参数传入,或先 psyclaw goal <目标>。"))
        return 1
    if topic:
        set_goal(topic, project)

    provider = get_provider(cfg.load_config())
    from psyclaw.loop import _read
    ctx = WorkflowContext(
        topic=goal, project=project, provider=provider, auto=auto,
        clar=_read(project / "notes" / "clarification.md"),
    )
    if seed:
        ctx.data.update(seed)

    steps: list[Step] = workflow["steps"]
    print(ui.panel(
        f"{workflow['name']} — {workflow.get('research_type', '')}",
        f"目标:{goal.splitlines()[0][:80]}\n步骤:"
        + " → ".join(s.title for s in steps)))
    ctx.log(f"workflow {workflow['id']} start · provider={provider.name} · goal={goal[:60]}")

    results: list[dict] = []
    stopped_at: str | None = None
    for i, step in enumerate(steps, 1):
        print("\n" + ui.accent(f"{i}/{len(steps)} {step.title}"))

        # ① harness 前置门禁(fail-closed,除非 optional)
        if step.gate is not None:
            ok, reason = step.gate(ctx)
            if not ok:
                if step.optional:
                    print(ui.dim(f"  跳过(门禁未过,可选步骤):{reason}"))
                    results.append({"id": step.id, "status": "skipped", "reason": reason})
                    continue
                print(ui.err(f"  ✗ 门禁拦截:{reason}"))
                ctx.log(f"workflow {workflow['id']} blocked at {step.id}: {reason}")
                stopped_at = step.id
                break

        # ② 跑 step(硬失败 fail-closed,除非 optional)
        try:
            out = step.run(ctx) or {}
        except Exception as exc:  # noqa: BLE001
            if step.optional:
                print(ui.warn(f"  ⚠ 可选步骤出错,跳过:{exc}"))
                results.append({"id": step.id, "status": "error-skipped", "reason": str(exc)})
                continue
            print(ui.err(f"  ✗ 步骤失败:{exc}"))
            ctx.log(f"workflow {workflow['id']} failed at {step.id}: {exc}")
            stopped_at = step.id
            break

        results.append({"id": step.id, "status": "done",
                        "artifact": ctx.artifacts.get(step.id), **out})
        ctx.log(f"workflow {workflow['id']} ✓ {step.id}")

        # ④ 步间 HITL(末步不问)
        if i < len(steps) and not _ask_continue(ctx, step):
            print(ui.dim("  已在此步暂停。已落盘的产物保留在 notes/ outputs/。"))
            stopped_at = f"after:{step.id}"
            break

    verdict = workflow_verdict(workflow, results, stopped_at)
    _write_summary(ctx, workflow, verdict)

    print("\n" + (ui.ok("✓ 流程跑通") if verdict["overall_passed"]
                  else ui.warn(f"△ 流程未完整跑通(停在 {stopped_at})")))
    for r in results:
        mark = {"done": ui.ok("✓"), "skipped": ui.dim("·"),
                "error-skipped": ui.warn("⚠")}.get(r["status"], ui.dim("·"))
        print(f"  {mark} {r['id']}" + (f" → {r['artifact']}" if r.get("artifact") else ""))
    return 0 if verdict["overall_passed"] else 1


def workflow_verdict(workflow: dict, results: list[dict],
                     stopped_at: str | None) -> dict:
    """机器可读总验收(纯函数,可单测)。

    overall_passed = 未中途 fail-closed 中断 且 所有非 optional 步骤都 done。
    """
    by_id = {r["id"]: r for r in results}
    required = [s for s in workflow["steps"] if not s.optional]
    missing = [s.id for s in required if by_id.get(s.id, {}).get("status") != "done"]
    passed = stopped_at is None and not missing
    reasons: list[str] = []
    if stopped_at:
        reasons.append(f"在 {stopped_at} 中断")
    if missing:
        reasons.append(f"必需步骤未完成:{', '.join(missing)}")
    return {
        "workflow": workflow["id"],
        "overall_passed": passed,
        "stopped_at": stopped_at,
        "steps": results,
        "missing_required": missing,
        "reasons": reasons,
    }


def _write_summary(ctx: WorkflowContext, workflow: dict, verdict: dict) -> None:
    summary = {
        "workflow": workflow["id"],
        "name": workflow["name"],
        "research_type": workflow.get("research_type"),
        "topic": ctx.topic.splitlines()[0][:200],
        "artifacts": ctx.artifacts,
        "verdict": verdict,
    }
    out = ctx.project / "notes" / "workflow_summary.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2,
                              default=str), encoding="utf-8")
