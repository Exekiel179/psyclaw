"""从 GitHub 装外部 skill 到 .claude/skills(浅克隆,镜像感知,fail-safe)。

psyclaw 只编排/消费外部 skill:git clone 到 .claude/skills,loader 自动发现。
国内网络不通走 gitclone 镜像(复用 mirror.py)。无 git / clone 失败给手动命令,绝不抛。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse


def repo_name(url: str) -> str:
    return (url or "").rstrip("/").split("/")[-1].replace(".git", "")


def install_skill_repo(url: str, dest_dir: str | None = None,
                       mirror: bool | None = None, runner=None,
                       ref: str | None = None,
                       sparse_paths: list[str] | None = None) -> dict:
    """git clone 外部 skill repo 到 .claude/skills/<name>。返回 {ok, path, note}。"""
    name = repo_name(url)
    parsed = urlparse(str(url))
    # Validate the transport before parsing a repository name so every unsafe
    # argv/protocol form receives the actionable HTTPS-only error.
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        return {"ok": False, "path": "",
                "note": "只接受 https://github.com 的 skill url(拒绝其他协议/主机,防命令注入)"}
    if (not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", name or "")
            or name in {".", ".."}):
        return {"ok": False, "path": "", "note": "无效的 repo url"}
    # 安全:只接受 https:// url——挡 argv flag 注入(--upload-pack=… 等被 git 当选项执行)
    # 与危险协议(ext:: / file: / ssh 命令走私)。下方 clone 再加 -- 哨兵双保险。
    if ref and not re.fullmatch(r"[A-Za-z0-9._/-]{1,128}", ref):
        return {"ok": False, "path": "", "note": "无效 ref"}
    sparse = []
    for item in sparse_paths or []:
        value = str(item).strip().replace("\\", "/")
        if (not value or value.startswith("/") or ".." in value.split("/")
                or not re.fullmatch(r"[A-Za-z0-9._/-]{1,256}", value)):
            return {"ok": False, "path": "", "note": "无效 sparse path"}
        sparse.append(value)
    dest = Path(dest_dir or ".claude/skills")
    target = dest / name
    try:
        target.resolve().relative_to(dest.resolve())
    except (OSError, ValueError):
        return {"ok": False, "path": str(target), "note": "安装目标越界"}
    if target.is_symlink():
        return {"ok": False, "path": str(target), "note": "拒绝写入 symlink 目标"}
    if target.exists() and any(target.iterdir()):
        return {"ok": True, "path": str(target), "note": f"{name} 已安装(目录非空)"}

    try:
        from psyclaw import mirror as mir
        use_mirror = mirror if mirror is not None else (not mir.github_reachable())
        clone_url = mir.github_clone_url(url) if use_mirror else url
    except Exception:  # noqa: BLE001
        clone_url = url

    dest.mkdir(parents=True, exist_ok=True)
    runner = runner or subprocess.run
    try:
        cmd = ["git", "clone", "--depth", "1"]
        if sparse:
            cmd += ["--filter", "blob:none", "--sparse"]
        if ref:
            cmd += ["--branch", ref]
        cmd += ["--", clone_url, str(target)]
        r = runner(cmd,
                   capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            return {"ok": False, "path": str(target),
                    "note": f"clone 失败:{(r.stderr or '')[:160]};"
                            f"手动:git clone -- {clone_url} {target}"}
        if sparse:
            sparse_run = runner(
                ["git", "-C", str(target), "sparse-checkout", "set", "--no-cone", *sparse],
                capture_output=True, text=True, timeout=300)
            if sparse_run.returncode != 0:
                return {"ok": False, "path": str(target),
                        "note": f"sparse checkout 失败:{(sparse_run.stderr or sparse_run.stdout)[:300]}"}
        return {"ok": True, "path": str(target), "note": f"已装 {name} → {target}"}
    except FileNotFoundError:
        return {"ok": False, "path": str(target),
                "note": f"未装 git;手动:git clone -- {clone_url} {target}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "path": str(target), "note": f"安装失败:{exc}"}
