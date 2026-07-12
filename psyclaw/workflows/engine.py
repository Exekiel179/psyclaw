"""Workflow 引擎 — 按声明式 Step 列表跑研究流程,带前置检查 + HITL + 机器可读总验收。

一个 workflow = 有序 Step 列表(纯数据,可被高级用户自由拼装/拆解)。
  Step.gate(ctx) -> (ok, reason)   前置检查;未通过 → fail-closed(除非 optional 则跳过)
  Step.run(ctx)  -> dict           干活;约定把产物路径写进 ctx.artifacts[step.id]

引擎对每个 Step:① 跑 gate(harness 约束)② 跑 run ③ 记 artifact/evidence
④ 非 auto 模式可在步间征求人工确认(HITL)。末尾产机器可读总验收 workflow_summary.json。

设计纪律:引擎只负责"按顺序、带前置检查、可中断地跑步骤 + 记状态",不含任何领域逻辑;
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
    gate:     (ctx) -> (bool, str)  前置检查;None=无前置检查
    optional: True 时检查未通过/出错只跳过该步,不阻断整条流程
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
                 project_dir: str = ".", auto: bool = True,
                 seed: dict | None = None, skip_gates: bool = False,
                 resume: bool = False) -> int:
    """按 workflow 定义跑研究流程。

    workflow: {"id", "name", "research_type", "steps": [Step, ...]}
    seed:     预填 ctx.data 的输入(如 {"effects_csv": "..."}),供需要数据文件的流程用。
    auto:     True 时连续执行(公开默认);False 时每步完成后确认。
    skip_gates: **用户显式选择探索性运行**时跳过前置检查。跳过要留痕:
        每次跳过记 notes/gate_skips.md + 总验收带 gates_skipped 列表,产出按探索性对待
        (区分探索/确证的学术诚信不靠拦,靠标注)。
    resume:   从 .psyclaw/workflows/<id>.json 恢复最后成功步骤;目标、输入或产物不一致时拒绝。
    返回 0=跑通(总验收落 notes/workflow_summary.json);1=fail-closed 中断(前置检查未通过 / 无目标 / 步骤硬失败)。
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
    if resume:
        try:
            results = _restore_checkpoint(ctx, workflow, seed or {})
        except ValueError as exc:
            print(ui.err(f"无法继续流程：{exc}"))
            return 1
        print(ui.ok(f"  ✓ 已恢复 {len(results)} 个已处理步骤"))
    else:
        _write_checkpoint(ctx, workflow, results, status="running")

    processed = {r["id"] for r in results}
    stopped_at: str | None = None
    for i, step in enumerate(steps, 1):
        if step.id in processed:
            print(ui.dim(f"\n{i}/{len(steps)} {step.title} — 已完成，继续点后续步骤"))
            continue
        print("\n" + ui.accent(f"{i}/{len(steps)} {step.title}"))

        # ① harness 前置检查(fail-closed,除非 optional / 用户显式要求跳过)
        if step.gate is not None:
            ok, reason = step.gate(ctx)
            if not ok:
                if skip_gates:
                    print(ui.warn(f"  ⚠ 按你的要求跳过前置检查：{reason}"))
                    print(ui.dim("    产出将按探索性对待;已记 notes/gate_skips.md。"))
                    _record_gate_skip(ctx, workflow, step, reason)
                elif step.optional:
                    print(ui.dim(f"  跳过（可选步骤的前置检查未通过）：{reason}"))
                    results.append({"id": step.id, "status": "skipped", "reason": reason})
                    _write_checkpoint(ctx, workflow, results, status="running")
                    continue
                else:
                    print(ui.err(f"  ✗ 前置检查未通过，流程已暂停：{reason}"))
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
                _write_checkpoint(ctx, workflow, results, status="running")
                continue
            print(ui.err(f"  ✗ 步骤失败:{exc}"))
            ctx.log(f"workflow {workflow['id']} failed at {step.id}: {exc}")
            stopped_at = step.id
            break

        results.append({"id": step.id, "status": "done",
                        "artifact": ctx.artifacts.get(step.id), **out})
        ctx.log(f"workflow {workflow['id']} ✓ {step.id}")
        _write_checkpoint(ctx, workflow, results, status="running")

        # ④ 步间 HITL(末步不问)
        if i < len(steps) and not _ask_continue(ctx, step):
            print(ui.dim("  已在此步暂停。已落盘的产物保留在 notes/ outputs/。"))
            stopped_at = f"after:{step.id}"
            break

    verdict = workflow_verdict(workflow, results, stopped_at)
    _write_summary(ctx, workflow, verdict)
    _write_checkpoint(ctx, workflow, results,
                      status="completed" if verdict["overall_passed"] else "paused",
                      stopped_at=stopped_at)

    print("\n" + (ui.ok("✓ 流程跑通") if verdict["overall_passed"]
                  else ui.warn(f"△ 流程未完整跑通(停在 {stopped_at})")))
    for r in results:
        mark = {"done": ui.ok("✓"), "skipped": ui.dim("·"),
                "error-skipped": ui.warn("⚠")}.get(r["status"], ui.dim("·"))
        print(f"  {mark} {r['id']}" + (f" → {r['artifact']}" if r.get("artifact") else ""))
    return 0 if verdict["overall_passed"] else 1


def _record_gate_skip(ctx: WorkflowContext, workflow: dict, step: Step,
                      reason: str) -> None:
    """用户要求跳过前置检查的留痕:ctx 记入 gates_skipped(进总验收)+ 追加 notes/gate_skips.md。"""
    ctx.data.setdefault("gates_skipped", []).append(
        {"step": step.id, "reason": reason})
    ctx.log(f"workflow {workflow['id']} gate SKIPPED by user at {step.id}: {reason}")
    p = ctx.project / "notes" / "gate_skips.md"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(f"\n## {datetime.now().isoformat(timespec='seconds')} — "
                    f"{workflow['id']} · {step.id}\n"
                    f"- 未通过的前置检查:{reason}\n"
                    f"- 依据:用户显式选择探索性运行(--exploratory);相应产出按**探索性**对待。\n")
    except OSError:
        pass  # 留痕失败不阻断流程


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
        "step_ids": [step.id for step in workflow["steps"]],
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
    if ctx.data.get("gates_skipped"):
        summary["gates_skipped"] = ctx.data["gates_skipped"]
        summary["exploratory"] = True   # 跳过前置检查的产出按探索性对待(标注,不隐瞒)
    out = ctx.project / "notes" / "workflow_summary.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2,
                              default=str), encoding="utf-8")


def checkpoint_path(project: Path, workflow_id: str) -> Path:
    """返回单个 workflow 的可恢复状态路径。"""
    safe_id = "".join(c for c in workflow_id if c.isalnum() or c in "-_") or "workflow"
    return project / ".psyclaw" / "workflows" / f"{safe_id}.json"


def checkpoint_value(project_dir: str, workflow_id: str, key: str) -> Any:
    """读取检查点中的一个 data 值,供 `run ... --resume` 恢复原输入。"""
    path = checkpoint_path(Path(project_dir), workflow_id)
    if not path.exists():
        raise ValueError(f"没有可恢复的检查点：{path}")
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"检查点不可读取：{exc}") from exc
    data = saved.get("data") if isinstance(saved.get("data"), dict) else {}
    value = data.get(key)
    if value in (None, ""):
        raise ValueError(f"检查点没有保存输入 {key}")
    return value


def _write_checkpoint(ctx: WorkflowContext, workflow: dict, results: list[dict],
                      *, status: str, stopped_at: str | None = None) -> None:
    """每步后原子写检查点;不让半写 JSON 冒充可恢复状态。"""
    path = checkpoint_path(ctx.project, workflow["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "workflow": workflow["id"],
        "step_ids": [step.id for step in workflow["steps"]],
        "topic": ctx.topic,
        "status": status,
        "stopped_at": stopped_at,
        "updated": datetime.now().isoformat(timespec="seconds"),
        "results": results,
        "artifacts": ctx.artifacts,
        "data": ctx.data,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                   encoding="utf-8")
    tmp.replace(path)


def _restore_checkpoint(ctx: WorkflowContext, workflow: dict,
                        current_seed: dict) -> list[dict]:
    """恢复并校验检查点;任何目标、输入或产物漂移都要求重新运行。"""
    path = checkpoint_path(ctx.project, workflow["id"])
    if not path.exists():
        raise ValueError(f"没有可恢复的检查点：{path}")
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"检查点不可读取：{exc}") from exc
    if saved.get("workflow") != workflow["id"]:
        raise ValueError("检查点属于其他流程")
    if saved.get("step_ids") != [step.id for step in workflow["steps"]]:
        raise ValueError("流程步骤定义已变化；请不加 --resume 重新运行")
    if saved.get("topic") != ctx.topic:
        raise ValueError("研究目标已变化；请不加 --resume 重新运行")

    saved_data = saved.get("data") if isinstance(saved.get("data"), dict) else {}
    for key, value in current_seed.items():
        if key in saved_data and saved_data[key] != value:
            raise ValueError(f"输入 {key} 已变化；请不加 --resume 重新运行")

    results = saved.get("results")
    if not isinstance(results, list):
        raise ValueError("检查点缺少步骤记录")
    known_steps = {s.id for s in workflow["steps"]}
    if any(not isinstance(r, dict) or r.get("id") not in known_steps for r in results):
        raise ValueError("检查点步骤与当前流程定义不一致")

    artifacts = saved.get("artifacts") if isinstance(saved.get("artifacts"), dict) else {}
    for result in results:
        artifact = result.get("artifact")
        if artifact and not (ctx.project / artifact).exists():
            raise ValueError(f"已完成步骤的产物不存在：{artifact}")

    ctx.data.update(saved_data)
    ctx.data.update(current_seed)
    ctx.artifacts.update(artifacts)
    return results
