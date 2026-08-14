"""LangGraph-backed PsyClaw orchestration.

The graph owns the four control-flow phases. PsyClaw still owns tool
execution, approval, artifact verification, and academic gates.
"""

from __future__ import annotations

import json
import threading
from typing import TypedDict


class GraphState(TypedDict, total=False):
    phase: str
    task_text: str
    messages: list[dict]
    system: str
    planner_provider: object
    executor_factory: object
    finisher_provider: object
    project_dir: str
    max_iters: int
    max_workers: int
    approve: object
    emit: object
    source_provider: object
    tools: dict
    run_state: object
    tasks: list
    planner_reply: str
    planner_status: dict
    task_results: dict
    trace: list[dict]
    lessons: list[dict]
    iterations: int
    required_failures: list
    final: str
    stopped: str
    error: str


def available() -> bool:
    try:
        import langgraph.graph  # noqa: F401
    except ImportError:
        return False
    return True


def _imports():
    from psyclaw.agent_runtime import (
        MAX_TASK_ATTEMPTS, Scheduler, TaskResult, _EXECUTOR_SYSTEM,
        _path_is_owned, _safe_relative_path, _task_prompt, _provider_domain,
        _completion, plan_tasks, verify_task,
    )
    from psyclaw.network import redact_secrets
    from psyclaw.run_state import RunState
    from psyclaw.toolloop import build_tools, run_tool_loop
    return locals()


def _build_nodes():
    """Return actual planner/executor/verifier/finisher node functions."""
    deps = _imports()
    StateGraph = __import__("langgraph.graph", fromlist=["StateGraph"]).StateGraph
    START = __import__("langgraph.graph", fromlist=["START"]).START
    END = __import__("langgraph.graph", fromlist=["END"]).END

    approved_domains: set[tuple[str, str]] = set()
    approval_lock = threading.Lock()

    def provider_allowed(provider, role: str, state: GraphState, source) -> bool:
        source_domain = deps["_provider_domain"](source)
        target_domain = deps["_provider_domain"](provider)
        if target_domain == source_domain or target_domain in approved_domains:
            return True
        approve = state.get("approve")
        if approve is None:
            return False
        call = {"name": "provider_handoff",
                "args": {"role": role, "from": source_domain, "to": target_domain},
                "_force_human": True}
        with approval_lock:
            if target_domain in approved_domains:
                return True
            allowed = bool(approve(call))
            if allowed:
                approved_domains.add(target_domain)
            return allowed

    def planner(state: GraphState) -> dict:
        source = state.get("source_provider") or state["planner_provider"]
        if not provider_allowed(state["planner_provider"], "planner", state, source):
            return {"phase": "planner", "tasks": [], "planner_reply": "",
                    "planner_status": {"fallback": True, "reason": "provider_handoff_denied"},
                    "stopped": "provider_handoff_denied"}
        tasks, reply, status = deps["plan_tasks"](
            state["planner_provider"], state["task_text"], state["messages"],
            available_tools=tuple(state.get("tools", {})))
        return {"phase": "planner", "tasks": tasks, "planner_reply": reply,
                "planner_status": status}

    def executor(state: GraphState) -> dict:
        lock = threading.Lock()
        accumulated: dict = {}
        provider_factory = state.get("executor_factory") or (lambda: state["planner_provider"])
        max_workers = int(state.get("max_workers") or 1)
        max_iters = int(state.get("max_iters") or 24)
        # max_iters is a per-task loop cap; the DAG also has a larger shared
        # budget so a five-step chain cannot starve after its first task.
        remaining = {"n": max(24, max_iters * max(1, len(state.get("tasks", []))))}

        def budget() -> bool:
            with lock:
                if remaining["n"] <= 0:
                    return False
                remaining["n"] -= 1
                return True

        def execute(task):
            provider = provider_factory()
            source = state.get("source_provider") or state["planner_provider"]
            if not provider_allowed(provider, "executor", state, source):
                result = deps["TaskResult"](
                    task, {"final": "", "trace": [], "lessons": [],
                           "stopped": "provider_handoff_denied", "iters": 0},
                    False, ["Executor Provider 属于不同信任域，未获确认"], 1,
                    threading.get_ident())
                with lock:
                    accumulated[task.id] = result
                return result
            feedback: list[str] = []
            history: list[dict] = []
            for _attempt in range(1, deps["MAX_TASK_ATTEMPTS"] + 1):
                tools = state.get("tools") or deps["build_tools"](state["project_dir"])

                def task_approve(call):
                    if task.parallel_safe and call.get("name") != "save_file":
                        return False
                    if call.get("name") == "save_file" and task.owned_paths:
                        raw = deps["_safe_relative_path"]((call.get("args") or {}).get("path"))
                        if not raw or not deps["_path_is_owned"](raw, task.owned_paths, state["project_dir"]):
                            return False
                    return bool(state.get("approve") and state["approve"](call))

                with lock:
                    snapshot = dict(accumulated)
                prompt = deps["_task_prompt"](task, snapshot, feedback, state["messages"])
                run = deps["run_tool_loop"](
                    provider, deps["redact_secrets"](state["system"]) + "\n\n" + deps["_EXECUTOR_SYSTEM"],
                    [{"role": "user", "content": prompt}], tools=tools,
                    project_dir=state["project_dir"], max_iters=max_iters,
                    approve=task_approve,
                    emit=(lambda event: state["emit"](f"{task.id}: {event}"))
                    if state.get("emit") else None,
                    iteration_budget=budget, run_state=state["run_state"])
                history.append(run)
                passed, reasons = deps["verify_task"](task, run, state["project_dir"])
                if passed:
                    result = deps["TaskResult"](task, run, True, [], len(history), threading.get_ident())
                    with lock:
                        accumulated[task.id] = result
                    return result
                feedback = reasons
                # Keep one bounded repair attempt even after a side effect:
                # a successful write/download may still miss another required
                # receipt or artifact in the same task.
            result = deps["TaskResult"](task, history[-1] if history else {}, False,
                                         feedback, len(history), threading.get_ident())
            with lock:
                accumulated[task.id] = result
            return result

        scheduler = deps["Scheduler"](execute, max_workers=max_workers,
                                       emit=state.get("emit"), project_dir=state["project_dir"])
        results = scheduler.run(state.get("tasks", []))
        trace = [{**item, "task_id": result.task.id}
                 for result in results.values() for item in result.run.get("trace", [])]
        lessons = [item for result in results.values() for item in result.run.get("lessons", [])]
        return {"phase": "executor", "task_results": results, "trace": trace,
                "lessons": lessons, "iterations": sum(result.run.get("iters", 0)
                                                        for result in results.values())}

    def verifier(state: GraphState) -> dict:
        if state.get("stopped") == "provider_handoff_denied":
            return {"phase": "verifier", "required_failures": [],
                    "stopped": "provider_handoff_denied"}
        failures = [r for r in state.get("task_results", {}).values()
                    if r.task.required and not r.passed]
        return {"phase": "verifier", "required_failures": failures,
                "stopped": "verification_failed" if failures else "verified"}

    def finisher(state: GraphState) -> dict:
        if state.get("stopped") == "provider_handoff_denied":
            return {"phase": "finisher",
                    "final": "Provider 跨信任域未获确认，任务未发送。",
                    "stopped": "provider_handoff_denied"}
        failures = state.get("required_failures", [])
        if failures:
            final = "任务未满足完成契约：\n" + "\n".join(
                f"- {r.task.id}: {'; '.join(r.reasons)}" for r in failures)
            return {"phase": "finisher", "final": final, "stopped": "verification_failed"}
        summaries = [{"id": r.task.id, "result": r.run.get("final", "")}
                     for r in state.get("task_results", {}).values()]
        provider = state.get("finisher_provider") or state["planner_provider"]
        source = state.get("source_provider") or state["planner_provider"]
        payload = deps["redact_secrets"](json.dumps({
            "original_goal": state["task_text"], "verified_results": summaries}, ensure_ascii=False))
        if not provider_allowed(provider, "finisher", state, source):
            final = "\n\n".join(str(item["result"]) for item in summaries if item["result"])
        else:
            try:
                final = "".join(provider.chat([{"role": "user", "content": payload}],
                                               system="# Finisher：只汇总已验收结果，不执行工具。"))
            except Exception:
                final = "\n\n".join(str(item["result"]) for item in summaries if item["result"])
        return {"phase": "finisher", "final": final.strip(), "stopped": "completed"}

    graph = StateGraph(GraphState)
    for name, node in (("planner", planner), ("executor", executor),
                       ("verifier", verifier), ("finisher", finisher)):
        graph.add_node(name, node)
    graph.add_edge(START, "planner")
    graph.add_edge("planner", "executor")
    graph.add_edge("executor", "verifier")
    graph.add_edge("verifier", "finisher")
    graph.add_edge("finisher", END)
    return graph.compile()


def run_langgraph_agent(planner_provider, system: str, messages: list[dict], **kwargs) -> dict:
    if not available():
        raise RuntimeError("langgraph 不可用")
    from psyclaw.run_state import RunState
    task_text = next((str(m.get("content") or "") for m in reversed(messages)
                      if m.get("role") == "user"), "")
    include_mcp = any(word in task_text.lower()
                      for word in ("mcp", "mne", "eeg", "spss", "stata", "mplus", "kaggle"))
    try:
        initial_tools = _imports()["build_tools"](
            kwargs.get("project_dir", "."), include_mcp=include_mcp)
    except TypeError:  # compatibility with injected/test builders
        initial_tools = _imports()["build_tools"](kwargs.get("project_dir", "."))
    state: GraphState = {
        "phase": "start", "task_text": task_text, "messages": messages,
        "system": system, "planner_provider": planner_provider,
        "executor_factory": kwargs.get("executor_factory"),
        "finisher_provider": kwargs.get("finisher_provider"),
        "project_dir": kwargs.get("project_dir", "."),
        "max_iters": kwargs.get("max_iters", 24), "max_workers": kwargs.get("max_workers", 3),
        "approve": kwargs.get("approve"), "emit": kwargs.get("emit"),
        "source_provider": kwargs.get("source_provider"),
        "tools": initial_tools,
        "run_state": RunState.load(kwargs.get("project_dir", "."), goal=task_text,
                                    conversation=messages),
    }
    state["run_state"].add_pending(task_text)
    result = _build_nodes().invoke(state)
    return {"final": result.get("final", ""), "iters": result.get("iterations", 0),
            "stopped": result.get("stopped", "completed"), "trace": result.get("trace", []),
            "lessons": result.get("lessons", []),
            "plan": [{"id": t.id, "objective": t.objective} for t in result.get("tasks", [])],
            "planner_reply": result.get("planner_reply", ""),
            "planner_fallback": bool(result.get("planner_status", {}).get("fallback")),
            "planner_parse_error": result.get("planner_status", {}).get("reason", ""),
            "planner_warning": result.get("planner_status", {}).get("warning", ""),
            "task_results": {k: v.public() for k, v in result.get("task_results", {}).items()},
            "backend": "langgraph", "graph_nodes": ["planner", "executor", "verifier", "finisher"]}


def run_agent(*args, backend: str = "auto", **kwargs) -> dict:
    requested = (backend or "auto").strip().lower()
    if requested in {"legacy", "classic"}:
        from psyclaw.agent_runtime import run_planned_agent
        result = dict(run_planned_agent(*args, **kwargs))
        result["backend"] = "legacy"
        return result
    try:
        return run_langgraph_agent(*args, **kwargs)
    except Exception as exc:
        return {"final": f"LangGraph 执行失败:{type(exc).__name__}: {exc}",
                "iters": 0, "stopped": "backend_error", "trace": [],
                "lessons": [], "backend": "langgraph",
                "graph_nodes": ["planner", "executor", "verifier", "finisher"],
                "backend_error": f"{type(exc).__name__}: {exc}"}
