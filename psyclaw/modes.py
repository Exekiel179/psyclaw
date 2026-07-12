"""三种公开交互模式的共享路由:chat / run / auto。

本模块只把稳定的用户意图映射到既有引擎,不承载研究或统计逻辑。旧的
agent/loop/*-loop/auto-loop 命令继续作为兼容入口,但不再构成用户心智模型。
"""

from __future__ import annotations

from pathlib import Path

RUN_TYPES = ("analysis", "meta", "literature", "qualitative")
LEGACY_RUN_TYPES = ("research", "task")

_RUN_ALIASES = {
    "analysis": "analysis", "analyze": "analysis", "analysis-loop": "analysis",
    "meta": "meta", "meta-analysis": "meta", "meta-loop": "meta",
    "literature": "literature", "lit": "literature", "lit-review": "literature",
    "lit-loop": "literature",
    "qualitative": "qualitative", "qual": "qualitative", "qual-loop": "qualitative",
    "research": "research", "full": "research",
    "task": "task", "generic": "task", "loop": "task",
}


def normalize_run_type(kind: str) -> str:
    """把公开类型和旧称归一;未知类型抛出带可用值的 ValueError。"""
    key = (kind or "").strip().lower()
    normalized = _RUN_ALIASES.get(key)
    if normalized:
        return normalized
    raise ValueError(f"未知运行类型:{kind or '(空)'};可用:{', '.join(RUN_TYPES)}")


def _required_target(kind: str, target: str | None) -> str:
    value = (target or "").strip()
    if not value:
        raise ValueError(f"run {kind} 需要输入路径")
    return value


def _workflow_input(kind: str, target: str | None, *, resume: bool,
                    project_dir: str, workflow_id: str, key: str) -> str:
    value = (target or "").strip()
    if not value and resume:
        from psyclaw.workflows.engine import checkpoint_value
        value = str(checkpoint_value(project_dir, workflow_id, key))
    return _required_target(kind, value)


def run_mode(kind: str, target: str | None = None, *, topic: str | None = None,
             project_dir: str = ".", confirm_each: bool = False,
             exploratory: bool = False, resume: bool = False,
             revise: bool = False, rounds: int = 3,
             auto: bool | None = None, skip_gates: bool | None = None) -> int:
    """执行一次明确流程。

    公开契约:默认连续执行;confirm_each 才逐步确认;exploratory 允许跳过前置检查并留痕;
    resume 从该 workflow 的最后成功步骤继续。auto/skip_gates 仅保留旧调用兼容。
    """
    mode = normalize_run_type(kind)
    continuous = (not confirm_each) if auto is None else bool(auto)
    exploratory = exploratory or bool(skip_gates)

    if mode in ("analysis", "meta", "literature", "qualitative"):
        from psyclaw.workflows import get_workflow, run_workflow

        if mode == "analysis":
            source = _workflow_input(mode, target, resume=resume, project_dir=project_dir,
                                     workflow_id="analysis", key="data_csv")
            title = topic or f"针对 {Path(source).stem} 的实证分析"
            return run_workflow(get_workflow("analysis"), topic=title,
                                project_dir=project_dir, auto=continuous,
                                seed={"data_csv": source}, skip_gates=exploratory,
                                resume=resume)
        if mode == "meta":
            source = _workflow_input(mode, target, resume=resume, project_dir=project_dir,
                                     workflow_id="meta", key="effects_csv")
            title = topic or f"针对 {Path(source).stem} 的随机效应元分析"
            return run_workflow(get_workflow("meta"), topic=title,
                                project_dir=project_dir, auto=continuous,
                                seed={"effects_csv": source}, skip_gates=exploratory,
                                resume=resume)
        if mode == "qualitative":
            source = _workflow_input(mode, target, resume=resume, project_dir=project_dir,
                                     workflow_id="qualitative", key="transcripts")
            title = topic or f"针对 {Path(source).stem} 的质性研究"
            return run_workflow(get_workflow("qualitative"), topic=title,
                                project_dir=project_dir, auto=continuous,
                                seed={"transcripts": source}, skip_gates=exploratory,
                                resume=resume)
        return run_workflow(get_workflow("lit-review"), topic=topic or target,
                            project_dir=project_dir, auto=continuous,
                            skip_gates=exploratory, resume=resume)

    if mode == "research":
        if exploratory or resume:
            raise ValueError("兼容类型 run research 不支持 --exploratory/--resume;请使用公开 workflow 类型")
        from psyclaw.pipeline import run_pipeline
        return run_pipeline(topic=topic or target, project_dir=project_dir,
                            auto=continuous, revise=revise, rounds=rounds)

    if exploratory or resume:
        raise ValueError("兼容类型 run task 不支持 --exploratory/--resume;请直接使用 chat")
    from psyclaw.loop import run_loop
    return run_loop(topic=topic or target, project_dir=project_dir, auto=continuous)


def run_auto(*, project_dir: str = ".", max_iters: int = 6,
             confirm_each: bool = False, exploratory: bool = False,
             skip_gates: bool | None = None) -> int:
    """自主推进项目;默认不逐任务确认,强制检查与不可逆决策仍会暂停。"""
    from psyclaw.autoloop import run_autoloop
    return run_autoloop(project_dir=project_dir, max_iters=max_iters,
                        auto=not confirm_each,
                        skip_gates=exploratory or bool(skip_gates))
