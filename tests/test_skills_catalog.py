"""bug 修:内置 skill 对 chat 模型「隐藏」——除非用户 /skills 才见。

capability_map 只列 lit/scale/preregister 等命令,从不告诉模型有哪些结构化 skill
(sample-size/confound-control/pingouin…),模型自然不会主动路由到它们。修:每轮系统
提示注入内置 skill 目录(名+一句描述+怎么用),让模型知道并主动调用。
"""
from __future__ import annotations

from psyclaw.context import skills_catalog


def test_catalog_lists_builtin_skills():
    cat = skills_catalog(".")
    assert "sample-size" in cat
    assert "confound-control" in cat
    assert "pingouin" in cat


def test_catalog_tells_model_how_to_use():
    cat = skills_catalog(".")
    # 要有引导语,让模型知道这些是可主动调用的能力而非摆设
    assert "skill" in cat.lower() or "技能" in cat
    assert "SKILL.md" in cat or "读" in cat or "按" in cat


def test_catalog_failsafe(monkeypatch):
    # 发现失败不抛,返回空串(系统提示零污染)
    import psyclaw.context as ctx
    monkeypatch.setattr(ctx, "list_skills", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert skills_catalog(".") == ""


def test_catalog_in_system_prompt():
    from psyclaw.repl import _build_system_prompt
    sp = _build_system_prompt()
    assert "sample-size" in sp and "confound-control" in sp
