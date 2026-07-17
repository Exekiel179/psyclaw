"""feat-159:psyclaw new <名>——文件夹组织的新建分析(全新状态,不继承旧 goal)。

用户在 psyclaw repo 目录跑,横幅读到上次会话的旧 goal(公正世界信念)。分析应
基于文件夹组织:new 建独立文件夹 + 标准脚手架 + 干净状态,cd 进去即隔离开工。
"""
from __future__ import annotations

import argparse

from psyclaw.scaffold import PROJECT_DIRS, create_analysis


def test_create_makes_folder_with_standard_dirs(tmp_path):
    r = create_analysis("bjw_study", base_dir=str(tmp_path))
    assert r["ok"] is True
    root = tmp_path / "bjw_study"
    assert root.is_dir()
    for d in PROJECT_DIRS:
        assert (root / d).is_dir(), f"缺标准目录 {d}"


def test_new_analysis_has_no_inherited_goal(tmp_path):
    """关键:即使 base_dir 有 goal,新分析文件夹是全新的(空 goal)。"""
    from psyclaw.tasks import get_goal, set_goal
    set_goal("旧目标 公正世界信念", project_dir=str(tmp_path))   # 父目录有旧 goal
    create_analysis("fresh", base_dir=str(tmp_path))
    assert get_goal(str(tmp_path / "fresh")) == ""              # 新分析不继承


def test_goal_option_writes_into_new_folder(tmp_path):
    from psyclaw.tasks import get_goal
    create_analysis("g", goal="拖延与学业倦怠", base_dir=str(tmp_path))
    assert "拖延" in get_goal(str(tmp_path / "g"))


def test_refuse_existing_nonempty(tmp_path):
    (tmp_path / "exists").mkdir()
    (tmp_path / "exists" / "file.txt").write_text("x", encoding="utf-8")
    r = create_analysis("exists", base_dir=str(tmp_path))
    assert r["ok"] is False and "已存在" in r["note"]


def test_reuse_empty_existing_ok(tmp_path):
    (tmp_path / "empty").mkdir()
    r = create_analysis("empty", base_dir=str(tmp_path))
    assert r["ok"] is True                                       # 空目录可复用


def test_reject_path_traversal(tmp_path):
    for bad in ("../escape", "/abs/path", "a/../../b"):
        r = create_analysis(bad, base_dir=str(tmp_path))
        assert r["ok"] is False and "名称" in r["note"]


def test_reject_empty_name(tmp_path):
    assert create_analysis("", base_dir=str(tmp_path))["ok"] is False


# ---- CLI 接线 -----------------------------------------------------------------

def test_cmd_new_wiring(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    from psyclaw.cli import cmd_new
    rc = cmd_new(argparse.Namespace(name="my_analysis", goal=None))
    assert rc == 0
    assert (tmp_path / "my_analysis" / "notes").is_dir()
    out = capsys.readouterr().out
    assert "my_analysis" in out and "cd" in out                 # 引导 cd 进去开工


def test_cmd_new_reports_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from psyclaw.cli import cmd_new
    rc = cmd_new(argparse.Namespace(name="../nope", goal=None))
    assert rc == 1
