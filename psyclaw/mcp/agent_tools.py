"""把已启用+健康的 MCP 服务器工具并进 agent 工具集(v0.5 feat-040)。

兑现「统计外移到 MCP」的最后一步:此前 MCP 只做目录/健康检查,现在 agent 循环
(toolloop.build_tools)真正能调用它们暴露的工具。

纪律(守 fail-safe + 不拖垮工具集):
- 只并入 enabled + health.ok + 有 command 的服务器(env:/detect: 无 command 的跳过)。
- 客户端**进程级缓存**(按 command 复用一个子进程),避免每次 build_tools 都起新进程;
  atexit 统一收尾。长会话 REPL 反复建工具集也只留一个连接。
- tools/list 用短超时——某个服务器起不来/慢,不阻塞 agent 启动;失败只是少几个工具。
- MCP 工具名加 `mcp__<server>__<tool>` 前缀防撞内置;一律 side_effect=True 走
  fail-closed 批准(外部进程执行,保守)。
- 环境变量 `PSYCLAW_MCP_TOOLS=0` 可整体关闭(默认开)。
"""

from __future__ import annotations

import atexit
import os

_MERGE_TIMEOUT = 10.0
_clients: dict = {}   # command -> MCPClient(进程级复用)


def _get_client(command: str):
    from psyclaw.mcp.client import MCPClient
    c = _clients.get(command)
    if c is None:
        c = MCPClient(command, timeout=_MERGE_TIMEOUT)
        _clients[command] = c
    return c


@atexit.register
def _close_all() -> None:
    for c in list(_clients.values()):
        try:
            c.close()
        except Exception:  # noqa: BLE001
            pass
    _clients.clear()


def _enabled() -> bool:
    return os.environ.get("PSYCLAW_MCP_TOOLS", "1").strip().lower() not in ("0", "false", "no")


def merge_mcp_tools(tools: dict, project_dir: str = ".") -> None:
    """就地把 MCP 工具并入 tools。任何异常都不外抛(与插件加载同构)。"""
    if not _enabled():
        return
    try:
        from psyclaw.mcp.manager import list_mcp_catalog_with_health
        catalog = list_mcp_catalog_with_health(project_dir)
    except Exception:  # noqa: BLE001
        return
    for entry in catalog:
        command = entry.get("command") or ""
        if not (entry.get("enabled") and command):
            continue
        if not (entry.get("health") or {}).get("ok"):
            continue
        server = entry.get("name", "?")
        try:
            client = _get_client(command)
            mcp_tools = client.list_tools()
        except Exception:  # noqa: BLE001
            continue
        for t in mcp_tools:
            tname = t.get("name")
            if not tname:
                continue
            full = f"mcp__{server}__{tname}"
            desc = f"[MCP:{server}] {t.get('description', '')}".strip()
            args_hint = _schema_hint(t.get("inputSchema") or {})

            def _run(a, _client=client, _tname=tname):
                return _client.call_tool(_tname, a)

            tools[full] = {"desc": desc, "args": args_hint, "run": _run,
                           "side_effect": True}


def _schema_hint(schema: dict) -> str:
    """把 inputSchema 压成简短参数提示串(给工具目录展示)。"""
    props = (schema or {}).get("properties") or {}
    required = set((schema or {}).get("required") or [])
    parts = []
    for k, v in props.items():
        typ = v.get("type", "any") if isinstance(v, dict) else "any"
        parts.append(f"{k}:{typ}" + ("" if k in required else "?"))
    return ", ".join(parts)
