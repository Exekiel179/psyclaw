"""把已启用+健康的 MCP 服务器工具并进 agent 工具集(v0.5 feat-040;v0.15 feat-138 惰性化)。

兑现「统计外移到 MCP」的最后一步:此前 MCP 只做目录/健康检查,现在 agent 循环
(toolloop.build_tools)真正能调用它们暴露的工具。

纪律(守 fail-safe + 不拖垮工具集):
- 只并入 enabled + health.ok + 有 command 的服务器(env:/detect: 无 command 的跳过)。
- **惰性登记(feat-138)**:merge 阶段不再逐服务器起子进程 list_tools(npx 系冷启
  会把 /agent on 首响应拖到分钟级)。有磁盘缓存(.psyclaw/mcp_tools_cache.json)
  按缓存登记全目录;无缓存但 registry 写了 provides 按 provides 登记工具名;
  真正被调用时才起对应子进程,并顺带把全目录回填缓存(下次 merge 即全量)。
  两者皆无 → 保持老的 eager list_tools(用户自定义无 provides 的服务器不回归),
  eager 拿到目录也回填缓存。`PSYCLAW_MCP_LAZY=0` 可整体退回 eager。
- 客户端**进程级缓存**(按 command 复用一个子进程),避免每次 build_tools 都起新进程;
  atexit 统一收尾。长会话 REPL 反复建工具集也只留一个连接。
- tools/list 用短超时——某个服务器起不来/慢,不阻塞 agent 启动;失败只是少几个工具。
- MCP 工具名加 `mcp__<server>__<tool>` 前缀防撞内置;一律 side_effect=True 走
  fail-closed 批准(外部进程执行,保守)。
- 环境变量 `PSYCLAW_MCP_TOOLS=0` 可整体关闭(默认开)。
"""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import time
from pathlib import Path

_MERGE_TIMEOUT = 10.0
_CALL_TIMEOUT = 30.0            # 首次真调用要吞下 npx 冷启,给足余量
_CACHE_REL = Path(".psyclaw") / "mcp_tools_cache.json"
_FAILURE_CACHE_TTL = 60.0
_clients: dict = {}             # command -> MCPClient(进程级复用)
_refreshed: set[str] = set()    # 本进程内已回填过缓存的 command
_failures: dict[str, tuple[float, str]] = {}


def _get_client(command: str, runtime_env: dict | None = None, runtime_cwd: str = ""):
    from psyclaw.mcp.client import MCPClient
    env = {str(k): str(v) for k, v in (runtime_env or {}).items()}
    identity = command
    if env or runtime_cwd:
        material = json.dumps({"env": env, "cwd": runtime_cwd}, sort_keys=True).encode()
        identity = f"{command}\0{hashlib.sha256(material).hexdigest()}"
    c = _clients.get(identity)
    if c is None:
        c = MCPClient(command, timeout=_MERGE_TIMEOUT, env=env, cwd=runtime_cwd or None)
        _clients[identity] = c
    return c


def _client_identity(command: str, runtime_env: dict | None = None,
                     runtime_cwd: str = "") -> str:
    env = {str(k): str(v) for k, v in (runtime_env or {}).items()}
    identity = command
    if env or runtime_cwd:
        material = json.dumps({"env": env, "cwd": runtime_cwd}, sort_keys=True).encode()
        identity = f"{command}\0{hashlib.sha256(material).hexdigest()}"
    return identity


def _cached_failure(command: str, runtime_env: dict | None = None,
                    runtime_cwd: str = "") -> str | None:
    identity = _client_identity(command, runtime_env, runtime_cwd)
    item = _failures.get(identity)
    if not item:
        return None
    started, message = item
    if time.monotonic() - started > _FAILURE_CACHE_TTL:
        _failures.pop(identity, None)
        return None
    return message


def _remember_failure(command: str, message: str,
                      runtime_env: dict | None = None,
                      runtime_cwd: str = "") -> None:
    _failures[_client_identity(command, runtime_env, runtime_cwd)] = (
        time.monotonic(), str(message))


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


def _lazy_enabled() -> bool:
    return os.environ.get("PSYCLAW_MCP_LAZY", "1").strip().lower() not in ("0", "false", "no")


# -- 工具目录缓存(feat-138) ---------------------------------------------------


def _load_tool_cache(project_dir: str) -> dict:
    try:
        raw = json.loads((Path(project_dir) / _CACHE_REL).read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _save_tool_cache(project_dir: str, command: str, metas: list[dict]) -> None:
    """把某 command 的工具目录写进缓存(fail-safe:写不了不抛)。"""
    try:
        path = Path(project_dir) / _CACHE_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        cache = _load_tool_cache(project_dir)
        cache[command] = metas
        path.write_text(json.dumps(cache, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _tool_metas(mcp_tools: list[dict]) -> list[dict]:
    return [{"name": t.get("name", ""),
             "description": t.get("description", ""),
             "args": _schema_hint(t.get("inputSchema") or {})}
            for t in mcp_tools if t.get("name")]


def _refresh_cache_once(project_dir: str, command: str, client) -> None:
    """真调用后顺带回填全目录(每进程每 command 一次;起不来拿不到目录则下次再试)。"""
    if command in _refreshed:
        return
    metas = _tool_metas(client.list_tools())
    if metas:
        _refreshed.add(command)
        _save_tool_cache(project_dir, command, metas)


def _normalize_mcp_result(result) -> dict:
    """把 MCP 工具回执规整成 {ok, text, degraded?}。"""
    if isinstance(result, dict):
        out = {
            "ok": bool(result.get("ok", True)),
            "text": str(result.get("text", "")),
        }
        if "degraded" in result:
            out["degraded"] = bool(result.get("degraded"))
        if result.get("error_kind"):
            out["error_kind"] = str(result["error_kind"])
        return out
    return {"ok": True, "text": str(result)}


def _call_mcp_tool(command: str, tool: str, args: dict, project_dir: str,
                   runtime_env: dict | None = None, runtime_cwd: str = "") -> dict:
    cached = _cached_failure(command, runtime_env, runtime_cwd)
    if cached:
        status = {"ok": False, "text": cached}
        if "统计库未安装" in cached:
            status["degraded"] = True
        return status
    client = (_get_client(command, runtime_env, runtime_cwd)
              if (runtime_env or runtime_cwd) else _get_client(command))
    client.timeout = max(client.timeout, _CALL_TIMEOUT)
    status = _normalize_mcp_result(client.call_tool_status(tool, args))
    text = str(status.get("text", ""))
    if (not status.get("ok")) or "统计库未安装" in text:
        if text and (status.get("error_kind") in {"startup", "transport"}
                     or "统计库未安装" in text):
            _remember_failure(command, text, runtime_env, runtime_cwd)
        if "统计库未安装" in text:
            return {"ok": False, "text": text, "degraded": True}
    _refresh_cache_once(project_dir, command, client)
    return status


def _provides_names(raw) -> list[str]:
    """registry 的 provides 可能是极简解析出的 "[a, b]" 字符串或真列表。"""
    if isinstance(raw, (list, tuple)):
        return [str(x).strip() for x in raw if str(x).strip()]
    s = str(raw or "").strip().strip("[]").replace("'", "").replace('"', "")
    return [p.strip() for p in s.split(",") if p.strip()]


def _register_lazy(tools: dict, server: str, command: str, meta: dict,
                   project_dir: str, runtime_env: dict | None = None,
                   runtime_cwd: str = "") -> None:
    tname = meta.get("name", "")
    if not tname:
        return
    desc = f"[MCP:{server}] {meta.get('description', '')}".strip()

    def _run(a, _cmd=command, _t=tname, _pd=project_dir,
             _env=runtime_env, _cwd=runtime_cwd):
        status = _call_mcp_tool(_cmd, _t, a, _pd, _env, _cwd)
        return status["text"]

    def _run_status(a, _cmd=command, _t=tname, _pd=project_dir,
                    _env=runtime_env, _cwd=runtime_cwd):
        return _call_mcp_tool(_cmd, _t, a, _pd, _env, _cwd)

    tools[f"mcp__{server}__{tname}"] = {"desc": desc,
                                        "args": meta.get("args", ""),
                                        "run": _run, "call_status": _run_status,
                                        "side_effect": True}


def merge_mcp_tools(tools: dict, project_dir: str = ".") -> None:
    """就地把 MCP 工具并入 tools。任何异常都不外抛(与插件加载同构)。"""
    if not _enabled():
        return
    try:
        from psyclaw.mcp.manager import list_mcp_catalog_with_health
        try:
            catalog = list_mcp_catalog_with_health(project_dir, include_runtime=True)
        except TypeError:  # test/third-party compatibility with the older callable
            catalog = list_mcp_catalog_with_health(project_dir)
    except Exception:  # noqa: BLE001
        return
    lazy = _lazy_enabled()
    cache = _load_tool_cache(project_dir) if lazy else {}
    for entry in catalog:
        command = entry.get("_runtime_command") or entry.get("command") or ""
        if not (entry.get("enabled") and command):
            continue
        if not (entry.get("health") or {}).get("ok"):
            continue
        server = entry.get("name", "?")
        runtime_env = entry.get("_runtime_env") or {}
        runtime_cwd = str(entry.get("_runtime_cwd") or "")

        if lazy:
            metas = cache.get(command)
            if not metas:
                # tools = 真实工具名(优先);provides 是能力标签,仅在恰为
                # 工具名的服务器(browser/sequential-thinking)可兜底
                names = (_provides_names(entry.get("tools"))
                         or _provides_names(entry.get("provides")))
                metas = [{"name": n,
                          "description": f"{n}(目录未缓存,首次调用后补全)",
                          "args": ""}
                         for n in names]
            if metas:
                for m in metas:
                    _register_lazy(tools, server, command, m, project_dir,
                                   runtime_env, runtime_cwd)
                continue

        # eager 老路径:无缓存也无 provides(或 PSYCLAW_MCP_LAZY=0)
        try:
            client = (_get_client(command, runtime_env, runtime_cwd)
                      if (runtime_env or runtime_cwd) else _get_client(command))
            mcp_tools = client.list_tools()
        except Exception:  # noqa: BLE001
            continue
        metas = _tool_metas(mcp_tools)
        if metas:
            _refreshed.add(command)
            _save_tool_cache(project_dir, command, metas)
        for t in mcp_tools:
            tname = t.get("name")
            if not tname:
                continue
            full = f"mcp__{server}__{tname}"
            desc = f"[MCP:{server}] {t.get('description', '')}".strip()
            args_hint = _schema_hint(t.get("inputSchema") or {})

            def _run(a, _client=client, _tname=tname):
                return _client.call_tool(_tname, a)

            def _run_status(a, _client=client, _tname=tname, _cmd=command):
                status = _normalize_mcp_result(_client.call_tool_status(_tname, a))
                text = str(status.get("text", ""))
                if "统计库未安装" in text:
                    _remember_failure(_cmd, text, runtime_env, runtime_cwd)
                    return {"ok": False, "text": text, "degraded": True}
                if (not status.get("ok") and text
                        and status.get("error_kind") in {"startup", "transport"}):
                    _remember_failure(_cmd, text, runtime_env, runtime_cwd)
                return status

            tools[full] = {"desc": desc, "args": args_hint, "run": _run,
                           "call_status": _run_status, "side_effect": True}


def _schema_hint(schema: dict) -> str:
    """把 inputSchema 压成简短参数提示串(给工具目录展示)。"""
    props = (schema or {}).get("properties") or {}
    required = set((schema or {}).get("required") or [])
    parts = []
    for k, v in props.items():
        typ = v.get("type", "any") if isinstance(v, dict) else "any"
        parts.append(f"{k}:{typ}" + ("" if k in required else "?"))
    return ", ".join(parts)
