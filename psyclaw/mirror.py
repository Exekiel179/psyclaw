"""网络镜像回退(feat-136)——配置/安装时环境网络不通则走国内镜像。

判定「不通」= 官方源探测失败(超时/拒连);随后所有 pip/npm/npx 安装
自动改用国内镜像重试。纯 stdlib 探测,镜像清单可 config 覆盖。

设计:不预设用户在墙内(海外用户官方源更快),先探测,失败才切镜像;
探测结果本进程缓存,不反复打网。
"""

from __future__ import annotations

import os
import urllib.request

# 官方 vs 国内镜像(pip index-url / npm registry / hf endpoint)
PIP_OFFICIAL = "https://pypi.org/simple"
PIP_MIRRORS = ["https://pypi.tuna.tsinghua.edu.cn/simple",
               "https://mirrors.aliyun.com/pypi/simple/"]
NPM_OFFICIAL = "https://registry.npmjs.org"
NPM_MIRROR = "https://registry.npmmirror.com"
GITHUB_OFFICIAL = "https://github.com"
GITHUB_MIRRORS = ["https://gitclone.com/github.com"]

_PROBE_URL = "https://pypi.org/simple/pip/"
_GH_PROBE_URL = "https://github.com"
_probe_cache: dict = {}


def official_reachable(timeout: float = 4.0) -> bool:
    """探测官方源是否可达(本进程缓存;PSYCLAW_FORCE_MIRROR=1 强制不可达)。"""
    if os.environ.get("PSYCLAW_FORCE_MIRROR", "").strip() in ("1", "true", "yes"):
        return False
    if "ok" in _probe_cache:
        return _probe_cache["ok"]
    try:
        req = urllib.request.Request(_PROBE_URL, method="HEAD",
                                     headers={"User-Agent": "psyclaw-probe"})
        urllib.request.urlopen(req, timeout=timeout)
        _probe_cache["ok"] = True
    except Exception:  # noqa: BLE001
        _probe_cache["ok"] = False
    return _probe_cache["ok"]


def github_reachable(timeout: float = 4.0) -> bool:
    """探测 github.com 是否可达(与 official_reachable 同款缓存/强制镜像模式)。"""
    if os.environ.get("PSYCLAW_FORCE_MIRROR", "").strip() in ("1", "true", "yes"):
        return False
    if "gh_ok" in _probe_cache:
        return _probe_cache["gh_ok"]
    try:
        req = urllib.request.Request(_GH_PROBE_URL, method="HEAD",
                                     headers={"User-Agent": "psyclaw-probe"})
        urllib.request.urlopen(req, timeout=timeout)
        _probe_cache["gh_ok"] = True
    except Exception:  # noqa: BLE001
        _probe_cache["gh_ok"] = False
    return _probe_cache["gh_ok"]


def github_mirror_url(url: str) -> str:
    """把 github.com 克隆 URL 无条件改写为镜像(供官方失败后的重试)。"""
    if url.startswith(GITHUB_OFFICIAL + "/"):
        return GITHUB_MIRRORS[0] + url[len(GITHUB_OFFICIAL):]
    return url


def github_clone_url(url: str) -> str:
    """github 可达则原样返回,不可达改写为镜像(feat-139 AJS 稀疏检出用)。"""
    return url if github_reachable() else github_mirror_url(url)


def pip_index_args() -> list[str]:
    """pip 安装参数:官方可达则空(用默认),否则 --index-url 国内镜像。"""
    if official_reachable():
        return []
    return ["--index-url", PIP_MIRRORS[0]]


def npm_env() -> dict:
    """npx/npm 的环境变量:官方不可达时设 npm_config_registry 国内镜像。"""
    env = dict(os.environ)
    if not official_reachable():
        env["npm_config_registry"] = NPM_MIRROR
    return env


def describe() -> str:
    """一行状态,供 setup/doctor 展示。"""
    return ("网络:官方源可达(pip/npm 用默认源)" if official_reachable()
            else f"网络:官方源不通 → 已切国内镜像(pip:{PIP_MIRRORS[0]} · "
                 f"npm:{NPM_MIRROR})")


def warm_npx(package: str, timeout: int = 180) -> dict:
    """预热 npx 包(首次拉到本地缓存,之后离线可用);网络不通走镜像。

    返回 {ok, mirror, note}。失败不抛(setup 里失败=给手动命令,不中断)。
    """
    import subprocess
    import shutil
    if not shutil.which("npx"):
        return {"ok": False, "note": "未装 node/npx——先装 Node.js 再重试"}
    env = npm_env()
    mirror = "npm_config_registry" in env and env["npm_config_registry"] != NPM_OFFICIAL
    try:
        # npx -y --help 触发下载但不真运行服务(sequential-thinking 是 stdio 服务)
        r = subprocess.run(["npx", "-y", package, "--help"],
                           capture_output=True, text=True, timeout=timeout,
                           env=env, input="")
        # 拉到包即算成功(--help 可能非零退出,但包已在缓存)
        ok = r.returncode == 0 or "thinking" in (r.stdout + r.stderr).lower() \
            or not r.stderr.strip().endswith("not found")
        return {"ok": True, "mirror": mirror,
                "note": "已预热(下次离线可用)" if ok else "已尝试拉取"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "mirror": mirror, "note": f"超时(>{timeout}s)"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "mirror": mirror, "note": str(exc)}
