"""Read-only discovery of Claude Code and Codex MCP configurations.

Only stdio servers can currently be executed by PsyClaw's MCP client. Runtime
environment values stay in private fields and must never be rendered in a
catalog or Agent prompt.
"""
from __future__ import annotations

import ast
import json
import re
import shlex
import sqlite3
from pathlib import Path


def _command(config: dict) -> str:
    command = str(config.get("command") or "").strip()
    args = config.get("args") or []
    if not command:
        return ""
    if not isinstance(args, list):
        args = []
    return shlex.join([command, *(str(arg) for arg in args)])


def _entry(name: str, config: dict, *, host: str, scope: str,
           path: Path, project_dir: str) -> dict | None:
    if not isinstance(config, dict) or not name:
        return None
    command = _command(config)
    url = str(config.get("url") or "").strip()
    transport = str(config.get("type") or ("stdio" if command else "http" if url else "unknown"))
    disabled = config.get("enabled") is False or config.get("disabled") is True
    if disabled:
        enable_when = "disabled:host"
    elif transport not in {"stdio", ""} or url:
        enable_when = f"unsupported:{transport}"
    elif scope == "project":
        # A repository-controlled MCP config is executable code. Recognition
        # is allowed by default; execution requires explicit local trust.
        enable_when = "trust:project"
    else:
        enable_when = "always"
    env = config.get("env") or {}
    if not isinstance(env, dict):
        env = {}
    cwd = str(config.get("cwd") or (Path(project_dir).resolve() if scope == "project" else Path.home()))
    return {
        "name": name, "category": "host", "origin": host, "_scope": scope,
        "enable_when": enable_when, "command": command, "provides": "", "tools": "",
        "transport": transport, "config_path": str(path),
        "env_keys": sorted(str(key) for key in env),
        "_runtime_env": {str(key): str(value) for key, value in env.items()},
        "_runtime_cwd": cwd,
    }


def _json_file(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _claude_sources(project_dir: str) -> list[tuple[Path, str, bool]]:
    root = Path(project_dir).resolve()
    return [
        (root / ".mcp.json", "project", False),
        (root / ".claude" / "mcp.json", "project", False),
        (root / ".claude" / "settings.json", "project", False),
        (root / ".claude" / "settings.local.json", "project", False),
        (Path.home() / ".claude.json", "global", True),
        (Path.home() / ".claude" / "mcp.json", "global", False),
        (Path.home() / ".claude" / "settings.json", "global", False),
        (Path.home() / ".claude" / "settings.local.json", "global", False),
    ]


def _claude_entries(project_dir: str) -> list[dict]:
    root = str(Path(project_dir).resolve())
    out: list[dict] = []
    seen_paths: set[str] = set()
    for path, scope, has_projects in _claude_sources(project_dir):
        key = str(path)
        if key in seen_paths or not path.is_file():
            continue
        seen_paths.add(key)
        data = _json_file(path)
        groups = [data.get("mcpServers") or data.get("mcp_servers") or {}]
        if has_projects:
            projects = data.get("projects") or {}
            if isinstance(projects, dict):
                for project_path, project_config in projects.items():
                    try:
                        same_project = str(Path(project_path).expanduser().resolve()) == root
                    except OSError:
                        same_project = False
                    if same_project and isinstance(project_config, dict):
                        groups.append(project_config.get("mcpServers") or {})
        for group in groups:
            if not isinstance(group, dict):
                continue
            for name, config in group.items():
                item = _entry(str(name), config, host="claude-code", scope=scope,
                              path=path, project_dir=project_dir)
                if item:
                    out.append(item)
    return out


def _toml_value(raw: str):
    value = raw.strip()
    try:
        return json.loads(value)
    except ValueError:
        pass
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError):
        if value.lower() in {"true", "false"}:
            return value.lower() == "true"
        return value.strip("'\"")


_SECTION = re.compile(r'^\[mcp_servers\.(?:"([^"]+)"|\'([^\']+)\'|([^\.\]]+))(?:\.(env))?\]$')


def _minimal_codex_toml(path: Path) -> dict[str, dict]:
    """Parse only ``mcp_servers`` tables on Python versions without tomllib."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    servers: dict[str, dict] = {}
    current: dict | None = None
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _SECTION.match(line)
        if match:
            name = next(x for x in match.groups()[:3] if x is not None)
            server = servers.setdefault(name, {})
            current = server.setdefault("env", {}) if match.group(4) else server
            continue
        if line.startswith("["):
            current = None
            continue
        if current is not None and "=" in line:
            key, value = line.split("=", 1)
            current[key.strip()] = _toml_value(value)
    return servers


def _codex_file(path: Path) -> dict[str, dict]:
    try:
        import tomllib  # type: ignore[import-not-found]
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        servers = data.get("mcp_servers") or {}
        return servers if isinstance(servers, dict) else {}
    except (ImportError, OSError, ValueError):
        return _minimal_codex_toml(path)


def _codex_entries(project_dir: str) -> list[dict]:
    root = Path(project_dir).resolve()
    out = []
    for path, scope in ((root / ".codex" / "config.toml", "project"),
                        (Path.home() / ".codex" / "config.toml", "global")):
        if not path.is_file():
            continue
        for name, config in _codex_file(path).items():
            item = _entry(str(name), config, host="codex", scope=scope,
                          path=path, project_dir=project_dir)
            if item:
                out.append(item)
    return out


def _cc_switch_entries(project_dir: str) -> list[dict]:
    """Read cc-switch's MCP table without writing or exposing its JSON secrets."""
    db = Path.home() / ".cc-switch" / "cc-switch.db"
    if not db.is_file():
        return []
    out = []
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        rows = conn.execute(
            "SELECT name, server_config, enabled_claude, enabled_codex, "
            "enabled_gemini, enabled_opencode, enabled_hermes FROM mcp_servers"
        ).fetchall()
    except (OSError, sqlite3.Error):
        return []
    finally:
        try:
            conn.close()
        except (UnboundLocalError, sqlite3.Error):
            pass
    for name, raw, *enabled in rows:
        try:
            config = json.loads(raw or "{}")
        except (TypeError, ValueError):
            continue
        if not isinstance(config, dict):
            continue
        config["enabled"] = any(str(flag).lower() in {"1", "true", "yes"} for flag in enabled)
        item = _entry(str(name), config, host="cc-switch", scope="global",
                      path=db, project_dir=project_dir)
        if item:
            out.append(item)
    return out


def discover_host_mcp_configs(project_dir: str = ".") -> list[dict]:
    """Return normalized host MCP entries; values of ``env`` remain private."""
    return (_claude_entries(project_dir) + _codex_entries(project_dir) +
            _cc_switch_entries(project_dir))
