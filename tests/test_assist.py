"""feat-141:协助水平(novice/standard/expert)——一处设置,术语解释与
生成代码注释密度随水平变;standard 零变化不回归。"""
from __future__ import annotations

import argparse

from psyclaw.context import ASSIST_LEVELS, assist_directives


# ---- assist_directives 纯函数 --------------------------------------------------

def test_levels_registry():
    assert ASSIST_LEVELS == ("novice", "standard", "expert")


def test_standard_is_empty_zero_regression():
    assert assist_directives("standard") == ""       # 默认档零变化


def test_novice_more_explanation_and_comments():
    d = assist_directives("novice")
    assert "白话" in d or "解释" in d
    assert "注释" in d                                # 代码注释更密
    assert "例" in d                                  # 举例


def test_expert_terse():
    d = assist_directives("expert")
    assert "不展开" in d or "精简" in d
    assert "注释" in d                                # 只注释非显然决策


def test_unknown_level_fail_safe_empty():
    assert assist_directives("weird") == ""
    assert assist_directives("") == ""


# ---- 系统提示注入 --------------------------------------------------------------

def _fake_conf(monkeypatch, level):
    monkeypatch.setattr("psyclaw.config.load_config",
                        lambda: {"assist_level": level, "provider": "mock"})


def test_system_prompt_injects_novice(monkeypatch):
    _fake_conf(monkeypatch, "novice")
    from psyclaw.repl import _build_system_prompt
    assert "协助水平" in _build_system_prompt()


def test_system_prompt_standard_unchanged(monkeypatch):
    _fake_conf(monkeypatch, "standard")
    from psyclaw.repl import _build_system_prompt
    assert "协助水平" not in _build_system_prompt()   # 默认档提示零变化


# ---- CLI:psyclaw assist [level] ----------------------------------------------

def _patch_config_home(monkeypatch, tmp_path):
    import psyclaw.config as C
    monkeypatch.setattr(C, "HOME_DIR", tmp_path)
    monkeypatch.setattr(C, "CONFIG_FILE", tmp_path / "config.yaml")
    monkeypatch.setattr(C, "ENV_FILE", tmp_path / ".env")


def test_cmd_assist_set_and_show(tmp_path, monkeypatch, capsys):
    _patch_config_home(monkeypatch, tmp_path)
    from psyclaw.cli import cmd_assist
    rc = cmd_assist(argparse.Namespace(level="novice"))
    assert rc == 0
    assert "assist_level: novice" in (tmp_path / "config.yaml").read_text(encoding="utf-8")
    capsys.readouterr()
    rc = cmd_assist(argparse.Namespace(level=None))    # 查看
    assert rc == 0
    out = capsys.readouterr().out
    assert "novice" in out and "expert" in out         # 当前值 + 各档说明


def test_cmd_assist_rejects_unknown_level(tmp_path, monkeypatch):
    _patch_config_home(monkeypatch, tmp_path)
    from psyclaw.cli import cmd_assist
    rc = cmd_assist(argparse.Namespace(level="master"))
    assert rc == 2
    assert not (tmp_path / "config.yaml").exists()     # 非法值不落盘
