"""安装脚本默认 tag 必须跟当前版本一致——防发行后忘记同步 docs/install.*。

历史事故:v0.17.0 发布后 docs/install.sh / install.ps1 仍钉在 v0.15.0,
一键安装装到两个版本前的旧版且无人察觉。
"""
from __future__ import annotations

import re
from pathlib import Path

import psyclaw


def _read(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "docs" / name).read_text(encoding="utf-8")


def test_install_sh_default_tag_matches_version():
    m = re.search(r'TAG="\$\{PSYCLAW_VERSION:-v([0-9.]+)\}"', _read("install.sh"))
    assert m, "install.sh 未找到默认 TAG 定义(脚本结构变了?)"
    assert m.group(1) == psyclaw.__version__


def test_install_ps1_default_tag_matches_version():
    m = re.search(r'else\s*\{\s*"v([0-9.]+)"\s*\}', _read("install.ps1"))
    assert m, "install.ps1 未找到默认 Tag 定义(脚本结构变了?)"
    assert m.group(1) == psyclaw.__version__
