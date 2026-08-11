"""上下文工程约束：角色提示只带契约，详细规范按需读取。"""

from __future__ import annotations

from psyclaw.loop import _AGENT_SHARED_RULES, _agent_prompt


def test_shared_agent_rules_point_to_source_of_truth():
    assert "gates/PSYCLAW.md" in _AGENT_SHARED_RULES
    assert "gates/rigor.md" in _AGENT_SHARED_RULES
    assert "未运行不报具体数值" in _AGENT_SHARED_RULES
    assert "未检索不列书目" in _AGENT_SHARED_RULES


def test_role_prompts_do_not_inline_full_gate_documents():
    for role in ("planner", "executor", "critic", "reviewer", "auditor", "writer"):
        prompt = _agent_prompt(role)
        assert "共享硬约束" in prompt
        assert "详细判据按需读取" in prompt
        assert "# 一、研究诚信原则" not in prompt
        assert "# 统计严谨性协议" not in prompt
        assert len(prompt) < 2200
