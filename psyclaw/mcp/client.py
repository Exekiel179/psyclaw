"""MCP stdio 客户端(stdlib only)——与 server_base.py 对偶。

起一个 MCP 服务器子进程,用换行分隔的 JSON-RPC 2.0 走 initialize / tools/list /
tools/call。PsyClaw 的 agent 循环(feat-040)据此把外部 MCP 工具并进内置工具集,
兑现「统计外移到 MCP」——从此前只做目录/健康检查,到真正可调用。

设计纪律(守 PsyClaw fail-safe + 零依赖):
- **每步超时不挂死**:后台读线程 + 队列,请求按 id 匹配;超时返回错误而非阻塞 agent。
- **优雅降级**:进程起不来 / 坏 JSON / 服务器异常 → 返回错误串,不抛穿主循环。
- **`python` 兜底**:command 里的 `python` 换 sys.executable(本机可能只有 python3)。
- **上下文管理器**:with MCPClient(...) as c 用完杀子进程,绝不留孤儿。

可单测:_next_line 读逻辑、命令解析、超时路径都能用假子进程或短命服务器覆盖。
"""

from __future__ import annotations

import json
import queue
import shlex
import subprocess
import sys
import threading

_DEFAULT_TIMEOUT = 30.0
PROTOCOL_VERSION = "2024-11-05"


def resolve_command(command: str) -> list[str]:
    """把 registry 的 command 字符串拆成 argv;开头的 `python` 换成当前解释器。

    本机可能只有 python3(无 python),内置服务器 command 写的是 `python -m …`——
    直接跑会 command not found,故统一兜底到 sys.executable。
    """
    argv = shlex.split(command or "")
    if argv and argv[0] in ("python", "python3"):
        argv[0] = sys.executable
    return argv


class MCPClient:
    """一个 MCP 服务器子进程的会话。惰性:__init__ 不起进程,start()/首个调用才起。"""

    def __init__(self, command: str, timeout: float = _DEFAULT_TIMEOUT) -> None:
        self.command = command
        self.timeout = timeout
        self._proc: subprocess.Popen | None = None
        self._q: queue.Queue = queue.Queue()
        self._reader: threading.Thread | None = None
        self._id = 0
        self._initialized = False
        self._start_error: str | None = None

    # -- 生命周期 ------------------------------------------------------------

    def __enter__(self) -> "MCPClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def start(self) -> str | None:
        """起子进程并做 initialize 握手。返回 None=成功,否则错误串。"""
        if self._proc is not None:
            return self._start_error
        argv = resolve_command(self.command)
        if not argv:
            self._start_error = "MCP 启动失败:command 为空"
            return self._start_error
        try:
            self._proc = subprocess.Popen(
                argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1,
            )
        except OSError as exc:
            self._start_error = f"MCP 启动失败:{exc}"
            return self._start_error
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()
        # 握手:initialize → notifications/initialized
        resp = self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "psyclaw", "version": "0.5.0"},
        })
        if "error" in resp:
            self._start_error = f"MCP initialize 失败:{resp['error']}"
            return self._start_error
        self._notify("notifications/initialized", {})
        self._initialized = True
        return None

    def close(self) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.stdin and not self._proc.stdin.closed:
                self._proc.stdin.close()
        except OSError:
            pass
        try:
            self._proc.terminate()
            self._proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                self._proc.kill()
            except OSError:
                pass
        self._proc = None

    # -- 传输 ----------------------------------------------------------------

    def _pump(self) -> None:
        """后台读子进程 stdout,逐行 JSON 入队。进程结束/管道断则收尾。"""
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for raw in proc.stdout:
                line = raw.strip()
                if not line:
                    continue
                try:
                    self._q.put(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except (OSError, ValueError):
            pass
        self._q.put({"__eof__": True})

    def _send(self, msg: dict) -> bool:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.stdin.closed:
            return False
        try:
            proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
            proc.stdin.flush()
            return True
        except (OSError, ValueError):
            return False

    def _notify(self, method: str, params: dict) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method: str, params: dict) -> dict:
        """发一条带 id 的请求,等到 id 匹配的响应(或超时/EOF)。"""
        self._id += 1
        want = self._id
        if not self._send({"jsonrpc": "2.0", "id": want, "method": method,
                           "params": params}):
            return {"error": {"code": -1, "message": "MCP 写入失败(进程已退出?)"}}
        import time as _time
        deadline = _time.monotonic() + self.timeout
        while True:
            remaining = deadline - _time.monotonic()
            if remaining <= 0:
                return {"error": {"code": -2, "message": f"MCP 响应超时(>{self.timeout}s)"}}
            try:
                msg = self._q.get(timeout=remaining)
            except queue.Empty:
                return {"error": {"code": -2, "message": f"MCP 响应超时(>{self.timeout}s)"}}
            if msg.get("__eof__"):
                return {"error": {"code": -3, "message": "MCP 进程提前退出"}}
            if msg.get("id") == want:
                return msg

    # -- 高层 API ------------------------------------------------------------

    def list_tools(self) -> list[dict]:
        """返回 [{name, description, inputSchema}];失败返回 []。"""
        if not self._initialized and self.start() is not None:
            return []
        resp = self._request("tools/list", {})
        if "error" in resp:
            return []
        return (resp.get("result") or {}).get("tools", []) or []

    def call_tool(self, name: str, arguments: dict) -> str:
        """调用工具,返回文本结果(错误也归一为可读串,不抛)。"""
        return self.call_tool_status(name, arguments)["text"]

    def call_tool_status(self, name: str, arguments: dict) -> dict:
        """调用工具,返回结构化结果 {ok, text}(feat-079)。

        ok=False 覆盖:启动失败 / 传输错误 / isError 工具报错 / 空结果。
        文本仍归一为可读串,不抛——但调用方(如 pystat_bridge 的真结果守卫)
        可据 ok 结构化判定,而不必嗅探错误串措辞。
        """
        if not self._initialized:
            err = self.start()
            if err is not None:
                return {"ok": False, "text": err}
        resp = self._request("tools/call", {"name": name, "arguments": arguments or {}})
        if "error" in resp:
            return {"ok": False,
                    "text": f"MCP 调用失败:{resp['error'].get('message', resp['error'])}"}
        result = resp.get("result") or {}
        parts = [c.get("text", "") for c in result.get("content", [])
                 if c.get("type") == "text"]
        text = "\n".join(p for p in parts if p)
        if not text:
            return {"ok": False, "text": "(空结果)"}
        if result.get("isError"):
            return {"ok": False, "text": f"MCP 工具报错:{text}"}
        return {"ok": True, "text": text}
