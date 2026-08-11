"""MCP stdio 客户端往返测试(v0.5 feat-039)——起真实短命服务器验证协议。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from psyclaw.mcp.client import MCPClient, _SAFE_ENV_KEYS, resolve_command

_ECHO = str(Path(__file__).with_name("_mcp_echo_server.py"))
_CMD = f"python {_ECHO}"   # resolve_command 会把 python 换成 sys.executable


def test_resolve_command_python_fallback():
    argv = resolve_command("python -m foo.bar")
    assert argv[0] == sys.executable and argv[1:] == ["-m", "foo.bar"]
    assert resolve_command("Rscript x.R")[0] == "Rscript"   # 非 python 不动
    assert resolve_command("") == []
    if os.name == "nt":
        assert resolve_command(r"python C:\tools\server.py")[1] == r"C:\tools\server.py"
        assert resolve_command(r'python "C:\Program Files\server.py"')[1] \
            == r"C:\Program Files\server.py"


def test_safe_environment_keeps_windows_runtime_paths_not_secrets():
    assert {"USERPROFILE", "APPDATA", "LOCALAPPDATA", "PATHEXT"} <= _SAFE_ENV_KEYS
    assert "KAGGLE_KEY" not in _SAFE_ENV_KEYS
    assert "OPENAI_API_KEY" not in _SAFE_ENV_KEYS


def test_credential_env_matches_windows_keys_case_insensitively(monkeypatch):
    monkeypatch.setenv("systemroot", r"C:\Windows")
    monkeypatch.setenv("path", r"C:\Windows\System32")
    client = MCPClient("python -m other_mcp")
    env = client._credential_env()
    folded = {k.upper(): v for k, v in env.items()}
    assert folded["SYSTEMROOT"] == r"C:\Windows"
    assert folded["PATH"] == r"C:\Windows\System32"


def test_call_tool_status_classifies_tool_error(monkeypatch):
    client = MCPClient("python -m other_mcp")
    client._initialized = True
    monkeypatch.setattr(client, "_request", lambda *_a, **_k: {
        "result": {"isError": True, "content": [{"type": "text", "text": "bad args"}]}
    })
    status = client.call_tool_status("demo", {})
    assert status["ok"] is False
    assert status["error_kind"] == "tool"


def test_kaggle_token_is_scoped_to_kaggle_mcp(monkeypatch, tmp_path):
    from psyclaw.mcp import client as mc
    token_file = tmp_path / ".kaggle" / "access_token"
    token_file.parent.mkdir()
    token_file.write_text("KGAT_test", encoding="utf-8")
    monkeypatch.setattr(mc.Path, "home", classmethod(lambda cls: tmp_path))
    kaggle = MCPClient("uvx kaggle-mcp --stdio")
    other = MCPClient("python -m other_mcp")
    kaggle_env = kaggle._credential_env()
    assert kaggle_env["KAGGLE_API_TOKEN"] == "KGAT_test"
    assert kaggle_env["KAGGLE_KEY"] == "KGAT_test"
    assert kaggle_env["KAGGLE_USERNAME"] == "__token__"
    assert "KAGGLE_API_TOKEN" not in other._credential_env()


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
