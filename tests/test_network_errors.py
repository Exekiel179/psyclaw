"""离线网络异常诊断测试。"""
from __future__ import annotations

import urllib.error

from psyclaw.network import network_error_hint, network_error_message


def test_network_error_categories_are_actionable_without_network():
    assert "超时" in network_error_message(TimeoutError("timed out"))
    dns = urllib.error.URLError(OSError("[WinError 11001] getaddrinfo failed"))
    assert "DNS" in network_error_message(dns)
    assert "代理" in network_error_message("tunnel error: proxy refused")
    assert "SSL" in network_error_message("certificate verify failed")


def test_unknown_tool_error_is_not_misclassified():
    assert network_error_hint(RuntimeError("invalid dataset column")) is None
    assert network_error_message(RuntimeError("invalid dataset column")) is None
    assert network_error_hint("JSON 解析失败") is None
    assert network_error_hint("文件下载失败: disk full") is None


def test_traceback_is_reduced_to_a_short_network_diagnosis():
    raw = "Traceback (most recent call last):\n  File 'x.py', line 2\n"
    raw += "urllib.error.URLError: <urlopen error name or service not known>"
    msg = network_error_message(raw)
    assert msg and "DNS" in msg and "Traceback" not in msg


def test_network_diagnosis_redacts_tokens_and_url_credentials():
    raw = ("network error: KGAT_do_not_show "
           "https://example.test/data?access_token=also_secret")
    msg = network_error_message(raw)
    assert msg and "KGAT_do_not_show" not in msg and "also_secret" not in msg
    assert "redacted" in msg


def test_redact_secrets_covers_provider_tokens_and_proxy_credentials():
    from psyclaw.network import redact_secrets
    text = ("sk-ant-abcdefghijklmnopqrstuvwxyz "
            "ghp_abcdefghijklmnopqrstuvwxyz123456 "
            "https://alice:private@proxy.example")
    safe = redact_secrets(text)
    assert "abcdefghijklmnopqrstuvwxyz" not in safe
    assert "alice:private" not in safe
    assert safe.count("redacted") >= 3


def test_mcp_eof_uses_network_stderr_instead_of_process_crash(monkeypatch):
    from psyclaw import ui
    from psyclaw.mcp.client import MCPClient

    monkeypatch.setattr(ui, "_ENABLED", False)
    client = MCPClient("unused")
    monkeypatch.setattr(client, "_send", lambda message: True)
    client._stderr_tail = ["uv: failed to fetch https://pypi.org/simple/kaggle-mcp"]
    client._q.put({"__eof__": True})

    response = client._request("initialize", {})

    message = response["error"]["message"]
    assert "网络连接失败" in message and "外部依赖下载失败" in message
    assert "MCP 进程提前退出" not in message


def test_mcp_network_tool_traceback_is_condensed(monkeypatch):
    from psyclaw.mcp.client import MCPClient

    client = MCPClient("unused")
    client._initialized = True
    monkeypatch.setattr(client, "_request", lambda *args, **kwargs: {
        "result": {
            "isError": True,
            "content": [{"type": "text", "text":
                         "Traceback (most recent call last):\nTimeoutError: timed out"}],
        },
    })

    result = client.call_tool_status("download", {})

    assert result["ok"] is False
    assert "网络连接失败" in result["text"] and "Traceback" not in result["text"]
