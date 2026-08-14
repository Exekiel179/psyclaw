"""Optional langchain-core bridge.

This module adapts PsyClaw providers/tools to LangChain Core primitives only.
PsyClaw's toolloop, approval layer and completion verification remain the
execution authority. The dependency is optional and imported lazily.
"""

from __future__ import annotations


def available() -> bool:
    try:
        import langchain_core  # noqa: F401
    except ImportError:
        return False
    return True


def provider_runnable(provider):
    """Return a RunnableLambda accepting {messages, system} and yielding text."""
    try:
        from langchain_core.runnables import RunnableLambda
    except ImportError as exc:
        raise RuntimeError("可选依赖 langchain-core 未安装: pip install 'psyclaw[langchain]'") from exc

    def invoke(payload):
        payload = payload or {}
        messages = payload.get("messages", []) if isinstance(payload, dict) else payload
        system = payload.get("system", "") if isinstance(payload, dict) else ""
        return "".join(provider.chat(messages, system=system))

    return RunnableLambda(invoke)


def tool_runnable(name: str, tool: dict):
    """Adapt one PsyClaw tool to a RunnableLambda; approvals stay outside."""
    try:
        from langchain_core.runnables import RunnableLambda
    except ImportError as exc:
        raise RuntimeError("可选依赖 langchain-core 未安装: pip install 'psyclaw[langchain]'") from exc

    def invoke(args):
        return tool["run"](args or {})

    runnable = RunnableLambda(invoke)
    return runnable.with_config(run_name=name, metadata={"side_effect": bool(tool.get("side_effect"))})
