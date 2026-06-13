"""MCP 目录读取与启用判定（骨架，stdlib only）。

骨架阶段用极简解析读 registry.yaml；正式版接 ARS 的 mcp/client.py。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

REGISTRY = Path(__file__).with_name("registry.yaml")


def _parse_registry(path: Path) -> list:
    """极简解析 registry.yaml 的 servers 列表，避免引入 pyyaml。"""
    servers: list = []
    cur = None
    if not path.exists():
        return servers
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- name:"):
            if cur:
                servers.append(cur)
            cur = {"name": stripped.split(":", 1)[1].strip()}
        elif cur is not None and ":" in stripped:
            key, val = stripped.split(":", 1)
            cur[key.strip()] = val.split("#", 1)[0].strip()
    if cur:
        servers.append(cur)
    return servers


def _is_enabled(enable_when: str) -> bool:
    if enable_when == "always":
        return True
    if enable_when.startswith("env:"):
        return bool(os.environ.get(enable_when[4:]))
    if enable_when.startswith("detect:"):
        return shutil.which(enable_when[7:]) is not None
    return False


def list_mcp_catalog() -> list:
    """读取目录并标注每个 MCP 当前是否满足启用条件。"""
    out = []
    for s in _parse_registry(REGISTRY):
        ew = s.get("enable_when", "always")
        out.append({
            "name": s.get("name", "?"),
            "category": s.get("category", "?"),
            "enable_when": ew,
            "enabled": _is_enabled(ew),
        })
    return out
