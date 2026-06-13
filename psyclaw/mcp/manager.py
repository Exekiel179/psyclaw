"""MCP 目录读取、启用判定、健康检查与能力探测（stdlib only）。

骨架阶段用极简解析读 registry.yaml；正式版接 ARS 的 mcp/client.py。
"""

from __future__ import annotations

import importlib.util
import os
import shutil
from pathlib import Path

REGISTRY = Path(__file__).with_name("registry.yaml")

# 各服务器需采集的密钥环境变量（向导使用）
SERVER_SECRETS: dict[str, list[str]] = {
    "zotero-mcp": ["ZOTERO_API_KEY", "ZOTERO_LIBRARY_ID"],
    "osf-mcp": ["OSF_TOKEN"],
}

# 各服务器的友好描述（向导 + doctor 使用）
SERVER_NOTES: dict[str, str] = {
    "pystat": "Python 统计库（pingouin/statsmodels 等）",
    "r-mcp": "R 统计环境（lavaan/lme4/semTools）",
    "mplus-mcp": "Mplus CFA/SEM/LGM/Mixture 语法生成",
    "spss-mcp": "SPSS 语法生成 + 批处理执行",
    "mne-mcp": "EEG/MEG/ERP 分析（MNE-Python）",
    "stata-mcp": "Stata do-file 生成（面板/IV/生存等）",
    "zotero-mcp": "Zotero 文献管理（搜索/引用/全文/撤稿）",
    "lit-search-mcp": "文献多源检索（PubMed/OpenAlex/Semantic Scholar）",
    "osf-mcp": "OSF 开放科学（预注册/数据托管）",
}


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


def health_check(entry: dict) -> dict:
    """对单个 MCP 条目做健康探测，返回 {"ok": bool, "detail": str}。

    启用条件不满足 → ok=False（未启用，不是错误）。
    对 Python 内置服务器：检查模块是否可找到（find_spec，无副作用）。
    对 env:/detect: 服务器：条件满足即视为健康（无法进一步 ping）。
    """
    ew = entry.get("enable_when", "always")
    if not _is_enabled(ew):
        if ew.startswith("env:"):
            return {"ok": False, "detail": f"未设置 ${ew[4:]}（可选）"}
        if ew.startswith("detect:"):
            return {"ok": False, "detail": f"未检测到 {ew[7:]}（可选）"}
        return {"ok": False, "detail": f"条件未满足: {ew}"}

    # Python 内置命令服务器 — 检查模块是否可找到
    command = entry.get("command", "")
    if command.startswith("python -m "):
        mod_path = command[len("python -m "):]
        try:
            spec = importlib.util.find_spec(mod_path)
        except (ModuleNotFoundError, ValueError):
            spec = None
        if spec is None:
            return {"ok": False, "detail": f"模块未找到: {mod_path}"}
        return {"ok": True, "detail": "模块就绪"}

    # env:/detect: — 条件已满足
    if ew.startswith("env:"):
        return {"ok": True, "detail": f"${ew[4:]} 已设置"}
    if ew.startswith("detect:"):
        path = shutil.which(ew[7:])
        return {"ok": True, "detail": f"检测到 {path}"}
    return {"ok": True, "detail": "就绪"}


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
            "provides": s.get("provides", ""),
            "command": s.get("command", ""),
            "note": SERVER_NOTES.get(s.get("name", ""), ""),
        })
    return out


def list_mcp_catalog_with_health() -> list:
    """读取目录并包含实时健康检查结果。"""
    out = []
    for s in _parse_registry(REGISTRY):
        ew = s.get("enable_when", "always")
        enabled = _is_enabled(ew)
        h = health_check(s)
        out.append({
            "name": s.get("name", "?"),
            "category": s.get("category", "?"),
            "enable_when": ew,
            "enabled": enabled,
            "provides": s.get("provides", ""),
            "command": s.get("command", ""),
            "note": SERVER_NOTES.get(s.get("name", ""), ""),
            "health": h,
        })
    return out


def probe_capabilities(catalog: list | None = None) -> dict[str, list[str]]:
    """从已启用且健康的 MCP 聚合能力集合。

    返回 {capability: [server_name, ...]}，仅包含健康服务器提供的能力。
    """
    if catalog is None:
        catalog = list_mcp_catalog_with_health()
    caps: dict[str, list[str]] = {}
    for entry in catalog:
        if not (entry.get("enabled") and entry.get("health", {}).get("ok")):
            continue
        provides_raw = entry.get("provides", "")
        if not provides_raw:
            continue
        # provides stored as "[cap1, cap2, ...]" from simple parser
        provides_str = provides_raw.strip("[]").replace("'", "").replace('"', "")
        for cap in provides_str.split(","):
            cap = cap.strip()
            if cap:
                caps.setdefault(cap, []).append(entry["name"])
    return caps
