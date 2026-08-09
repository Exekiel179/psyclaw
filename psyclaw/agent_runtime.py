"""Planning/execution separated agent runtime with bounded homogeneous forks.

The planner can only emit a task DAG. Executors are fresh, homogeneous provider
instances running the existing tool loop. The scheduler keeps the critical path
on the caller thread, forks disjoint ready tasks to a bounded pool, and joins
all results before deterministic verification and finalization.
"""

from __future__ import annotations

import json
import os
import re
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable


MAX_PLAN_TASKS = 8
MAX_WORKERS = 4
MAX_TASK_ATTEMPTS = 2

_PLANNER_SYSTEM = """
# 角色：Planner（只规划，不执行）
你不能调用工具、写文件或声称已经执行。把用户目标拆成一个有向无环任务图，只输出一个 JSON 对象：
{
  "tasks": [
    {
      "id": "短英文标识",
      "objective": "可独立执行的具体目标",
      "depends_on": [],
      "mainline": true,
      "parallel_safe": false,
      "owned_paths": ["outputs/example.md"],
      "required": true,
      "completion": {
        "required_tools": [],
        "required_artifacts": [],
        "min_successful_tool_calls": 0,
        "allow_reasoning_only": true
      }
    }
  ]
}
规则：
- mainline 表示关键路径；至多一个当前无依赖任务设为 true。
- 只有任务彼此独立且写入路径明确、互不重叠时才设 parallel_safe=true。
- 需要执行、检索、读取或写文件的任务必须 allow_reasoning_only=false，并填写工具/产物条件。
- owned_paths 只能是项目内相对路径。信息不足且必须由人决策时，创建一个不可执行的澄清任务。
- 最多 8 个任务。不要输出 JSON 之外的解释。
""".strip()

_EXECUTOR_SYSTEM = """
# 角色：Executor（只执行分配的任务）
严格处理当前 TaskSpec，不重新规划全局任务，也不处理其他任务。需要操作时必须实际调用工具；
不得只说“我先执行”“等待结果”。完成后给出基于真实工具回执或产物的简短结论。
""".strip()

_FINISHER_SYSTEM = """
# 角色：Finisher（只汇总，不执行）
所有必需任务已经通过独立验收。根据提供的任务结果直接回答最初的用户目标。
不得声明还要执行、稍后处理或等待结果；不得编造未出现在结果中的事实。
""".strip()


@dataclass(frozen=True)
class CompletionContract:
    required_tools: tuple[str, ...] = ()
    required_artifacts: tuple[str, ...] = ()
    min_successful_tool_calls: int = 0
    allow_reasoning_only: bool = True


@dataclass(frozen=True)
class TaskSpec:
    id: str
    objective: str
    depends_on: tuple[str, ...] = ()
    mainline: bool = False
    parallel_safe: bool = False
    owned_paths: tuple[str, ...] = ()
    required: bool = True
    completion: CompletionContract = field(default_factory=CompletionContract)


@dataclass
class TaskResult:
    task: TaskSpec
    run: dict
    passed: bool
    reasons: list[str]
    attempts: int = 1
    thread_id: int = 0

    def public(self) -> dict:
        return {
            "task": asdict(self.task),
            "passed": self.passed,
            "reasons": list(self.reasons),
            "attempts": self.attempts,
            "thread_id": self.thread_id,
            "run": self.run,
        }


def _clean_id(value: object, index: int) -> str:
    raw = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "")).strip("-").lower()
    return raw[:48] or f"task-{index}"


def _safe_relative_path(value: object) -> str | None:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return None
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts or re.match(r"^[A-Za-z]:", raw):
        return None
    normalized = path.as_posix().lstrip("./")
    return normalized if normalized not in {"", "."} else None


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _completion(raw: object) -> CompletionContract:
    data = raw if isinstance(raw, dict) else {}
    artifacts = tuple(filter(None, (_safe_relative_path(v)
                                    for v in _string_tuple(data.get("required_artifacts")))))
    try:
        minimum = max(0, int(data.get("min_successful_tool_calls", 0)))
    except (TypeError, ValueError):
        minimum = 0
    return CompletionContract(
        required_tools=_string_tuple(data.get("required_tools")),
        required_artifacts=artifacts,
        min_successful_tool_calls=minimum,
        allow_reasoning_only=bool(data.get("allow_reasoning_only", True)),
    )


def _extract_json(text: str) -> dict:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text or "", re.S | re.I)
    candidate = fenced.group(1) if fenced else ""
    if not candidate:
        start, end = (text or "").find("{"), (text or "").rfind("}")
        candidate = (text or "")[start:end + 1] if 0 <= start < end else ""
    value = json.loads(candidate)
    if not isinstance(value, dict):
        raise ValueError("planner output must be a JSON object")
    return value


def _assert_acyclic(tasks: list[TaskSpec]) -> None:
    remaining = {task.id: set(task.depends_on) for task in tasks}
    done: set[str] = set()
    while remaining:
        ready = [task_id for task_id, deps in remaining.items() if deps <= done]
        if not ready:
            raise ValueError("task plan contains a dependency cycle")
        for task_id in ready:
            done.add(task_id)
            remaining.pop(task_id)


def parse_plan(text: str, fallback_objective: str = "") -> list[TaskSpec]:
    """Parse and validate the planner JSON. Invalid output becomes one safe task."""
    try:
        payload = _extract_json(text)
        raw_tasks = payload.get("tasks")
        if not isinstance(raw_tasks, list) or not raw_tasks:
            raise ValueError("planner emitted no tasks")
        if len(raw_tasks) > MAX_PLAN_TASKS:
            raise ValueError("planner emitted too many tasks")
        tasks: list[TaskSpec] = []
        ids: set[str] = set()
        for index, raw in enumerate(raw_tasks, 1):
            if not isinstance(raw, dict):
                raise ValueError("task must be an object")
            task_id = _clean_id(raw.get("id"), index)
            if task_id in ids:
                raise ValueError(f"duplicate task id: {task_id}")
            ids.add(task_id)
            objective = str(raw.get("objective") or "").strip()
            if not objective:
                raise ValueError(f"task {task_id} has no objective")
            owned = tuple(filter(None, (_safe_relative_path(v)
                                        for v in _string_tuple(raw.get("owned_paths")))))
            tasks.append(TaskSpec(
                id=task_id,
                objective=objective,
                depends_on=_string_tuple(raw.get("depends_on")),
                mainline=bool(raw.get("mainline", False)),
                parallel_safe=bool(raw.get("parallel_safe", False)) and bool(owned),
                owned_paths=owned,
                required=bool(raw.get("required", True)),
                completion=_completion(raw.get("completion")),
            ))
        known = {task.id for task in tasks}
        if any(dep not in known or dep == task.id for task in tasks for dep in task.depends_on):
            raise ValueError("task plan has an unknown/self dependency")
        if sum(task.mainline for task in tasks) > 1:
            raise ValueError("task plan has multiple mainline tasks")
        if not any(task.mainline for task in tasks):
            first = tasks[0]
            tasks[0] = TaskSpec(**{**asdict(first), "completion": first.completion,
                                   "mainline": True})
        _assert_acyclic(tasks)
        return tasks
    except (ValueError, TypeError, json.JSONDecodeError):
        objective = fallback_objective.strip() or "回答用户当前问题"
        return [TaskSpec(id="main", objective=objective, mainline=True)]


def plan_tasks(provider, task: str, context: list[dict] | None = None,
               available_tools: tuple[str, ...] = ()) -> tuple[list[TaskSpec], str]:
    from psyclaw.network import redact_secrets

    history = [{"role": str(message.get("role") or "user"),
                "content": redact_secrets(str(message.get("content") or ""))}
               for message in (context or [])[-6:]]
    messages = [{"role": "user", "content": json.dumps({
        "original_goal": redact_secrets(task),
        "conversation_context": history,
    }, ensure_ascii=False)}]
    catalog = ("\n\n可用工具名（只用于填写完成契约，Planner 不得调用）：\n"
               + ", ".join(available_tools)) if available_tools else ""
    reply = "".join(provider.chat(messages, system=_PLANNER_SYSTEM + catalog))
    return parse_plan(reply, task), reply


def _resolved_owned_paths(paths: tuple[str, ...], project_dir: str = ".") -> tuple[str, ...]:
    root = Path(project_dir).expanduser().resolve()
    resolved: list[str] = []
    for relative in paths:
        target = (root / relative).resolve()
        if target.is_relative_to(root):
            resolved.append(os.path.normcase(str(target)))
    return tuple(resolved)


def _paths_overlap(left: tuple[str, ...], right: tuple[str, ...],
                   project_dir: str = ".") -> bool:
    left_real = _resolved_owned_paths(left, project_dir)
    right_real = _resolved_owned_paths(right, project_dir)
    for a in left_real:
        for b in right_real:
            try:
                common = os.path.normcase(os.path.commonpath((a, b)))
            except ValueError:
                continue
            if common in {a, b}:
                return True
    return False


def _path_is_owned(target: str, owners: tuple[str, ...],
                   project_dir: str = ".") -> bool:
    target_real = _resolved_owned_paths((target,), project_dir)
    owner_real = _resolved_owned_paths(owners, project_dir)
    if not target_real:
        return False
    for owner in owner_real:
        try:
            if os.path.normcase(os.path.commonpath((target_real[0], owner))) == owner:
                return True
        except ValueError:
            continue
    return False


def _provider_domain(provider) -> tuple[str, str]:
    return (str(getattr(provider, "name", type(provider).__name__)),
            str(getattr(provider, "base_url", "") or "").rstrip("/").lower())


def verify_task(task: TaskSpec, run: dict, project_dir: str = ".") -> tuple[bool, list[str]]:
    """Verify execution from structured receipts and artifacts, never model claims."""
    from psyclaw.repl import unfulfilled_action_commitment

    reasons: list[str] = []
    if run.get("stopped") != "answered":
        reasons.append(f"executor 未正常回答:{run.get('stopped', 'unknown')}")
    final = str(run.get("final") or "").strip()
    if not final:
        reasons.append("executor 最终答复为空")
    elif unfulfilled_action_commitment(final):
        reasons.append("executor 仍包含未兑现的执行承诺")
    trace = list(run.get("trace") or [])
    successful = [item for item in trace if item.get("ok")]
    used = {str(item.get("name") or "") for item in successful}
    missing_tools = [name for name in task.completion.required_tools if name not in used]
    if missing_tools:
        reasons.append("缺少必需工具回执:" + ", ".join(missing_tools))
    if len(successful) < task.completion.min_successful_tool_calls:
        reasons.append(
            f"成功工具调用不足:{len(successful)}/{task.completion.min_successful_tool_calls}")
    if not task.completion.allow_reasoning_only and not successful:
        reasons.append("任务要求实际执行，但没有成功工具回执")
    root = Path(project_dir).resolve()
    for relative in task.completion.required_artifacts:
        artifact = (root / relative).resolve()
        if not artifact.is_relative_to(root) or not artifact.is_file() or artifact.stat().st_size == 0:
            reasons.append(f"必需产物缺失或为空:{relative}")
    return not reasons, reasons


class Scheduler:
    """Bounded DAG scheduler. Mainline runs locally; safe siblings run as forks."""

    def __init__(self, execute: Callable[[TaskSpec], TaskResult], max_workers: int = 3,
                 emit: Callable[[str], None] | None = None,
                 project_dir: str = ".") -> None:
        self.execute = execute
        self.max_workers = max(1, min(int(max_workers), MAX_WORKERS))
        self.emit = emit
        self.project_dir = project_dir

    def _say(self, text: str) -> None:
        if self.emit:
            self.emit(text)

    def _safe_execute(self, task: TaskSpec) -> TaskResult:
        try:
            return self.execute(task)
        except Exception as exc:  # noqa: BLE001
            return TaskResult(
                task=task,
                run={"final": "", "trace": [], "lessons": [],
                     "stopped": "error", "iters": 0},
                passed=False, reasons=[f"executor 异常:{exc}"],
                thread_id=threading.get_ident(),
            )

    def run(self, tasks: list[TaskSpec]) -> dict[str, TaskResult]:
        pending = {task.id: task for task in tasks}
        passed: set[str] = set()
        failed: set[str] = set()
        results: dict[str, TaskResult] = {}
        with ThreadPoolExecutor(max_workers=max(1, self.max_workers - 1),
                                thread_name_prefix="psyclaw-executor") as pool:
            while pending:
                blocked = [task for task in pending.values() if set(task.depends_on) & failed]
                for task in blocked:
                    result = TaskResult(
                        task=task,
                        run={"final": "", "trace": [], "lessons": [], "stopped": "blocked",
                             "iters": 0},
                        passed=False, reasons=["依赖任务验收失败"], thread_id=threading.get_ident())
                    results[task.id] = result
                    failed.add(task.id)
                    pending.pop(task.id)
                ready = [task for task in pending.values() if set(task.depends_on) <= passed]
                if not ready:
                    if pending:
                        raise RuntimeError("scheduler cannot make progress")
                    break
                main = next((task for task in ready if task.mainline), ready[0])
                children: list[TaskSpec] = []
                if self.max_workers > 1 and main.parallel_safe:
                    for task in ready:
                        if task.id == main.id or not task.parallel_safe:
                            continue
                        if _paths_overlap(main.owned_paths, task.owned_paths,
                                          self.project_dir):
                            continue
                        if any(_paths_overlap(task.owned_paths, child.owned_paths,
                                              self.project_dir)
                               for child in children):
                            continue
                        children.append(task)
                        if len(children) >= self.max_workers - 1:
                            break
                futures: dict[Future, TaskSpec] = {}
                for child in children:
                    self._say(f"fork {child.id}: {child.objective[:70]}")
                    futures[pool.submit(self._safe_execute, child)] = child
                self._say(f"main {main.id}: {main.objective[:70]}")
                wave: list[TaskResult] = [self._safe_execute(main)]
                for future, child in futures.items():
                    wave.append(future.result())
                for result in wave:
                    results[result.task.id] = result
                    pending.pop(result.task.id, None)
                    (passed if result.passed else failed).add(result.task.id)
                    self._say(
                        f"join {result.task.id}: {'passed' if result.passed else 'failed'}")
        return results


def _task_prompt(task: TaskSpec, dependency_results: dict[str, TaskResult],
                 verification_feedback: list[str] | None = None) -> str:
    from psyclaw.network import redact_secrets

    deps = {
        task_id: result.run.get("final", "")
        for task_id, result in dependency_results.items() if task_id in task.depends_on
    }
    payload = {
        "task": asdict(task),
        "dependency_results": deps,
        "previous_verification_failures": verification_feedback or [],
    }
    return "执行以下结构化任务：\n" + redact_secrets(
        json.dumps(payload, ensure_ascii=False, indent=2))


def run_planned_agent(
        planner_provider, system: str, messages: list[dict], *,
        executor_factory: Callable[[], object] | None = None,
        finisher_provider=None, project_dir: str = ".", max_iters: int = 24,
        max_workers: int = 3, approve=None, emit=None, source_provider=None) -> dict:
    """Run planner -> bounded fork/join executors -> verifier -> finisher."""
    from psyclaw.toolloop import build_tools, run_tool_loop
    from psyclaw.network import redact_secrets

    approval_lock = threading.Lock()
    emit_lock = threading.Lock()
    result_lock = threading.Lock()
    budget_lock = threading.Lock()
    accumulated: dict[str, TaskResult] = {}
    approved_domains: set[tuple[str, str]] = set()

    task_text = next((str(message.get("content") or "") for message in reversed(messages)
                      if message.get("role") == "user"), "")

    def provider_allowed(provider, role: str) -> bool:
        source = source_provider or planner_provider
        source_domain = _provider_domain(source)
        target_domain = _provider_domain(provider)
        if target_domain == source_domain or target_domain in approved_domains:
            return True
        call = {
            "name": "provider_handoff",
            "args": {"role": role, "from": source_domain, "to": target_domain},
            "_force_human": True,
        }
        if approve is None:
            return False
        with approval_lock:
            if target_domain in approved_domains:
                return True
            allowed = bool(approve(call))
            if allowed:
                approved_domains.add(target_domain)
            return allowed

    def safe_emit(event: str) -> None:
        if emit:
            with emit_lock:
                emit(event)

    if not provider_allowed(planner_provider, "planner"):
        return {
            "final": "规划 Provider 属于不同信任域，未获确认，任务未发送。",
            "iters": 0, "stopped": "provider_handoff_denied", "trace": [],
            "lessons": [], "plan": [], "planner_reply": "", "task_results": {},
        }

    available_tools = tuple(build_tools(project_dir))
    tasks, planner_reply = plan_tasks(
        planner_provider, task_text, messages, available_tools=available_tools)
    if executor_factory is None:
        executor_factory = lambda: planner_provider
        max_workers = 1
    try:
        remaining_iterations = max(1, int(max_iters))
    except (TypeError, ValueError):
        remaining_iterations = 24

    def take_iteration() -> bool:
        nonlocal remaining_iterations
        with budget_lock:
            if remaining_iterations <= 0:
                return False
            remaining_iterations -= 1
            return True

    safe_emit(f"plan: {len(tasks)} tasks · workers={max(1, min(max_workers, MAX_WORKERS))}")

    def execute(task: TaskSpec) -> TaskResult:
        feedback: list[str] = []
        history: list[dict] = []
        last_run: dict = {"final": "", "trace": [], "lessons": [],
                          "stopped": "not_started", "iters": 0}

        def audited_run() -> dict:
            merged = dict(last_run)
            merged["trace"] = [item for attempt_run in history
                               for item in attempt_run.get("trace", [])]
            merged["lessons"] = [item for attempt_run in history
                                 for item in attempt_run.get("lessons", [])]
            merged["iters"] = sum(int(attempt_run.get("iters", 0))
                                  for attempt_run in history)
            merged["attempts"] = history
            return merged

        for attempt in range(1, MAX_TASK_ATTEMPTS + 1):
            provider = executor_factory()
            if not provider_allowed(provider, "executor"):
                last_run = {"final": "", "trace": [], "lessons": [],
                            "stopped": "provider_handoff_denied", "iters": 0}
                history.append(last_run)
                feedback = ["Executor Provider 属于不同信任域，未获确认"]
                break
            tools = build_tools(project_dir)

            def task_approve(call: dict) -> bool:
                if (task.parallel_safe and call.get("name") != "save_file"):
                    safe_emit(f"deny {task.id}: 并行副本不能执行非文件副作用")
                    return False
                if call.get("name") == "save_file" and task.owned_paths:
                    raw = _safe_relative_path((call.get("args") or {}).get("path"))
                    if not raw or not _path_is_owned(raw, task.owned_paths, project_dir):
                        safe_emit(f"deny {task.id}: 写入路径不属于该任务")
                        return False
                if approve is None:
                    return False
                with approval_lock:
                    return bool(approve(call))

            with result_lock:
                dependency_snapshot = dict(accumulated)
            prompt = _task_prompt(task, dependency_snapshot, feedback)
            last_run = run_tool_loop(
                provider, redact_secrets(system) + "\n\n" + _EXECUTOR_SYSTEM,
                [{"role": "user", "content": prompt}], tools=tools,
                project_dir=project_dir, max_iters=max_iters,
                approve=task_approve, emit=lambda event: safe_emit(f"{task.id}: {event}"),
                iteration_budget=take_iteration)
            history.append(last_run)
            passed, reasons = verify_task(task, last_run, project_dir)
            if passed:
                result = TaskResult(
                    task, audited_run(), True, [], attempt, threading.get_ident())
                with result_lock:
                    accumulated[task.id] = result
                return result
            attempted_side_effects = [item for item in last_run.get("trace", [])
                                      if item.get("side_effect")]
            if attempted_side_effects:
                reasons.append("已有副作用执行尝试，为避免重复提交，不自动重试")
                feedback = reasons
                safe_emit(f"verify {task.id} failed: 已阻止副作用重放")
                break
            feedback = reasons
            safe_emit(f"verify {task.id} failed: {'; '.join(reasons[:2])}")
        result = TaskResult(task, audited_run(), False, feedback, len(history),
                            threading.get_ident())
        with result_lock:
            accumulated[task.id] = result
        return result

    scheduler = Scheduler(execute, max_workers=max_workers, emit=safe_emit,
                          project_dir=project_dir)
    accumulated.update(scheduler.run(tasks))
    required_failures = [result for result in accumulated.values()
                         if result.task.required and not result.passed]
    trace = [{**item, "task_id": result.task.id}
             for result in accumulated.values() for item in result.run.get("trace", [])]
    lessons = []
    lesson_keys: set[tuple[str, str]] = set()
    for result in accumulated.values():
        for item in result.run.get("lessons", []):
            key = (str(item.get("trigger", "")), str(item.get("lesson", "")))
            if key not in lesson_keys:
                lesson_keys.add(key)
                lessons.append(item)
    iterations = sum(int(result.run.get("iters", 0)) for result in accumulated.values())
    if required_failures:
        lines = ["任务未满足完成契约："]
        for result in required_failures:
            lines.append(f"- {result.task.id}: {'; '.join(result.reasons)}")
        final = "\n".join(lines)
        stopped = "verification_failed"
    else:
        summaries = [{"id": result.task.id, "result": result.run.get("final", "")}
                     for result in accumulated.values()]
        finisher = finisher_provider or planner_provider
        finish_payload = redact_secrets(json.dumps({
            "original_goal": task_text,
            "verified_results": summaries,
        }, ensure_ascii=False))
        if provider_allowed(finisher, "finisher"):
            try:
                final = "".join(finisher.chat(
                    [{"role": "user", "content": finish_payload}],
                    system=_FINISHER_SYSTEM)).strip()
            except Exception:  # noqa: BLE001
                final = ""
        else:
            safe_emit("deny finisher: Provider 跨信任域未获确认，使用已验收摘要")
            final = ""
        from psyclaw.repl import unfulfilled_action_commitment
        if not final or unfulfilled_action_commitment(final):
            final = "\n\n".join(str(item["result"]) for item in summaries if item["result"])
        stopped = "completed"
    return {
        "final": final,
        "iters": iterations,
        "stopped": stopped,
        "trace": trace,
        "lessons": lessons,
        "plan": [asdict(task) for task in tasks],
        "planner_reply": planner_reply,
        "task_results": {task_id: result.public()
                         for task_id, result in accumulated.items()},
    }
