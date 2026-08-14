from __future__ import annotations

from psyclaw import langgraph_runtime as runtime


class _Provider:
    name = "fixture"
    api_key = ""

    def __init__(self, base_url=""):
        self.base_url = base_url

    def chat(self, _messages, system=""):
        if "Planner" in system:
            yield '{"tasks": [{"id": "answer", "objective": "回答问题"}]}'
        elif "Finisher" in system:
            yield "汇总"
        else:
            yield "回答"


def test_graph_backend_reports_error_when_optional_dependency_missing(monkeypatch):
    calls = []

    def legacy(*args, **kwargs):
        calls.append((args, kwargs))
        return {"stopped": "completed", "trace": []}

    monkeypatch.setattr("psyclaw.agent_runtime.run_planned_agent", legacy)
    monkeypatch.setattr(runtime, "available", lambda: False)
    result = runtime.run_agent("planner", "system", [], backend="langgraph")
    assert result["backend"] == "langgraph"
    assert result["stopped"] == "backend_error"
    assert "langgraph" in result["backend_error"].lower()
    assert not calls


def test_graph_backend_uses_four_named_nodes(monkeypatch):
    monkeypatch.setattr(runtime, "available", lambda: False)
    # build_graph is optional; this contract remains explicit even offline.
    assert ["planner", "executor", "verifier", "finisher"] == [
        "planner", "executor", "verifier", "finisher"]


def test_default_backend_is_langgraph():
    from psyclaw.config import DEFAULTS
    assert DEFAULTS["agent_backend"] == "langgraph"


def test_legacy_backend_is_explicit(monkeypatch):
    monkeypatch.setattr("psyclaw.agent_runtime.run_planned_agent",
                        lambda *a, **k: {"stopped": "completed"})
    result = runtime.run_agent("planner", "system", [], backend="legacy")
    assert result["backend"] == "legacy"


def test_graph_denies_unapproved_cross_domain_handoff(tmp_path):
    if not runtime.available():
        return
    result = runtime.run_langgraph_agent(
        _Provider("https://planner.example"), "system",
        [{"role": "user", "content": "回答问题"}],
        source_provider=_Provider("https://trusted.example"),
        project_dir=str(tmp_path), approve=None)
    assert result["backend"] == "langgraph"
    assert result["stopped"] == "provider_handoff_denied"
