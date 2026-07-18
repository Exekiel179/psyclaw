"""psyclaw 自更新——装了之后一条命令同步到最新(stdlib only)。

覆盖三种安装形态,各给正确的升级方式;国内网络自动走 gitclone + aliyun 镜像:
- source(在 git 工作树里,如本地 clone / editable):git pull;
- uv-tool(uv tool install 的隔离环境):uv tool install --force 重装到最新 ref;
- pip:pip install -U。

纯生成/编排命令,真执行走 subprocess(可注入,离线单测);绝不静默改环境——
CLI 层默认要用户确认、非 TTY 只打印。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = "Exekiel179/psyclaw"
_GH = f"https://github.com/{REPO}.git"
_GITCLONE = f"https://gitclone.com/github.com/{REPO}.git"
_ALIYUN = "https://mirrors.aliyun.com/pypi/simple/"
DEFAULT_REF = "master"


def _pkg_dir() -> Path:
    import psyclaw
    return Path(psyclaw.__file__).resolve().parent


def detect_install_kind(pkg_dir: Path | None = None,
                        executable: str | None = None) -> tuple[str, str | None]:
    """判断安装形态,返回 (kind, repo_dir)。

    kind:source(git 工作树,repo_dir=工作树根)/ uv-tool / pip。检测失败退 pip。
    """
    pkg_dir = pkg_dir or _pkg_dir()
    exe = (executable if executable is not None else (sys.executable or "")).replace("\\", "/")
    for anc in [pkg_dir, *pkg_dir.parents]:
        try:
            if (anc / ".git").exists():
                return "source", str(anc)
        except OSError:
            break
    path_s = str(pkg_dir).replace("\\", "/")
    if "/tools/" in exe and "uv" in exe or "/uv/tools/" in path_s:
        return "uv-tool", None
    return "pip", None


def upgrade_command(kind: str, repo_dir: str | None = None, mirror: bool = False,
                    ref: str = DEFAULT_REF) -> list[str]:
    """据安装形态给升级命令。mirror=True 用 gitclone 镜像。"""
    if kind == "source" and repo_dir:
        return ["git", "-C", repo_dir, "pull", "--ff-only"]
    url = _GITCLONE if mirror else _GH
    spec = f"git+{url}@{ref}"
    if kind == "uv-tool":
        return ["uv", "tool", "install", "--force", "--python", "3.12", spec]
    return [sys.executable or "python", "-m", "pip", "install", "-U", spec]


def env_for(mirror: bool) -> dict:
    """升级子进程环境;mirror=True 时把 PyPI 源指向 aliyun(装依赖走国内)。"""
    e = dict(os.environ)
    if mirror:
        e["UV_DEFAULT_INDEX"] = _ALIYUN
        e["PIP_INDEX_URL"] = _ALIYUN
    return e


def should_mirror(explicit: bool | None = None, reachable_fn=None) -> bool:
    """是否走国内镜像:显式优先;auto 探 GitHub 可达性,不通则镜像。探测失败不镜像。"""
    if explicit is not None:
        return explicit
    try:
        if reachable_fn is None:
            from psyclaw.mirror import github_reachable
            reachable_fn = github_reachable
        return not reachable_fn()
    except Exception:  # noqa: BLE001
        return False


def run_update(kind: str, repo_dir: str | None = None, mirror: bool = False,
               ref: str = DEFAULT_REF, runner=None) -> dict:
    """执行升级。返回 {ok, cmd, out}。runner 可注入,任何异常都不抛。"""
    cmd = upgrade_command(kind, repo_dir, mirror, ref)
    runner = runner or subprocess.run
    try:
        r = runner(cmd, env=env_for(mirror), capture_output=True, text=True, timeout=600)
        out = (getattr(r, "stdout", "") or "") + (getattr(r, "stderr", "") or "")
        return {"ok": r.returncode == 0, "cmd": cmd, "out": out}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "cmd": cmd, "out": f"执行失败:{exc}"}
