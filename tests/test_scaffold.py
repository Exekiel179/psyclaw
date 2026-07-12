"""项目脚手架 scaffold.py 测试 — 目录结构 / clarify→概览 / 项目记忆。

均为确定性纯文件操作,不触网络/依赖安装。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from psyclaw.scaffold import (  # noqa: E402
    PROJECT_DIRS, ensure_dirs, generate_overview, init_project_memory,
    scaffold_project,
)

_CARD = """| 研究准备项 | 状态 | 内容 |
|---|---|---|
| research_question | resolved | 正念干预能否降低大学生焦虑 |
| design_type | resolved | 被试间随机对照 |
| analysis_plan | resolved | 独立样本 t 检验 |
| novelty | unresolved |  |
"""


def _write_card(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    (notes / "clarification.md").write_text(_CARD, encoding="utf-8")


# --- ensure_dirs -----------------------------------------------------------

def test_ensure_dirs_creates_all(tmp_path):
    created = ensure_dirs(str(tmp_path))
    assert set(created) == set(PROJECT_DIRS)
    for d in PROJECT_DIRS:
        assert (tmp_path / d).is_dir()


def test_ensure_dirs_idempotent(tmp_path):
    ensure_dirs(str(tmp_path))
    assert ensure_dirs(str(tmp_path)) == []   # 第二次无新建


# --- generate_overview -----------------------------------------------------

def test_overview_none_without_card(tmp_path):
    assert generate_overview(str(tmp_path)) is None


def test_overview_from_card(tmp_path):
    _write_card(tmp_path)
    out = generate_overview(str(tmp_path))
    assert out is not None and out.name == "project_overview.md"
    text = out.read_text(encoding="utf-8")
    assert "**研究问题**：正念干预能否降低大学生焦虑" in text
    assert "**设计类型**：被试间随机对照" in text
    assert "## A.问题与理论" in text          # 按澄清卡类别组织
    assert "已完成 3/17 个研究准备项" in text  # 只数 resolved
    assert "增量贡献" not in text              # unresolved 不进概览


# --- init_project_memory ---------------------------------------------------

def test_memory_skeleton_without_card(tmp_path):
    out = init_project_memory(str(tmp_path))
    assert out.name == "project_memory.md"
    text = out.read_text(encoding="utf-8")
    assert "## 研究目标" in text
    assert "## 决策日志" in text


def test_memory_seeded_from_card(tmp_path):
    _write_card(tmp_path)
    text = init_project_memory(str(tmp_path)).read_text(encoding="utf-8")
    assert "正念干预能否降低大学生焦虑" in text
    assert "被试间随机对照" in text            # 关键方法学决策播种


def test_memory_not_overwritten(tmp_path):
    out = init_project_memory(str(tmp_path))
    out.write_text("我手写的决策日志", encoding="utf-8")
    init_project_memory(str(tmp_path))          # 再跑
    assert out.read_text(encoding="utf-8") == "我手写的决策日志"   # 不覆盖


# --- scaffold_project ------------------------------------------------------

def test_scaffold_project_all(tmp_path):
    _write_card(tmp_path)
    res = scaffold_project(str(tmp_path))
    assert all((tmp_path / d).is_dir() for d in PROJECT_DIRS)  # 全部目录就绪
    assert res["overview"] is not None
    assert res["memory"].exists()
