"""测试夹具:最小 MCP stdio 服务器(基于 server_base),供 client 往返测试。"""
from __future__ import annotations

from psyclaw.mcp.server_base import MCPServer

srv = MCPServer("psyclaw-test-echo", "0.0.1")


@srv.tool("echo", "回声", {"properties": {"text": {"type": "string"}},
                          "required": ["text"]})
def echo(args: dict) -> str:
    return f"echo: {args.get('text', '')}"


@srv.tool("boom", "总是报错", {"properties": {}, "required": []})
def boom(args: dict) -> str:
    raise RuntimeError("intentional")


if __name__ == "__main__":
    raise SystemExit(srv.run())
