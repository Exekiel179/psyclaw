from __future__ import annotations

from psyclaw import langchain_adapter as adapter


def test_langchain_adapter_is_optional():
    assert isinstance(adapter.available(), bool)


def test_provider_runnable_fails_with_actionable_message_when_uninstalled(monkeypatch):
    class P:
        def chat(self, messages, system=""):
            yield "ok"
    if adapter.available():
        assert adapter.provider_runnable(P()) is not None
    else:
        try:
            adapter.provider_runnable(P())
        except RuntimeError as exc:
            assert "langchain-core" in str(exc)
        else:
            raise AssertionError("missing optional dependency did not fail clearly")
