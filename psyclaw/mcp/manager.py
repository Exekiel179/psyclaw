"""MCP 目录读取、启用判定、健康检查与能力探测（stdlib only）。

骨架阶段用极简解析读 registry.yaml；正式版接 ARS 的 mcp/client.py。
"""

from __future__ import annotations

import importlib.util
import os
import shlex
import shutil
import sys
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
    "mplus-mcp": "Mplus CFA/SEM/LGM/Mixture 语法生成【可选便捷集成，需安装 Mplus】",
    "spss-mcp": "SPSS 语法生成 + 批处理执行【用户自研，需安装 IBM SPSS Statistics】",
    "mne-mcp": "EEG/MEG/ERP 分析（MNE-Python）",
    "stata-mcp": "Stata do-file 生成（面板/IV/生存等）【可选便捷集成，需安装 Stata】",
    "zotero-mcp": "Zotero 文献管理（搜索/引用/全文/撤稿）",
    "lit-search-mcp": "文献多源检索（PubMed/OpenAlex/Semantic Scholar）",
    "osf-mcp": "OSF 开放科学（预注册/数据托管）",
    "kaggle": "Kaggle 数据集搜索、元数据查看与下载【可选，需 uvx 和 Kaggle API token】",
}

# origin=optional/user 的商业软件 MCP 不纳入 doctor 强制健康检查（可选，非核心路径）
OPTIONAL_ORIGINS = frozenset({"optional", "user"})


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


def is_optional(entry: dict) -> bool:
    """返回 True 表示该 MCP 为可选集成（commercial/user-built，不纳入强制健康检查）。"""
    return entry.get("origin", "builtin") in OPTIONAL_ORIGINS


def user_registries(project_dir: str = ".") -> list[tuple[Path, str]]:
    """用户级 MCP 目录(同 registry.yaml 格式):项目 .psyclaw/mcp.yaml + 全局 ~/.psyclaw/mcp.yaml。"""
    cands = [(Path(project_dir) / ".psyclaw" / "mcp.yaml", "project"),
             (Path.home() / ".psyclaw" / "mcp.yaml", "global")]
    return [(p, scope) for p, scope in cands if p.is_file()]


# feat-107:浏览器 MCP 的执行文件适配——chrome-devtools-mcp 默认只找 Chrome stable,
# 本机没装 Chrome 但有其他 Chromium 系(Edge/Arc/Brave/Chromium)时自动补
# --executablePath。与 client.resolve_command 把 python→sys.executable 同一先例:
# 环境适配,不是浏览器逻辑(仓内零浏览器代码铁律不破)。
_CHROMIUM_MAC = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Arc.app/Contents/MacOS/Arc",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]
_CHROMIUM_WIN = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]
_CHROMIUM_BINS = ["google-chrome", "google-chrome-stable", "chromium",
                  "chromium-browser", "microsoft-edge", "brave-browser"]


def detect_chromium_executable() -> str | None:
    """找一个本机可用的 Chromium 系浏览器执行文件;没有返回 None。"""
    plats = _CHROMIUM_MAC if sys.platform == "darwin" else (
        _CHROMIUM_WIN if os.name == "nt" else [])
    for p in plats:
        if Path(p).exists():
            return p
    for b in _CHROMIUM_BINS:
        w = shutil.which(b)
        if w:
            return w
    return None


def _adapt_browser_command(entry: dict) -> None:
    """browser 条目补 --executablePath(用户已自定义则不动;找不到浏览器留原样,
    调用时服务器会给出清晰报错)。"""
    if entry.get("name") != "browser":
        return
    cmd = entry.get("command", "")
    if not cmd or "--executablePath" in cmd:
        return
    exe = detect_chromium_executable()
    if exe:
        entry["command"] = f'{cmd} --executablePath "{exe}"'


def _display_command(entry: dict) -> str:
    """Show a host command without exposing token-like argv values."""
    command = str(entry.get("command", ""))
    if entry.get("origin") not in {"claude-code", "codex"}:
        return command
    try:
        argv = shlex.split(command)
    except ValueError:
        return "<invalid host command>"
    redact_next = False
    out = []
    for arg in argv:
        low = arg.lower()
        if redact_next:
            out.append("<redacted>")
            redact_next = False
            continue
        out.append(arg)
        if any(word in low for word in ("token", "secret", "password", "api-key", "apikey", "credential")):
            redact_next = True
    return shlex.join(out)


def _all_entries(project_dir: str = ".") -> list:
    """内置、PsyClaw 用户目录和宿主配置合并；先发现者优先。"""
    entries: list = []
    seen: set[str] = set()
    for s in _parse_registry(REGISTRY):
        s["_scope"] = "builtin"
        _adapt_browser_command(s)
        seen.add(s.get("name", "?"))
        entries.append(s)
    for path, scope in user_registries(project_dir):
        for s in _parse_registry(path):
            name = s.get("name", "?")
            if name in seen:
                continue          # 内置优先,用户不得覆盖同名内置定义
            s["_scope"] = scope
            s.setdefault("origin", "user")
            seen.add(name)
            entries.append(s)
    try:
        from psyclaw.mcp.host_configs import discover_host_mcp_configs
        host_entries = discover_host_mcp_configs(project_dir)
    except Exception:  # noqa: BLE001 — 坏宿主配置不拖垮 PsyClaw 目录
        host_entries = []
    host_counts: dict[str, int] = {}
    for s in host_entries:
        host_counts[s.get("name", "?")] = host_counts.get(s.get("name", "?"), 0) + 1
    preferred_host = os.environ.get("PSYCLAW_MCP_SOURCE_PREFERENCE", "").strip().lower()
    for s in host_entries:
        name = s.get("name", "?")
        # A built-in or PsyClaw user definition owns its name. Host shadows
        # are omitted from the callable catalog rather than shown as a second
        # disabled copy.
        if name in seen:
            continue
        preferred = host_counts.get(name, 0) > 1 and s.get("origin") == preferred_host
        if host_counts.get(name, 0) > 1 and not preferred:
            # Keep duplicate metadata visible, but make every ambiguous host
            # entry non-callable. Builtins/PsyClaw definitions still remain.
            s = dict(s)
            s["_conflict"] = True
            s["enable_when"] = "conflict:host"
            entries.append(s)
            continue
        seen.add(name)
        entries.append(s)
    return entries


def _is_enabled(enable_when: str) -> bool:
    if enable_when == "always":
        return True
    if enable_when.startswith("env:"):
        return bool(os.environ.get(enable_when[4:]))
    if enable_when.startswith("detect:"):
        return shutil.which(enable_when[7:]) is not None
    if enable_when == "trust:project":
        return os.environ.get("PSYCLAW_TRUST_HOST_MCP", "").strip().lower() in {"1", "true", "yes"}
    return False


def health_check(entry: dict) -> dict:
    """对单个 MCP 条目做健康探测，返回 {"ok": bool, "detail": str, "optional": bool}。

    启用条件不满足 → ok=False（未启用，不是错误）。
    对 Python 内置服务器：检查模块是否可找到（find_spec，无副作用）。
    对 env:/detect: 服务器：条件满足即视为健康（无法进一步 ping）。
    商业可选服务器（origin: optional/user）未安装时带「可选」标注。
    """
    ew = entry.get("enable_when", "always")
    optional = is_optional(entry)
    optional_tag = "（可选，未安装）" if optional else "（可选）"
    if not _is_enabled(ew):
        if ew.startswith("env:"):
            return {"ok": False, "detail": f"未设置 ${ew[4:]}{optional_tag}", "optional": optional}
        if ew.startswith("detect:"):
            return {"ok": False, "detail": f"未检测到 {ew[7:]}{optional_tag}", "optional": optional}
        return {"ok": False, "detail": f"条件未满足: {ew}", "optional": optional}

    # Python 内置命令服务器 — 检查模块是否可找到
    command = entry.get("command", "")
    if command.startswith("python -m "):
        mod_path = command[len("python -m "):]
        try:
            spec = importlib.util.find_spec(mod_path)
        except (ModuleNotFoundError, ValueError):
            spec = None
        if spec is None:
            return {"ok": False, "detail": f"模块未找到: {mod_path}", "optional": optional}
        return {"ok": True, "detail": "模块就绪", "optional": optional}

    # Claude Code/Codex 的 stdio 配置必须至少能解析并找到可执行文件；
    # 不启动服务，避免 catalog 查询产生外部副作用。
    if entry.get("origin") in {"claude-code", "codex", "cc-switch"} and command:
        try:
            argv = shlex.split(command)
        except ValueError:
            argv = []
        if not argv:
            return {"ok": False, "detail": "宿主 MCP command 无法解析", "optional": optional}
        executable = Path(argv[0]).expanduser()
        if not executable.is_absolute():
            executable = Path(entry.get("_runtime_cwd") or ".") / executable
        found = executable.is_file() or shutil.which(argv[0]) is not None
        return {"ok": found,
                "detail": "宿主 stdio 命令就绪" if found else f"宿主 MCP 可执行文件未找到:{argv[0]}",
                "optional": optional}

    # env:/detect: — 条件已满足
    if ew.startswith("env:"):
        return {"ok": True, "detail": f"${ew[4:]} 已设置", "optional": optional}
    if ew.startswith("detect:"):
        bin_path = shutil.which(ew[7:])
        return {"ok": True, "detail": f"检测到 {bin_path}", "optional": optional}
    return {"ok": True, "detail": "就绪", "optional": optional}


def list_mcp_catalog(project_dir: str = ".") -> list:
    """读取目录(内置 + 用户 项目/全局)并标注启用条件与 origin/scope 归属。"""
    out = []
    for s in _all_entries(project_dir):
        ew = s.get("enable_when", "always")
        out.append({
            "name": s.get("name", "?"),
            "category": s.get("category", "?"),
            "origin": s.get("origin", "builtin"),
            "scope": s.get("_scope", "builtin"),
            "enable_when": ew,
            "enabled": _is_enabled(ew),
            "provides": s.get("provides", ""),
            "tools": s.get("tools", ""),
            "command": _display_command(s),
            "note": SERVER_NOTES.get(s.get("name", ""), ""),
            "transport": s.get("transport", "stdio" if s.get("command") else "unknown"),
            "config_path": s.get("config_path", ""),
            "env_keys": s.get("env_keys", []),
            "conflict": bool(s.get("_conflict", False)),
        })
    return out


def list_mcp_catalog_with_health(project_dir: str = ".", *, include_runtime: bool = False) -> list:
    """读取目录并附健康状态；默认绝不返回宿主配置中的环境变量值。"""
    out = []
    for s in _all_entries(project_dir):
        ew = s.get("enable_when", "always")
        enabled = _is_enabled(ew)
        h = health_check(s)
        item = {
            "name": s.get("name", "?"),
            "category": s.get("category", "?"),
            "origin": s.get("origin", "builtin"),
            "scope": s.get("_scope", "builtin"),
            "enable_when": ew,
            "enabled": enabled,
            "provides": s.get("provides", ""),
            "tools": s.get("tools", ""),
            "command": _display_command(s),
            "note": SERVER_NOTES.get(s.get("name", ""), ""),
            "transport": s.get("transport", "stdio" if s.get("command") else "unknown"),
            "config_path": s.get("config_path", ""),
            "env_keys": s.get("env_keys", []),
            "conflict": bool(s.get("_conflict", False)),
            "health": h,
        }
        if include_runtime:
            item["_runtime_env"] = s.get("_runtime_env", {})
            item["_runtime_cwd"] = s.get("_runtime_cwd", "")
            item["_runtime_command"] = s.get("command", "")
        out.append(item)
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
