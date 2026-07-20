"""白皮书里提到的命令/工具必须真实存在(feat-192)。

文档最容易烂在「命令被删了但文档还在教」——本轮就撞见两处:v0.18.0 删了内置量表库
和 norms 命令,但 `psyclaw scale` 的帮助文本仍写着「DASS/PHQ-9/GAD-7」、仍指引
「psyclaw norms <id>」。文档指向不存在的东西,和编造能力是一回事。

故把校验固化:白皮书里出现的每个 psyclaw 子命令、每个工具名,都要能在 argparse
与 build_tools 里找到。
"""
from __future__ import annotations

import re
from pathlib import Path

import psyclaw
from psyclaw.cli import build_parser
from psyclaw.toolloop import build_tools

DOC = Path(__file__).resolve().parents[1] / "docs" / "WHITEPAPER.md"


def _text() -> str:
    return DOC.read_text(encoding="utf-8")


def _cli_commands() -> set:
    return {name for act in build_parser()._subparsers._group_actions  # noqa: SLF001
            for name in (getattr(act, "choices", {}) or {})}


def test_whitepaper_exists():
    assert DOC.is_file()


def test_all_named_commands_exist():
    cmds = _cli_commands()
    used = set(re.findall(r"psyclaw ([a-z][a-z-]+)", _text()))
    missing = sorted(c for c in used if c not in cmds)
    assert not missing, f"白皮书提到不存在的命令:{missing}"


def test_all_named_tools_exist():
    tools = set(build_tools("."))
    used = set(re.findall(r"\b(lit_[a-z_]+|zotero_[a-z_]+)\b", _text()))
    missing = sorted(t for t in used if t not in tools)
    assert not missing, f"白皮书提到不存在的工具:{missing}"


def test_version_matches_package():
    """标题里的版本号要跟包版本一致,否则读者照着装到旧版。"""
    assert f"v{psyclaw.__version__}" in _text().split("\n")[0]


def test_no_removed_features_advertised():
    """v0.18.0 移除的东西不许再出现在文档里(内置量表/设计库/预注册命令/norms)。"""
    txt = _text()
    for gone in ("psyclaw norms", "psyclaw design", "psyclaw preregister"):
        assert gone not in txt, f"白皮书仍在教已移除的 {gone}"


def test_states_the_three_red_lines():
    """三条设计红线是本项目的立身之本,白皮书必须写明。"""
    txt = _text()
    assert "统计外移" in txt
    assert "零杜撰" in txt
    assert "半吊子内容库" in txt


def test_install_section_covers_domestic_network():
    txt = _text()
    assert "mirrors.aliyun.com" in txt          # 国内 PyPI 索引
    assert "gitclone.com" in txt                # 国内 GitHub 镜像
    assert "install.sh" in txt                  # 一键脚本
    assert "psyclaw-offline-" in txt            # 离线分发包


def test_discloses_known_limits():
    """已知边界必须写出来——夸大能力比少一个功能更伤人。"""
    txt = _text()
    assert "已知边界" in txt
    assert "不内置量表库" in txt
    assert "WebBridge 扩展" in txt
