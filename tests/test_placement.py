"""feat-140:产物文件归位软约定——引导不强制,chat 自行决定,绝不搬文件。"""
from __future__ import annotations

import psyclaw.toolloop as TL
from psyclaw.scaffold import canonical_dir


# ---- canonical_dir 纯函数 ------------------------------------------------------

def test_canonical_dir_by_suffix():
    assert canonical_dir("fig1.png") == "figures"
    assert canonical_dir("plot.svg") == "figures"
    assert canonical_dir("analysis.py") == "scripts"
    assert canonical_dir("clean.R") == "scripts"
    assert canonical_dir("report.docx") == "outputs"
    assert canonical_dir("clean_data.csv") == "data/clean"


def test_canonical_dir_ambiguous_or_unknown_returns_none():
    assert canonical_dir("draft.md") is None        # 成稿/笔记二义,不武断
    assert canonical_dir("mystery.xyz") is None
    assert canonical_dir("") is None


# ---- save_file 软提示:裸文件名落根才提示,不改路径不搬文件 --------------------

def _save_tool(tmp_path):
    tools = TL.build_tools(str(tmp_path))
    return tools["save_file"]


def test_save_bare_filename_gets_placement_hint(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = _save_tool(tmp_path)["run"]({"path": "fig1.png", "content": "x"})
    assert (tmp_path / "fig1.png").exists()          # 文件仍按模型指定落根,不搬
    assert "figures/" in out                          # 回执附归位约定提示


def test_save_with_explicit_dir_no_hint(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "scripts").mkdir()
    out = _save_tool(tmp_path)["run"]({"path": "scripts/run.py", "content": "x"})
    assert "约定" not in out and "归位" not in out    # 显式目录尊重原样,零打扰


def test_save_unknown_type_no_hint(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = _save_tool(tmp_path)["run"]({"path": "notes.md", "content": "x"})
    assert "约定" not in out                          # 二义类型不武断提示


# ---- lean_core 目录约定(软引导主路径)+ 预算不破 ------------------------------

def test_lean_core_mentions_placement_convention():
    from psyclaw.context import LEAN_CORE_BUDGET, lean_core
    core = lean_core()
    assert "outputs/" in core and "figures/" in core and "scripts/" in core
    assert "显式" in core or "为准" in core            # 用户显式指定优先
    assert len(core) <= LEAN_CORE_BUDGET


def test_save_file_desc_mentions_convention(tmp_path):
    tools = TL.build_tools(str(tmp_path))
    assert "归位" in tools["save_file"]["desc"] or "约定" in tools["save_file"]["desc"]
