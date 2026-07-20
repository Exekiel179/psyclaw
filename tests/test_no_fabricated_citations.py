"""文献零杜撰:系统提示与写作 agent 都不得授权「凭记忆列文献」。

历史事故:系统提示原文写「凭记忆的文献条目一律标『⚠ 未核实』,哪怕确信存在」——
等于把编造合法化了,只要贴标签。真实后果:lit 检索调用失败后,模型严格照此执行,
输出「我切换为手动列举——基于记忆回顾…10 篇核心文献,均标注 ⚠ 未核实」,
整段书目全是编造的。学术场景里这比直接报错有害得多(读者会照着去引)。

正确契约:书目条目只能来自真实检索返回;检索失败 → 如实报失败并停,
而不是降级成记忆输出。本测试守住这条,防规则被改回「贴标签即可」。
"""
from __future__ import annotations

from pathlib import Path

from psyclaw.context import lean_core

WRITER = Path(__file__).resolve().parents[1] / "psyclaw" / "agents" / "writer.md"


def test_system_prompt_forbids_memory_citations():
    core = lean_core()
    assert "绝不凭记忆列文献" in core
    assert "只能来自真实检索返回" in core


def test_system_prompt_rejects_label_as_loophole():
    """关键:必须显式否定「标注未核实就能列」,否则模型会把标签当豁免。"""
    core = lean_core()
    assert "不是豁免" in core
    # 不得再出现「凭记忆…一律标未核实」这种授权式表述
    assert "凭记忆的文献条目一律标" not in core


def test_system_prompt_says_stop_on_search_failure():
    """检索失败时的正确动作要写死:报失败 + 停,不许降级成记忆列举。"""
    core = lean_core()
    assert "检索失败" in core
    assert "手动列举" in core          # 明令禁止这类话术


def test_writer_agent_forbids_memory_citations():
    txt = WRITER.read_text(encoding="utf-8")
    assert "凭记忆的书目条目一律不写" in txt
    assert "待补引清单" in txt          # 给出占位+回填的正路,而非编造
    # 旧的「凭记忆的引用一律标『未核实』」授权必须已被移除
    assert "凭记忆的引用一律标" not in txt
