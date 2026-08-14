"""Planning/execution separated runtime: DAG, fork/join, verification and finish."""

from __future__ import annotations

import json
import os
import threading
from argparse import Namespace
from pathlib import Path

import pytest

from psyclaw.agent_runtime import (
    CompletionContract,
    Scheduler,
    TaskResult,
    TaskSpec,
    _task_prompt,
    parse_plan,
    run_planned_agent,
    verify_task,
)
from psyclaw.toolloop import run_tool_loop


def test_agent_workers_default_is_three():
    from psyclaw.config import DEFAULTS

    assert DEFAULTS["agent_workers"] == "3"


def test_cli_agent_ask_confirms_every_side_effect(monkeypatch):
    from psyclaw import cli
    import psyclaw.agent_runtime as runtime
    import psyclaw.repl as repl
    import psyclaw.toolloop as toolloop

    captured = {}

    def fake_run(*_args, **kwargs):
        captured["approve"] = kwargs["approve"]
        return {"final": "done", "iters": 0, "stopped": "completed",
                "trace": [], "lessons": [], "plan": [], "task_results": {}}

    prompts = []
    monkeypatch.setattr(cli.cfg, "load_config", lambda: {"provider": "mock"})
    monkeypatch.setattr(runtime, "run_planned_agent", fake_run)
    monkeypatch.setattr(repl, "_hitl_confirm",
                        lambda prompt: prompts.append(prompt) or True)
    monkeypatch.setattr(repl, "render_images_in_text", lambda *_a, **_k: None)
    monkeypatch.setattr(toolloop, "log_agent_run", lambda *_a, **_k: None)

    assert cli.cmd_agent(Namespace(task=["测试"], ask=True, max_iters=4,
                                   history=None)) == 0
    assert captured["approve"]({"name": "writer", "args": {}}) is True
    assert prompts and "工具副作用" in prompts[-1]


def test_cli_agent_auto_only_confirms_guarded_side_effects(monkeypatch):
    from psyclaw import cli
    import psyclaw.agent_runtime as runtime
    import psyclaw.repl as repl
    import psyclaw.toolloop as toolloop

    captured = {}

    def fake_run(*_args, **kwargs):
        captured["approve"] = kwargs["approve"]
        return {"final": "done", "iters": 0, "stopped": "completed",
                "trace": [], "lessons": [], "plan": [], "task_results": {}}

    prompts = []
    monkeypatch.setattr(cli.cfg, "load_config", lambda: {"provider": "mock"})
    monkeypatch.setattr(runtime, "run_planned_agent", fake_run)
    monkeypatch.setattr(repl, "_hitl_confirm",
                        lambda prompt: prompts.append(prompt) or True)
    monkeypatch.setattr(repl, "render_images_in_text", lambda *_a, **_k: None)
    monkeypatch.setattr(toolloop, "log_agent_run", lambda *_a, **_k: None)

    assert cli.cmd_agent(Namespace(task=["测试"], ask=False, max_iters=4,
                                   history=None)) == 0
    approve = captured["approve"]
    assert approve({"name": "writer", "args": {}}) is True
    assert prompts == []
    assert approve({"name": "writer", "args": {}, "_force_human": True}) is True
    assert prompts and "纠偏后的首个副作用" in prompts[-1]


def test_cli_agent_shows_background_activity(monkeypatch):
    from psyclaw import cli
    import psyclaw.agent_runtime as runtime
    import psyclaw.repl as repl
    import psyclaw.toolloop as toolloop

    events = []

    class FakeIndicator:
        def __init__(self, message=""):
            self.message = message
        def start(self):
            events.append(("start", self.message))
        def stop(self, final=None):
            events.append(("stop", final))

    monkeypatch.setattr("psyclaw.ui.ActivityIndicator", FakeIndicator)
    monkeypatch.setattr(cli.cfg, "load_config", lambda: {"provider": "mock"})
    monkeypatch.setattr(runtime, "run_planned_agent",
                        lambda *a, **k: {"final": "done", "iters": 0,
                                         "stopped": "completed", "trace": [],
                                         "lessons": [], "plan": [],
                                         "task_results": {}})
    monkeypatch.setattr(repl, "_hitl_confirm", lambda prompt: True)
    monkeypatch.setattr(repl, "render_images_in_text", lambda *_a, **_k: None)
    monkeypatch.setattr(toolloop, "log_agent_run", lambda *_a, **_k: None)

    assert cli.cmd_agent(Namespace(task=["测试"], ask=False, max_iters=4,
                                   history=None)) == 0
    assert events[0][0] == "start" and "后台" in events[0][1]
    assert events[-1] == ("stop", "Agent 已完成")


def test_cli_agent_stops_activity_when_cancelled(monkeypatch):
    from psyclaw import cli
    import psyclaw.agent_runtime as runtime

    events = []

    class FakeIndicator:
        def __init__(self, message=""):
            pass
        def start(self):
            events.append("start")
        def stop(self, final=None):
            events.append(final)

    monkeypatch.setattr("psyclaw.ui.ActivityIndicator", FakeIndicator)
    monkeypatch.setattr(cli.cfg, "load_config", lambda: {"provider": "mock"})
    monkeypatch.setattr(runtime, "run_planned_agent",
                        lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        cli.cmd_agent(Namespace(task=["测试"], ask=False, max_iters=4, history=None))
    assert events == ["start", "已取消"]


def _result(task: TaskSpec, passed: bool = True) -> TaskResult:
    return TaskResult(
        task=task,
        run={"final": "done", "stopped": "answered", "trace": [],
             "lessons": [], "iters": 1},
        passed=passed,
        reasons=[] if passed else ["failed"],
        thread_id=threading.get_ident(),
    )


def test_parse_plan_builds_valid_dag_and_contract():
    raw = json.dumps({"tasks": [
        {
            "id": "main",
            "objective": "写主报告",
            "mainline": True,
            "parallel_safe": True,
            "owned_paths": ["outputs/report.md"],
            "completion": {
                "required_tools": ["save_file"],
                "required_artifacts": ["outputs/report.md"],
                "min_successful_tool_calls": 1,
                "allow_reasoning_only": False,
            },
        },
        {
            "id": "sources",
            "objective": "整理来源",
            "parallel_safe": True,
            "owned_paths": ["notes/sources.md"],
        },
    ]})
    tasks = parse_plan(raw, "fallback")
    assert [task.id for task in tasks] == ["main", "sources"]
    assert tasks[0].completion.required_tools == ("save_file",)
    assert tasks[0].completion.allow_reasoning_only is False


def test_action_tasks_get_real_execution_contract_even_when_planner_omits_it():
    raw = json.dumps({"tasks": [{"id": "download", "objective": "下载检索到的论文"}]})
    task = parse_plan(raw)[0]
    assert task.completion.allow_reasoning_only is False
    assert task.completion.min_successful_tool_calls == 1


def test_invalid_or_cyclic_plan_falls_back_to_safe_main_task():
    cycle = json.dumps({"tasks": [
        {"id": "a", "objective": "A", "depends_on": ["b"]},
        {"id": "b", "objective": "B", "depends_on": ["a"]},
    ]})
    tasks = parse_plan(cycle, "回答问题")
    assert len(tasks) == 1 and tasks[0].id == "main"
    assert tasks[0].parallel_safe is False


def test_multiple_mainlines_are_normalized_without_discarding_tasks():
    raw = json.dumps({"tasks": [
        {"id": "search", "objective": "检索", "mainline": True},
        {"id": "download", "objective": "下载", "mainline": True,
         "depends_on": ["search"]},
    ]})
    tasks = parse_plan(raw, "继续")
    assert [task.id for task in tasks] == ["search", "download"]
    assert [task.mainline for task in tasks] == [True, False]


def test_multiple_mainlines_are_warning_not_parse_error():
    import psyclaw.agent_runtime as runtime
    raw = json.dumps({"tasks": [
        {"id": "a", "objective": "A", "mainline": True},
        {"id": "b", "objective": "B", "mainline": True},
    ]})
    _, status = runtime._parse_plan_status(raw, "继续")
    assert status["fallback"] is False
    assert status["reason"] == ""
    assert "normalized" in status["warning"]


def test_task_prompt_carries_recent_conversation_context():
    from psyclaw.agent_runtime import _task_prompt

    prompt = _task_prompt(
        TaskSpec("download", "下载刚才检索到的论文"), {},
        conversation_context=[
            {"role": "user", "content": "帮我查最新一期"},
            {"role": "assistant", "content": "DOI 10.1146/annurev-psych-020425-020958"},
        ],
    )
    assert "10.1146/annurev-psych-020425-020958" in prompt
    assert "优先复用" in prompt


def test_unsafe_owned_path_disables_parallel_execution():
    raw = json.dumps({"tasks": [{
        "id": "x", "objective": "x", "parallel_safe": True,
        "owned_paths": ["../outside.txt"],
    }]})
    task = parse_plan(raw)[0]
    assert task.owned_paths == () and task.parallel_safe is False


def test_scheduler_runs_main_on_caller_and_forks_disjoint_child():
    barrier = threading.Barrier(2, timeout=3)
    caller = threading.get_ident()
    seen: dict[str, int] = {}
    main = TaskSpec("main", "主线", mainline=True, parallel_safe=True,
                    owned_paths=("outputs/main.md",))
    child = TaskSpec("child", "子任务", parallel_safe=True,
                     owned_paths=("notes/child.md",))

    def execute(task):
        seen[task.id] = threading.get_ident()
        barrier.wait()
        return _result(task)

    results = Scheduler(execute, max_workers=2).run([main, child])
    assert set(results) == {"main", "child"}
    assert seen["main"] == caller
    assert seen["child"] != caller


def test_scheduler_serializes_overlapping_writes():
    caller = threading.get_ident()
    threads = []
    first = TaskSpec("main", "主线", mainline=True, parallel_safe=True,
                     owned_paths=("outputs",))
    second = TaskSpec("child", "冲突子任务", parallel_safe=True,
                      owned_paths=("outputs/report.md",))

    def execute(task):
        threads.append(threading.get_ident())
        return _result(task)

    Scheduler(execute, max_workers=3).run([first, second])
    assert threads == [caller, caller]


def test_scheduler_blocks_task_when_dependency_fails():
    first = TaskSpec("first", "先做", mainline=True)
    second = TaskSpec("second", "后做", depends_on=("first",))
    results = Scheduler(lambda task: _result(task, passed=False)).run([first, second])
    assert results["first"].passed is False
    assert results["second"].run["stopped"] == "blocked"


def test_scheduler_contains_mainline_executor_exception():
    task = TaskSpec("main", "主线", mainline=True)
    results = Scheduler(lambda _task: (_ for _ in ()).throw(RuntimeError("boom"))).run([task])
    assert results["main"].passed is False
    assert results["main"].run["stopped"] == "error"
    assert "boom" in results["main"].reasons[0]


def test_scheduler_fail_closes_unresolvable_dependencies():
    first = TaskSpec("first", "先做", depends_on=("missing",))
    second = TaskSpec("second", "后做", depends_on=("first",))
    scheduler = Scheduler(lambda _task: pytest.fail("blocked task must not execute"),
                          max_workers=1)
    result = scheduler.run([first, second])
    assert set(result) == {"first", "second"}
    assert all(item.passed is False for item in result.values())
    assert all(item.run["stopped"] == "blocked" for item in result.values())
    assert "未产生可用验收结果" in result["first"].reasons[0]


def test_task_prompt_carries_dependency_receipts():
    parent = TaskSpec("search", "检索", mainline=True)
    child = TaskSpec("download", "下载", depends_on=("search",))
    result = TaskResult(parent, {
        "final": "已检索",
        "stopped": "answered",
        "trace": [{"name": "lit_search", "ok": True, "output": "notes/lit_search.json"}],
    }, True, [])
    prompt = _task_prompt(child, {"search": result}, [], [])
    assert "lit_search" in prompt
    assert "notes/lit_search.json" in prompt


def test_parse_plan_infers_action_tool_contracts():
    tasks = parse_plan(json.dumps({"tasks": [
        {"id": "search", "objective": "检索文献"},
        {"id": "write", "objective": "写入报告"},
        {"id": "download", "objective": "下载全文"},
    ]}))
    contracts = {task.id: task.completion for task in tasks}
    assert contracts["search"].required_tools == ("lit_search",)
    assert contracts["write"].required_tools == ("save_file",)
    assert contracts["download"].required_tools == ("lit_download",)
    assert all(contract.allow_reasoning_only is False for contract in contracts.values())


def test_verify_task_requires_real_receipts_and_artifacts(tmp_path):
    task = TaskSpec(
        "write", "写文件",
        completion=CompletionContract(
            required_tools=("save_file",),
            required_artifacts=("outputs/report.md",),
            min_successful_tool_calls=1,
            allow_reasoning_only=False,
        ),
    )
    run = {"final": "完成", "stopped": "answered", "trace": [], "lessons": []}
    passed, reasons = verify_task(task, run, str(tmp_path))
    assert passed is False and any("工具" in reason for reason in reasons)
    artifact = tmp_path / "outputs" / "report.md"
    artifact.parent.mkdir()
    artifact.write_text("report", encoding="utf-8")
    run["trace"] = [{"name": "save_file", "ok": True, "output": "saved"}]
    assert verify_task(task, run, str(tmp_path)) == (True, [])


class _ScriptProvider:
    name = "script"
    last_stop_reason = ""

    def __init__(self, replies):
        self.replies = list(replies)

    def chat(self, messages, system=""):
        yield self.replies.pop(0) if self.replies else "done"


def test_toolloop_corrects_fake_promise_and_marks_first_side_effect():
    provider = _ScriptProvider([
        "我先执行检查，等结果回传后继续。",
        '```tool\n{"name":"writer","args":{}}\n```',
        "已经根据真实结果完成。",
    ])
    approvals = []
    tools = {"writer": {"desc": "write", "args": "", "side_effect": True,
                         "run": lambda _args: "wrote"}}
    result = run_tool_loop(
        provider, "system", [{"role": "user", "content": "do it"}], tools=tools,
        approve=lambda call: approvals.append(dict(call)) or True,
    )
    assert result["stopped"] == "answered"
    assert len(result["trace"]) == 1
    assert approvals[0]["_force_human"] is True


def test_toolloop_forces_every_side_effect_in_recovery_batch():
    provider = _ScriptProvider([
        "我先执行检查，等结果回传后继续。",
        ('```tool\n{"name":"reader","args":{}}\n```\n'
         '```tool\n{"name":"writer","args":{"n":1}}\n```\n'
         '```tool\n{"name":"writer","args":{"n":2}}\n```'),
        "完成。",
    ])
    approvals = []
    tools = {
        "reader": {"desc": "read", "args": "", "side_effect": False,
                   "run": lambda _args: "read"},
        "writer": {"desc": "write", "args": "", "side_effect": True,
                   "run": lambda _args: "wrote"},
    }
    result = run_tool_loop(
        provider, "system", [{"role": "user", "content": "do it"}], tools=tools,
        approve=lambda call: approvals.append(dict(call)) or True,
    )
    assert result["stopped"] == "answered"
    assert len(approvals) == 2
    assert all(call["_force_human"] is True for call in approvals)


def test_toolloop_keeps_recovery_pending_across_read_only_batch():
    provider = _ScriptProvider([
        "我先执行检查，等结果回传后继续。",
        '```tool\n{"name":"reader","args":{}}\n```',
        '```tool\n{"name":"writer","args":{}}\n```',
        "完成。",
    ])
    approvals = []
    tools = {
        "reader": {"desc": "read", "args": "", "side_effect": False,
                   "run": lambda _args: "read"},
        "writer": {"desc": "write", "args": "", "side_effect": True,
                   "run": lambda _args: "wrote"},
    }
    run_tool_loop(provider, "system", [{"role": "user", "content": "do it"}],
                  tools=tools, approve=lambda call: approvals.append(dict(call)) or True)
    assert len(approvals) == 1 and approvals[0]["_force_human"] is True


def test_toolloop_stops_repeated_fake_promises():
    provider = _ScriptProvider(["我先检查，等结果回传后继续。"] * 4)
    result = run_tool_loop(provider, "system", [{"role": "user", "content": "do"}],
                           tools={})
    assert result["stopped"] == "unfulfilled_commitment"
    assert result["trace"] == []


class _Planner:
    name = "planner"
    last_stop_reason = ""

    def __init__(self, barrier=None):
        self.barrier = barrier
        self.calls = 0

    def chat(self, messages, system=""):
        self.calls += 1
        if "Planner" in system:
            yield json.dumps({"tasks": [
                {"id": "main", "objective": "主线", "mainline": True,
                 "parallel_safe": True, "owned_paths": ["outputs/main.md"]},
                {"id": "child", "objective": "子线", "parallel_safe": True,
                 "owned_paths": ["notes/child.md"]},
            ]})
        elif "Finisher" in system:
            yield "所有经过验收的任务已经汇总完成。"
        else:
            if self.barrier:
                self.barrier.wait(timeout=3)
            yield "executor completed"


def test_planned_agent_forks_homogeneous_executors_and_finishes():
    barrier = threading.Barrier(2, timeout=3)
    planner = _Planner()
    created = []

    def factory():
        provider = _Planner(barrier)
        created.append(provider)
        return provider

    result = run_planned_agent(
        planner, "system", [{"role": "user", "content": "完成两个独立任务"}],
        executor_factory=factory, finisher_provider=planner, max_workers=2,
        approve=lambda _call: True,
    )
    assert result["stopped"] == "completed"
    assert set(result["task_results"]) == {"main", "child"}
    thread_ids = {item["thread_id"] for item in result["task_results"].values()}
    assert len(thread_ids) == 2
    assert len(created) == 2


def test_planner_fallback_is_reported():
    class BrokenPlanner(_Planner):
        def chat(self, messages, system=""):
            self.calls += 1
            if "Planner" in system:
                yield "not json at all"
            else:
                yield "done"

    result = run_planned_agent(
        BrokenPlanner(), "system", [{"role": "user", "content": "执行"}],
        executor_factory=lambda: _ScriptProvider(["done"]), max_workers=1,
        approve=lambda _call: True,
    )
    assert result["planner_fallback"] is True
    assert result["planner_parse_error"]


def test_finisher_not_called_when_required_contract_fails():
    planner = _Planner()
    plan = json.dumps({"tasks": [{
        "id": "must-run", "objective": "必须执行", "mainline": True,
        "completion": {"allow_reasoning_only": False,
                       "min_successful_tool_calls": 1},
    }]})

    class FailedPlanner(_Planner):
        def chat(self, messages, system=""):
            self.calls += 1
            if "Planner" in system:
                yield plan
            else:
                yield "我声称完成但没有工具回执。"

    failed = FailedPlanner()
    result = run_planned_agent(
        failed, "system", [{"role": "user", "content": "执行"}],
        executor_factory=lambda: _ScriptProvider(["只有文字"]), max_workers=1,
        approve=lambda _call: True,
    )
    assert result["stopped"] == "verification_failed"
    assert "未满足完成契约" in result["final"]


def test_parallel_executor_cannot_run_non_file_side_effect(monkeypatch):
    import psyclaw.toolloop as toolloop

    plan = json.dumps({"tasks": [{
        "id": "unsafe", "objective": "调用外部副作用", "mainline": True,
        "parallel_safe": True, "owned_paths": ["outputs/unsafe.txt"],
        "completion": {"required_tools": ["writer"],
                       "min_successful_tool_calls": 1,
                       "allow_reasoning_only": False},
    }]})

    class Planner(_Planner):
        def chat(self, messages, system=""):
            if "Planner" in system:
                yield plan
            else:
                yield "finish"

    class Executor(_ScriptProvider):
        def __init__(self):
            super().__init__([
                '```tool\n{"name":"writer","args":{}}\n```',
                "工具被拒后停止。",
            ])

    tools = {"writer": {"desc": "write", "args": "", "side_effect": True,
                         "run": lambda _args: "wrote"}}
    monkeypatch.setattr(toolloop, "build_tools", lambda _project_dir=".": tools)
    approvals = []
    result = run_planned_agent(
        Planner(), "system", [{"role": "user", "content": "执行"}],
        executor_factory=Executor, max_workers=2,
        approve=lambda call: approvals.append(call) or True,
    )
    assert result["stopped"] == "verification_failed"
    assert all(call.get("name") == "provider_handoff" for call in approvals)
    attempts = result["task_results"]["unsafe"]["run"]["attempts"]
    assert len(attempts) == 1
    assert all(attempt["trace"][0]["ok"] is False for attempt in attempts)


def test_failed_verification_does_not_replay_attempted_side_effect(tmp_path):
    plan = json.dumps({"tasks": [{
        "id": "write", "objective": "写入一次", "mainline": True,
        "owned_paths": ["outputs/actual.md"],
        "completion": {"required_artifacts": ["outputs/missing.md"],
                       "allow_reasoning_only": False},
    }]})

    class Planner(_Planner):
        def chat(self, messages, system=""):
            yield plan if "Planner" in system else "finish"

    created = []

    def factory():
        created.append(1)
        return _ScriptProvider([
            '```tool\n{"name":"save_file","args":{"path":"outputs/actual.md",'
            '"content":"done"}}\n```',
            "完成。",
        ])

    result = run_planned_agent(
        Planner(), "system", [{"role": "user", "content": "执行"}],
        executor_factory=factory, project_dir=str(tmp_path), approve=lambda _call: True,
    )
    assert result["stopped"] == "verification_failed"
    assert result["task_results"]["write"]["attempts"] == 1
    assert len(created) == 1
    assert (tmp_path / "outputs" / "actual.md").read_text(encoding="utf-8") == "done"
    assert "避免重复提交" in result["task_results"]["write"]["reasons"][-1]


def test_global_iteration_budget_is_shared_across_tasks():
    plan = json.dumps({"tasks": [
        {"id": "main", "objective": "A", "mainline": True},
        {"id": "child", "objective": "B"},
    ]})

    class Planner(_Planner):
        def chat(self, messages, system=""):
            yield plan if "Planner" in system else "finish"

    result = run_planned_agent(
        Planner(), "system", [{"role": "user", "content": "两个任务"}],
        executor_factory=lambda: _ScriptProvider(["done"]), max_iters=1,
        approve=lambda _call: True,
    )
    assert result["iters"] <= 1
    assert result["stopped"] == "verification_failed"
    assert any(item["run"]["stopped"] == "global_budget"
               for item in result["task_results"].values())


def test_cross_provider_handoff_requires_confirmation():
    planner = _Planner()
    source = _ScriptProvider([])
    approvals = []
    result = run_planned_agent(
        planner, "system", [{"role": "user", "content": "任务"}],
        source_provider=source,
        approve=lambda call: approvals.append(call) or False,
    )
    assert result["stopped"] == "provider_handoff_denied"
    assert planner.calls == 0
    assert approvals[0]["name"] == "provider_handoff"


@pytest.mark.skipif(os.name != "nt", reason="Windows path comparison")
def test_owned_path_overlap_is_case_insensitive_on_windows(tmp_path):
    from psyclaw.agent_runtime import _paths_overlap

    assert _paths_overlap(("outputs/report.md",), ("OUTPUTS/report.md",), str(tmp_path))
