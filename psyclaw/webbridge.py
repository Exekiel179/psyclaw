"""Kimi WebBridge 接入(feat-108)——psyclaw 驱动用户**真实浏览器**(登录态复用)。

WebBridge = 本地守护进程(127.0.0.1:10086,HTTP)+ 浏览器扩展(用户在自己的
浏览器里安装,支持 Chrome/Edge/Arc 等 Chromium 系)。psyclaw 经 **stdlib urllib**
调它的 HTTP API——与统计外移/浏览器 MCP 同一铁律:能力外移,仓内零浏览器逻辑。

- 安装配置:``psyclaw webbridge install``(下载官方二进制 → 启动守护进程 →
  给各 agent 装技能 → 按**默认浏览器**给扩展安装指引);
- 默认浏览器识别:macOS 走 LaunchServices(http scheme 的 handler bundle id);
- agent 工具:守护进程可达时,``web__navigate/snapshot/click/fill/…`` 并入
  psyclaw agent 循环(side_effect=True 逐动作审批),机构库检索路线 B 可用
  **已登录的真实浏览器**执行——对齐浏览器桥文献综述教学文档的完整体验;
- 纪律:绝不自动 stop/restart/uninstall(与 Kimi 桌面端管理的守护进程打架,
  官方 operations 文档明确要求);登录动作永远由用户人工完成。
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from pathlib import Path

BIN = Path.home() / ".kimi-webbridge" / "bin" / "kimi-webbridge"
DAEMON = "http://127.0.0.1:10086"
HELP_URL = "https://www.kimi.com/zh-cn/features/webbridge"
# Chrome Web Store 官方扩展页(Arc/Chrome/Edge/Brave 均可从此安装)。
# 浏览器安全模型禁止静默装扩展(扩展可读全部页面,必须用户亲点「添加」)——
# psyclaw 能自动化的极限:打开确切安装页 + 轮询等连接,只给用户留一次点击。
EXTENSION_ID = "fldmhceldgbpfpkbgopacenieobmligc"
EXTENSION_STORE_URL = ("https://chromewebstore.google.com/detail/"
                       f"kimi-webbridge/{EXTENSION_ID}")
_DL_BASE = "https://cdn.kimi.com/webbridge"      # 与官方 install.sh 同源
_TIMEOUT = 30.0    # 真实浏览器开标签+页面加载可能不止 8 秒(活体实测 navigate 超时)
DEFAULT_SESSION = "psyclaw-research"

# macOS 常见浏览器 bundle id → 人读名(默认浏览器识别与扩展指引用)
_BUNDLE_NAMES = {
    "company.thebrowser.browser": "Arc",
    "com.google.chrome": "Google Chrome",
    "com.microsoft.edgemac": "Microsoft Edge",
    "com.brave.browser": "Brave",
    "org.chromium.chromium": "Chromium",
    "com.apple.safari": "Safari",
    "org.mozilla.firefox": "Firefox",
}
_CHROMIUM_BUNDLES = {"company.thebrowser.browser", "com.google.chrome",
                     "com.microsoft.edgemac", "com.brave.browser",
                     "org.chromium.chromium"}
# WebBridge 官方支持列表只有 Chrome / Edge。Arc 实测半兼容:查询类(list_tabs/
# find_tab)正常,但建标签会话要走 chrome.tabGroups——Arc 未实现,navigate 挂死。
_OFFICIAL_BUNDLES = {"com.google.chrome", "com.microsoft.edgemac"}


def officially_supported(db: dict | None) -> bool:
    return bool(db) and db.get("bundle_id") in _OFFICIAL_BUNDLES


def default_browser() -> dict | None:
    """macOS 默认浏览器 {name, bundle_id, chromium: bool};识别不出返回 None。

    读 LaunchServices 的 http scheme handler(纯 plistlib,无子进程)。
    """
    import sys
    if sys.platform != "darwin":
        return None
    import plistlib
    p = (Path.home() / "Library" / "Preferences" /
         "com.apple.LaunchServices" / "com.apple.launchservices.secure.plist")
    try:
        data = plistlib.loads(p.read_bytes())
    except Exception:  # noqa: BLE001
        return None
    for h in data.get("LSHandlers", []):
        if h.get("LSHandlerURLScheme") in ("http", "https"):
            bid = (h.get("LSHandlerRoleAll") or "").lower()
            if bid:
                return {"bundle_id": bid,
                        "name": _BUNDLE_NAMES.get(bid, bid),
                        "chromium": bid in _CHROMIUM_BUNDLES}
    return None


def binary_installed() -> bool:
    return BIN.is_file() and os.access(BIN, os.X_OK)


def daemon_status(timeout: float = 2.0) -> dict | None:
    """GET /status;守护进程不可达返回 None(不抛)。"""
    try:
        with urllib.request.urlopen(f"{DAEMON}/status", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return None


def start_daemon() -> bool:
    """启动守护进程(官方语义:幂等,已在运行则 no-op)。"""
    if not binary_installed():
        return False
    try:
        subprocess.run([str(BIN), "start"], capture_output=True, timeout=30)
    except Exception:  # noqa: BLE001
        return False
    return daemon_status() is not None


def download_binary(platform_tag: str | None = None,
                    _urlopen=urllib.request.urlopen) -> Path:
    """按官方 install.sh 同源地址下载二进制到标准路径并 chmod。"""
    if platform_tag is None:
        import platform as _pl
        import sys
        osname = "darwin" if sys.platform == "darwin" else "linux"
        arch = "arm64" if _pl.machine() in ("arm64", "aarch64") else "amd64"
        platform_tag = f"{osname}-{arch}"
    url = f"{_DL_BASE}/latest/releases/kimi-webbridge-{platform_tag}"
    BIN.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "psyclaw-webbridge"})
    with _urlopen(req, timeout=180) as r:
        BIN.write_bytes(r.read())
    os.chmod(BIN, 0o755)
    return BIN


def install_skill() -> str:
    """给检测到的 agent 运行时装 webbridge 技能(官方 install-skill -y)。"""
    try:
        res = subprocess.run([str(BIN), "install-skill", "-y"],
                             capture_output=True, text=True, timeout=60)
        return (res.stdout or "") + (res.stderr or "")
    except Exception as exc:  # noqa: BLE001
        return f"install-skill 失败:{exc}"


def call(action: str, args: dict | None = None,
         session: str = DEFAULT_SESSION, timeout: float = _TIMEOUT) -> dict:
    """POST /command。守护进程未起则自动 start 一次再重试(官方推荐,幂等)。

    返回守护进程的 JSON;连接层失败返回 {"success": False, "error": …}——
    错误如实透传,绝不假装成功。
    """
    body = json.dumps({"action": action, "args": args or {}, "session": session},
                      ensure_ascii=False).encode("utf-8")

    def _post() -> dict:
        req = urllib.request.Request(
            f"{DAEMON}/command", data=body,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

    try:
        return _post()
    except Exception:  # noqa: BLE001  # 守护进程可能没起:start 幂等,补一次
        if not start_daemon():
            return {"success": False,
                    "error": f"webbridge 守护进程不可达(psyclaw webbridge install 安装;"
                             f"帮助:{HELP_URL})"}
        try:
            return _post()
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": f"webbridge 调用失败:{exc}"}


def open_in_default_browser(url: str) -> bool:
    """在系统默认浏览器打开 URL(macOS open / Linux xdg-open / Windows start)。"""
    import sys
    try:
        if sys.platform == "darwin":
            argv = ["open", url]
        elif os.name == "nt":
            argv = ["cmd", "/c", "start", "", url]
        else:
            argv = ["xdg-open", url]
        subprocess.run(argv, capture_output=True, timeout=15)
        return True
    except Exception:  # noqa: BLE001
        return False


def wait_extension(timeout: float = 120.0, poll: float = 3.0,
                   on_tick=None) -> bool:
    """轮询守护进程直到扩展连接(用户在商店页点完「添加」即连上)。"""
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = daemon_status()
        if st and st.get("extension_connected"):
            return True
        if on_tick:
            on_tick()
        time.sleep(poll)
    return False


# ---------------------------------------------------------------------------
# agent 工具并入(与 merge_mcp_tools 同构;web__ 前缀,逐动作审批)
# ---------------------------------------------------------------------------

_TOOLS = {
    "navigate": ("打开 URL(newTab=true 开新标签;group_title 设标签组名)",
                 "url, newTab?, group_title?"),
    "find_tab": ("回到本会话开过的标签;active=true 借用用户当前浏览的标签",
                 "url, active?"),
    "snapshot": ("读当前页可达性树(定位元素用 @e 引用;读页面内容首选)", ""),
    "click": ("点击元素(@e 引用或 CSS 选择器)", "selector"),
    "fill": ("填输入框/富文本", "selector, value"),
    "evaluate": ("在当前页执行 JS(支持 async)", "code"),
    "screenshot": ("截图存文件(可选 selector 局部截图)", "format?, selector?, path?"),
    "list_tabs": ("列出本会话标签页", ""),
    "close_session": ("关闭本会话开的全部标签(任务收尾)", ""),
}


def _enabled() -> bool:
    return os.environ.get("PSYCLAW_WEBBRIDGE", "1").strip().lower() \
        not in ("0", "false", "no")


def merge_webbridge_tools(tools: dict) -> None:
    """binary 在位即并入 web__* 工具(daemon 懒启动);异常绝不外抛。"""
    if not _enabled():
        return
    try:
        if not binary_installed():
            return
        for name, (desc, args_hint) in _TOOLS.items():
            def _run(a, _n=name):
                a = dict(a or {})
                session = a.pop("session", DEFAULT_SESSION)
                out = call(_n, a, session=session)
                return json.dumps(out, ensure_ascii=False)[:6000]
            tools[f"web__{name}"] = {
                "desc": f"[WebBridge 真实浏览器] {desc}",
                "args": args_hint, "run": _run, "side_effect": True}
    except Exception:  # noqa: BLE001
        pass
