"""MCP stdio 服务器基座(stdlib only)。

实现 Model Context Protocol 的 stdio 传输(换行分隔 JSON-RPC 2.0):
initialize / tools/list / tools/call / ping。
PsyClaw 内置 MCP(mne/spss)基于此;也可被 Claude Desktop/任意 MCP 客户端直连:

    {"command": "python", "args": ["-m", "psyclaw.mcp.servers.mne_server"]}
"""

from __future__ import annotations

import json
import sys
import traceback

PROTOCOL_VERSION = "2024-11-05"


class MCPServer:
    def __init__(self, name: str, version: str = "0.1.0") -> None:
        self.name = name
        self.version = version
        self._tools: dict = {}   # name -> (schema_dict, handler)

    def tool(self, name: str, description: str, input_schema: dict):
        """装饰器:注册工具。handler(args: dict) -> str"""
        def deco(fn):
            self._tools[name] = (
                {"name": name, "description": description,
                 "inputSchema": {"type": "object",
                                 "properties": input_schema.get("properties", {}),
                                 "required": input_schema.get("required", [])}},
                fn,
            )
            return fn
        return deco

    # -- 协议处理 ------------------------------------------------------------

    def _handle(self, msg: dict) -> dict | None:
        mid = msg.get("id")
        method = msg.get("method", "")
        params = msg.get("params", {}) or {}

        if method == "initialize":
            return self._result(mid, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": self.name, "version": self.version},
            })
        if method in ("notifications/initialized", "initialized"):
            return None
        if method == "ping":
            return self._result(mid, {})
        if method == "tools/list":
            return self._result(mid, {"tools": [s for s, _ in self._tools.values()]})
        if method == "tools/call":
            tool_name = params.get("name", "")
            args = params.get("arguments", {}) or {}
            entry = self._tools.get(tool_name)
            if not entry:
                return self._error(mid, -32602, f"unknown tool: {tool_name}")
            try:
                text = entry[1](args)
                return self._result(mid, {
                    "content": [{"type": "text", "text": str(text)}],
                    "isError": False,
                })
            except Exception as exc:  # noqa: BLE001
                return self._result(mid, {
                    "content": [{"type": "text",
                                 "text": f"工具执行失败: {exc}\n{traceback.format_exc(limit=3)}"}],
                    "isError": True,
                })
        if mid is not None:
            return self._error(mid, -32601, f"method not found: {method}")
        return None

    @staticmethod
    def _result(mid, result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    @staticmethod
    def _error(mid, code, message):
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}

    # -- 主循环 --------------------------------------------------------------

    def run(self) -> int:
        for raw in sys.stdin:
            raw = raw.strip()
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            resp = self._handle(msg)
            if resp is not None:
                sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                sys.stdout.flush()
        return 0
