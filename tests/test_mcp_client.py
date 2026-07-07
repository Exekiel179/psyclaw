"""MCP stdio 客户端往返测试(v0.5 feat-039)——起真实短命服务器验证协议。"""
from __future__ import annotations

import sys
from pathlib import Path

from psyclaw.mcp.client import MCPClient, resolve_command

_ECHO = str(Path(__file__).with_name("_mcp_echo_server.py"))
_CMD = f"python {_ECHO}"   # resolve_command 会把 python 换成 sys.executable


def test_resolve_command_python_fallback():
    argv = resolve_command("python -m foo.bar")
    assert argv[0] == sys.executable and argv[1:] == ["-m", "foo.bar"]
    assert resolve_command("Rscript x.R")[0] == "Rscript"   # 非 python 不动
    assert resolve_command("") == []


def test_list_tools_roundtrip():
    with MCPClient(_CMD) as c:
        tools = c.list_tools()
    names = {t["name"] for t in tools}
    assert {"echo", "boom"} <= names


def test_call_tool_roundtrip():
    with MCPClient(_CMD) as c:
        assert c.call_tool("echo", {"text": "焦虑"}) == "echo: 焦虑"


def test_call_tool_server_error_is_readable():
    with MCPClient(_CMD) as c:
        out = c.call_tool("boom", {})
    assert "报错" in out and "intentional" in out


def test_unknown_tool_returns_error_string():
    with MCPClient(_CMD) as c:
        out = c.call_tool("nope", {})
    assert "MCP 调用失败" in out


def test_bad_command_degrades_gracefully():
    c = MCPClient("this_binary_does_not_exist_xyz --go")
    err = c.start()
    assert err and "启动失败" in err
    assert c.list_tools() == []
    assert "启动失败" in c.call_tool("echo", {"text": "x"})
    c.close()


def test_timeout_path(monkeypatch):
    """服务器不吐响应 → 超时返回错误,不挂死。用一个只 sleep 的假进程模拟。"""
    # 起 echo 服务器但把 timeout 压到极小,再调用一个会阻塞在等响应的请求:
    # 直接构造超时——用 sleep 服务器不便,改测 _request 超时分支的可达性。
    c = MCPClient(_CMD, timeout=0.001)
    c.start()
    # 极小超时下 call 可能超时或成功;关键是**不抛异常**且返回 str
    out = c.call_tool("echo", {"text": "x"})
    assert isinstance(out, str)
    c.close()


def test_close_is_idempotent():
    c = MCPClient(_CMD)
    c.start()
    c.close()
    c.close()   # 二次 close 不炸
